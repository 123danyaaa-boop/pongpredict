"""
PongPredict — Скрейпер данных

Собирает результаты матчей из нескольких источников:
  1. ITTF API (api.ittf.com) — официальные результаты
  2. World Table Tennis (worldtabletennis.com) — WTT турниры
  3. CSV импорт — ручной импорт данных

ВАЖНО: Запускай с паузами между запросами (delay в config.yaml)!
       Не забывай про rate limiting — мы не хотим быть забанены.

Использование:
    python -m data.scraper --source ittf --year 2024
    python -m data.scraper --source csv --file data/matches.csv
"""

import requests
import time
import json
import csv
import os
import sys
from datetime import datetime, date
from bs4 import BeautifulSoup
import yaml

# Добавляем корень проекта в path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.models import Player, Match, get_session, init_db

# === Загружаем конфиг ===
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)['scraping']


class BaseScraper:
    """Базовый класс для всех скрейперов"""

    def __init__(self):
        self.session_http = requests.Session()
        self.session_http.headers.update({
            'User-Agent': config['user_agent'],
            'Accept': 'application/json',
        })
        self.delay = config['delay']
        self.max_retries = config['max_retries']

    def _request(self, url, params=None):
        """
        Выполнить GET-запрос с паузой и повторами.
        Возвращает response или None при ошибке.
        """
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.delay)  # Пауза между запросами
                resp = self.session_http.get(url, params=params, timeout=15)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                print(f"  ⚠️ Попытка {attempt + 1}/{self.max_retries}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * 2)  # Увеличенная пауза при ошибке
        return None

    def _find_or_create_player(self, db_session, name, country=None, gender=None):
        """
        Найти игрока по имени или создать нового.
        Возвращает объект Player.
        """
        # Нормализуем имя (убираем лишние пробелы, приводим к title case)
        name = ' '.join(name.strip().split())

        player = db_session.query(Player).filter(
            Player.name == name
        ).first()

        if not player:
            player = Player(
                name=name,
                country=country,
                gender=gender,
            )
            db_session.add(player)
            db_session.flush()  # Получаем ID без коммита
            print(f"  + Новый игрок: {name} ({country or '?'})")

        return player


class ITTFScraper(BaseScraper):
    """
    Скрейпер для ITTF API.

    API документация: https://arcnovus.github.io/ittf-api/
    Базовый URL: http://api.ittf.com/1/

    Примечание: API может быть ограничен CORS (только *.ittf.com).
    В этом случае используйте серверные запросы.
    """

    BASE_URL = "http://api.ittf.com/1"

    def fetch_tournament_matches(self, tournament_id, event_type='MS'):
        """
        Получить все матчи турнира.

        Аргументы:
            tournament_id: ID турнира в ITTF
            event_type:    'MS' (мужские одиночные) или 'WS' (женские)

        Возвращает:
            list of dict с данными матчей, или пустой список
        """
        url = f"{self.BASE_URL}/matches/"
        params = {
            'tournamentId': tournament_id,
            'eventType': event_type,
            'state': 'COMPLETE',
        }

        resp = self._request(url, params=params)
        if not resp:
            print(f"  ❌ Не удалось получить матчи турнира {tournament_id}")
            return []

        try:
            data = resp.json()
            matches = data.get('data', [])
            print(f"  ✅ Турнир {tournament_id}: {len(matches)} матчей")
            return matches
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ❌ Ошибка парсинга ответа: {e}")
            return []

    def fetch_rankings(self, category='MS', limit=100):
        """
        Получить текущие рейтинги ITTF.

        Аргументы:
            category: 'MS' / 'WS' / 'MD' / 'WD' / 'XD'
            limit:    кол-во игроков (1-500)

        Возвращает:
            list of dict с рейтингами
        """
        url = f"{self.BASE_URL}/rankings/"
        params = {
            'category': category,
            'limit': limit,
        }

        resp = self._request(url, params=params)
        if not resp:
            return []

        try:
            data = resp.json()
            rankings = data.get('data', [])
            print(f"  ✅ Рейтинги {category}: {len(rankings)} игроков")
            return rankings
        except (json.JSONDecodeError, KeyError):
            return []

    def save_matches_to_db(self, raw_matches, tournament_name, tournament_level='regular'):
        """
        Сохранить матчи из ITTF API в базу данных.

        Аргументы:
            raw_matches:      список матчей из API
            tournament_name:  название турнира
            tournament_level: 'grand_slam' / 'major' / 'contender' / 'regular'
        """
        db = get_session()
        saved = 0

        for m in raw_matches:
            try:
                # Извлекаем данные игроков
                opp1 = m.get('opponentOne', {})
                opp2 = m.get('opponentTwo', {})

                name1 = opp1.get('name', '').strip()
                name2 = opp2.get('name', '').strip()

                if not name1 or not name2:
                    continue

                country1 = opp1.get('association', {}).get('id', None)
                country2 = opp2.get('association', {}).get('id', None)

                # Определяем победителя
                if opp1.get('hasWon'):
                    winner_name = name1
                elif opp2.get('hasWon'):
                    winner_name = name2
                else:
                    continue  # Нет победителя — пропускаем

                # Создаём/находим игроков
                p1 = self._find_or_create_player(db, name1, country1)
                p2 = self._find_or_create_player(db, name2, country2)
                winner = p1 if winner_name == name1 else p2

                # Формируем счёт
                score1 = opp1.get('score', 0)
                score2 = opp2.get('score', 0)
                score_str = f"{score1}-{score2}"

                # Дата матча
                date_str = m.get('startDateTime', '')
                try:
                    match_date = datetime.fromisoformat(date_str).date()
                except (ValueError, TypeError):
                    match_date = date.today()

                # Проверяем дубликат
                existing = db.query(Match).filter(
                    Match.date == match_date,
                    Match.player1_id == p1.id,
                    Match.player2_id == p2.id,
                ).first()

                if existing:
                    continue

                # Создаём матч
                match = Match(
                    date=match_date,
                    tournament=tournament_name,
                    tournament_level=tournament_level,
                    round_name=m.get('roundName', None),
                    player1_id=p1.id,
                    player2_id=p2.id,
                    winner_id=winner.id,
                    score=score_str,
                    source='ittf',
                )
                db.add(match)
                saved += 1

            except Exception as e:
                print(f"  ⚠️ Ошибка при обработке матча: {e}")
                continue

        db.commit()
        db.close()
        print(f"  💾 Сохранено {saved} матчей из '{tournament_name}'")
        return saved


class CSVImporter(BaseScraper):
    """
    Импортёр данных из CSV файла.

    Ожидаемый формат CSV:
        date,player1,player2,winner,score,tournament,level,country1,country2

    Пример строки:
        2024-03-15,Fan Zhendong,Ma Long,Fan Zhendong,4-2,WTT Champions,major,CHN,CHN
    """

    def import_file(self, filepath):
        """
        Импортировать матчи из CSV файла.

        Аргументы:
            filepath: путь к CSV файлу

        Возвращает:
            int — кол-во сохранённых матчей
        """
        if not os.path.exists(filepath):
            print(f"❌ Файл не найден: {filepath}")
            return 0

        db = get_session()
        saved = 0

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Парсим дату
                    match_date = datetime.strptime(row['date'], '%Y-%m-%d').date()

                    # Создаём/находим игроков
                    p1 = self._find_or_create_player(
                        db, row['player1'], row.get('country1')
                    )
                    p2 = self._find_or_create_player(
                        db, row['player2'], row.get('country2')
                    )

                    # Определяем победителя
                    winner_name = row['winner'].strip()
                    if winner_name == p1.name:
                        winner = p1
                    elif winner_name == p2.name:
                        winner = p2
                    else:
                        print(f"  ⚠️ Победитель '{winner_name}' не совпадает с игроками")
                        continue

                    # Проверяем дубликат
                    existing = db.query(Match).filter(
                        Match.date == match_date,
                        Match.player1_id == p1.id,
                        Match.player2_id == p2.id,
                    ).first()

                    if existing:
                        continue

                    # Создаём матч
                    match = Match(
                        date=match_date,
                        tournament=row.get('tournament', 'Unknown'),
                        tournament_level=row.get('level', 'regular'),
                        player1_id=p1.id,
                        player2_id=p2.id,
                        winner_id=winner.id,
                        score=row.get('score', ''),
                        source='csv',
                    )
                    db.add(match)
                    saved += 1

                    # Обновляем счётчики
                    p1.total_matches = (p1.total_matches or 0) + 1
                    p2.total_matches = (p2.total_matches or 0) + 1
                    winner.total_wins = (winner.total_wins or 0) + 1

                except Exception as e:
                    print(f"  ⚠️ Ошибка в строке: {e}")
                    continue

        db.commit()
        db.close()
        print(f"✅ Импортировано {saved} матчей из '{filepath}'")
        return saved


class WTTScraper(BaseScraper):
    """
    Скрейпер для World Table Tennis (worldtabletennis.com).

    Сайт рендерится через JavaScript, поэтому нужно искать
    внутренний API, который он использует для загрузки данных.
    """

    # Потенциальные API endpoints (нужно проверить через DevTools браузера)
    BASE_URL = "https://www.worldtabletennis.com"

    def discover_api(self):
        """
        Попытаться найти JSON API за сайтом WTT.

        ИНСТРУКЦИЯ для Даньки:
        1. Открой https://www.worldtabletennis.com/matches в Chrome
        2. Открой DevTools → Network → XHR
        3. Перезагрузи страницу
        4. Ищи запросы к API (обычно содержат /api/ в URL)
        5. Скопируй URL и добавь сюда

        Типичные паттерны:
        - /api/v1/matches?...
        - /api/events/...
        - /graphql
        """
        print("🔍 Для обнаружения API эндпоинтов WTT:")
        print("   1. Открой https://www.worldtabletennis.com/matches")
        print("   2. Chrome DevTools → Network → XHR")
        print("   3. Найди запросы к API")
        print("   4. Добавь URL в WTTScraper.BASE_API_URL")
        print()
        print("   Альтернатива: используй CSVImporter для ручного импорта")


def create_sample_csv():
    """
    Создаёт пример CSV файла с несколькими матчами для тестирования.
    """
    sample_data = [
        # date, player1, player2, winner, score, tournament, level, country1, country2
        ("2024-01-15", "Fan Zhendong", "Ma Long", "Fan Zhendong", "4-2",
         "WTT Champions Incheon", "major", "CHN", "CHN"),
        ("2024-01-15", "Wang Chuqin", "Lin Shidong", "Wang Chuqin", "4-1",
         "WTT Champions Incheon", "major", "CHN", "CHN"),
        ("2024-01-16", "Fan Zhendong", "Wang Chuqin", "Wang Chuqin", "4-3",
         "WTT Champions Incheon", "major", "CHN", "CHN"),
        ("2024-01-14", "Hugo Calderano", "Tomokazu Harimoto", "Hugo Calderano", "4-2",
         "WTT Champions Incheon", "major", "BRA", "JPN"),
        ("2024-01-14", "Liang Jingkun", "Patrick Franziska", "Liang Jingkun", "4-0",
         "WTT Champions Incheon", "major", "CHN", "GER"),
        ("2024-02-10", "Fan Zhendong", "Hugo Calderano", "Fan Zhendong", "4-1",
         "WTT Contender Lagos", "contender", "CHN", "BRA"),
        ("2024-02-10", "Ma Long", "Liang Jingkun", "Ma Long", "4-3",
         "WTT Contender Lagos", "contender", "CHN", "CHN"),
        ("2024-02-11", "Fan Zhendong", "Ma Long", "Ma Long", "4-2",
         "WTT Contender Lagos", "contender", "CHN", "CHN"),
        ("2024-03-05", "Tomokazu Harimoto", "Lin Shidong", "Tomokazu Harimoto", "4-1",
         "WTT Star Contender Doha", "contender", "JPN", "CHN"),
        ("2024-03-06", "Wang Chuqin", "Tomokazu Harimoto", "Wang Chuqin", "4-2",
         "WTT Star Contender Doha", "contender", "CHN", "JPN"),
        ("2024-03-20", "Fan Zhendong", "Patrick Franziska", "Fan Zhendong", "4-0",
         "WTT Feeder Düsseldorf", "regular", "CHN", "GER"),
        ("2024-03-21", "Hugo Calderano", "Wang Chuqin", "Wang Chuqin", "4-3",
         "WTT Feeder Düsseldorf", "regular", "BRA", "CHN"),
        ("2024-04-10", "Ma Long", "Hugo Calderano", "Hugo Calderano", "4-2",
         "WTT Champions Chongqing", "major", "CHN", "BRA"),
        ("2024-04-11", "Fan Zhendong", "Liang Jingkun", "Fan Zhendong", "4-1",
         "WTT Champions Chongqing", "major", "CHN", "CHN"),
        ("2024-04-12", "Fan Zhendong", "Hugo Calderano", "Fan Zhendong", "4-3",
         "WTT Champions Chongqing", "major", "CHN", "BRA"),
    ]

    filepath = os.path.join(os.path.dirname(__file__), '..', 'data', 'sample_matches.csv')
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'date', 'player1', 'player2', 'winner', 'score',
            'tournament', 'level', 'country1', 'country2'
        ])
        writer.writerows(sample_data)

    print(f"✅ Создан пример CSV: {filepath}")
    print(f"   {len(sample_data)} матчей, 7 игроков")
    return filepath


# === CLI запуск ===
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='PongPredict — Сбор данных')
    parser.add_argument('--source', choices=['ittf', 'csv', 'sample', 'discover'],
                        default='sample',
                        help='Источник данных')
    parser.add_argument('--file', type=str, help='Путь к CSV файлу')
    parser.add_argument('--tournament-id', type=int, help='ID турнира для ITTF')

    args = parser.parse_args()

    # Инициализируем базу
    init_db()

    if args.source == 'sample':
        # Создаём и импортируем тестовые данные
        print("\n🏓 PongPredict — Загрузка тестовых данных\n")
        filepath = create_sample_csv()
        importer = CSVImporter()
        importer.import_file(filepath)

    elif args.source == 'csv':
        if not args.file:
            print("❌ Укажи --file для CSV импорта")
            sys.exit(1)
        importer = CSVImporter()
        importer.import_file(args.file)

    elif args.source == 'ittf':
        if not args.tournament_id:
            print("❌ Укажи --tournament-id для ITTF")
            sys.exit(1)
        scraper = ITTFScraper()
        matches = scraper.fetch_tournament_matches(args.tournament_id)
        if matches:
            scraper.save_matches_to_db(matches, f"Tournament {args.tournament_id}")

    elif args.source == 'discover':
        scraper = WTTScraper()
        scraper.discover_api()
