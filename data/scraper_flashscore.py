"""
PongPredict — Flashscore Scraper (настольный теннис)

Скрейпит результаты матчей по настольному теннису с flashscore.com.
Использует Selenium, потому что сайт рендерится через JavaScript.

ВАЖНО: Перед запуском установи:
    pip install selenium webdriver-manager

Запуск:
    python -m data.scraper_flashscore                    # вчерашние результаты
    python -m data.scraper_flashscore --days 7           # последние 7 дней
    python -m data.scraper_flashscore --date 2025-03-15  # конкретная дата

Поддерживаемые турниры:
    - WTT Champions / Grand Smash / Star Contender / Contender / Feeder
    - ITTF World Championships
    - Olympic Games
    - Бундеслига (Tischtennis Bundesliga)
    - Чемпионаты по странам
"""

import time
import re
import sys
import os
import csv
import json
import argparse
from datetime import datetime, date, timedelta

# Добавляем корень проекта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException, WebDriverException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️ Selenium не установлен. Установи: pip install selenium webdriver-manager")

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER = True
except ImportError:
    WEBDRIVER_MANAGER = False

from data.models import Player, Match, get_session, init_db


# === Конфигурация ===
FLASHSCORE_BASE = "https://www.flashscore.com/table-tennis"
FLASHSCORE_RESULTS = f"{FLASHSCORE_BASE}/results/"

# Маппинг уровней турниров по ключевым словам в названии
LEVEL_KEYWORDS = {
    'grand_slam': ['Olympic', 'World Championships', 'World Cup'],
    'major': ['Champions', 'Grand Smash', 'Finals', 'WTT Cup'],
    'contender': ['Star Contender', 'Contender'],
    'regular': ['Feeder', 'Challenger'],
    'league': ['Bundesliga', 'Super League', 'Premier League', 'T2 Diamond',
               'Liga Pro', 'Setka Cup', 'TT-CUP', 'Win Cup'],
}


def classify_tournament_level(tournament_name):
    """Определить уровень турнира по его названию."""
    name_lower = tournament_name.lower()
    for level, keywords in LEVEL_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in name_lower:
                return level
    return 'regular'


class FlashscoreScraper:
    """
    Скрейпер матчей настольного тенниса с Flashscore.

    Использование:
        scraper = FlashscoreScraper(headless=True)
        matches = scraper.scrape_results(days_back=7)
        scraper.save_to_db(matches)
        scraper.close()
    """

    def __init__(self, headless=True):
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium не установлен!")

        self.options = Options()
        if headless:
            self.options.add_argument('--headless=new')
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--window-size=1920,1080')
        self.options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # Инициализация драйвера
        try:
            if WEBDRIVER_MANAGER:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=self.options)
            else:
                self.driver = webdriver.Chrome(options=self.options)
            print("✅ Chrome WebDriver запущен")
        except WebDriverException as e:
            print(f"❌ Не удалось запустить Chrome: {e}")
            print("   Попробуй: pip install webdriver-manager")
            raise

        self.driver.implicitly_wait(5)

    def close(self):
        """Закрыть браузер."""
        if hasattr(self, 'driver'):
            self.driver.quit()
            print("🔒 Браузер закрыт")

    def _accept_cookies(self):
        """Принять куки (Flashscore показывает баннер)."""
        try:
            cookie_btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            cookie_btn.click()
            time.sleep(1)
        except (TimeoutException, NoSuchElementException):
            pass  # Баннера нет — ок

    def _load_more_results(self, max_clicks=5):
        """Нажать 'Показать больше' для загрузки старых результатов."""
        for i in range(max_clicks):
            try:
                show_more = self.driver.find_element(
                    By.CSS_SELECTOR, "a.event__more.event__more--static"
                )
                self.driver.execute_script("arguments[0].click();", show_more)
                time.sleep(2)
                print(f"  📄 Загружена страница {i + 2}")
            except NoSuchElementException:
                break  # Больше нет кнопки

    def scrape_results(self, days_back=1, target_date=None, load_pages=3):
        """
        Скрейпить результаты матчей.

        Аргументы:
            days_back:    сколько дней назад скрейпить (по умолчанию 1 — вчера)
            target_date:  конкретная дата (формат YYYY-MM-DD), перезаписывает days_back
            load_pages:   сколько раз нажать "показать ещё" (больше = старее данные)

        Возвращает:
            list of dict: [{
                'date': '2025-03-15',
                'player1': 'Fan Zhendong',
                'player2': 'Wang Chuqin',
                'winner': 'Fan Zhendong',
                'score': '4-2',
                'sets_detail': '11-7,9-11,11-5,11-8,13-11,11-6',
                'tournament': 'WTT Star Contender Bangkok',
                'tournament_level': 'contender',
                'country1': None,
                'country2': None,
            }, ...]
        """
        print(f"\n🌐 Загружаю Flashscore: настольный теннис...")
        self.driver.get(FLASHSCORE_RESULTS)
        time.sleep(3)
        self._accept_cookies()

        # Загружаем больше результатов
        self._load_more_results(max_clicks=load_pages)

        matches = []
        current_tournament = ""
        current_tournament_level = "regular"

        try:
            # Flashscore структура: блоки турниров с матчами внутри
            # Ищем все строки событий
            event_rows = self.driver.find_elements(
                By.CSS_SELECTOR, "div.event__match, div.event__header"
            )

            print(f"  📊 Найдено {len(event_rows)} элементов на странице")

            for row in event_rows:
                try:
                    classes = row.get_attribute("class") or ""

                    # Заголовок турнира
                    if "event__header" in classes:
                        try:
                            title_el = row.find_element(
                                By.CSS_SELECTOR, "span.event__title--name"
                            )
                            current_tournament = title_el.text.strip()
                            current_tournament_level = classify_tournament_level(
                                current_tournament
                            )
                        except NoSuchElementException:
                            pass
                        continue

                    # Строка матча
                    if "event__match" in classes:
                        match_data = self._parse_match_row(
                            row, current_tournament, current_tournament_level
                        )
                        if match_data:
                            matches.append(match_data)

                except Exception as e:
                    continue  # Пропускаем проблемные строки

        except Exception as e:
            print(f"  ❌ Ошибка при парсинге: {e}")

        # Фильтруем по дате если нужно
        if target_date:
            matches = [m for m in matches if m.get('date') == target_date]
        elif days_back:
            cutoff = (date.today() - timedelta(days=days_back)).isoformat()
            matches = [m for m in matches if m.get('date', '') >= cutoff]

        print(f"  ✅ Спарсено {len(matches)} матчей")
        return matches

    def _parse_match_row(self, row, tournament, level):
        """Распарсить одну строку матча."""
        try:
            # Имена игроков
            participants = row.find_elements(
                By.CSS_SELECTOR, "div.event__participant"
            )
            if len(participants) < 2:
                return None

            player1 = participants[0].text.strip()
            player2 = participants[1].text.strip()

            if not player1 or not player2:
                return None

            # Счёт по сетам
            scores = row.find_elements(
                By.CSS_SELECTOR, "div.event__score"
            )

            score_str = ""
            winner = None

            if len(scores) >= 2:
                s1 = scores[0].text.strip()
                s2 = scores[1].text.strip()

                try:
                    score1 = int(s1)
                    score2 = int(s2)
                    score_str = f"{score1}-{score2}"

                    if score1 > score2:
                        winner = player1
                    elif score2 > score1:
                        winner = player2
                except ValueError:
                    return None  # Незавершённый матч

            if not winner:
                return None

            # Дата (из атрибута или текущая)
            match_date = date.today().isoformat()
            try:
                time_el = row.find_element(
                    By.CSS_SELECTOR, "div.event__time"
                )
                time_text = time_el.text.strip()
                # Flashscore показывает дату как "15.03." или "15.03.2025"
                date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})?', time_text)
                if date_match:
                    day = int(date_match.group(1))
                    month = int(date_match.group(2))
                    year = int(date_match.group(3)) if date_match.group(3) else date.today().year
                    match_date = f"{year}-{month:02d}-{day:02d}"
            except NoSuchElementException:
                pass

            # Детали счёта по сетам (если есть)
            sets_detail = ""
            try:
                set_scores = row.find_elements(
                    By.CSS_SELECTOR, "div.event__part"
                )
                if set_scores:
                    sets_detail = ",".join(s.text.strip() for s in set_scores if s.text.strip())
            except NoSuchElementException:
                pass

            return {
                'date': match_date,
                'player1': player1,
                'player2': player2,
                'winner': winner,
                'score': score_str,
                'sets_detail': sets_detail,
                'tournament': tournament,
                'tournament_level': level,
                'country1': None,
                'country2': None,
            }

        except Exception:
            return None

    def save_to_db(self, matches):
        """
        Сохранить спарсенные матчи в базу данных.

        Аргументы:
            matches: список dict из scrape_results()

        Возвращает:
            int — кол-во сохранённых матчей
        """
        if not matches:
            print("  ℹ️ Нет матчей для сохранения")
            return 0

        db = get_session()
        saved = 0

        for m in matches:
            try:
                # Находим или создаём игроков
                p1 = db.query(Player).filter(Player.name == m['player1']).first()
                if not p1:
                    p1 = Player(name=m['player1'], country=m.get('country1'))
                    db.add(p1)
                    db.flush()

                p2 = db.query(Player).filter(Player.name == m['player2']).first()
                if not p2:
                    p2 = Player(name=m['player2'], country=m.get('country2'))
                    db.add(p2)
                    db.flush()

                winner = p1 if m['winner'] == m['player1'] else p2

                # Проверяем дубликат
                match_date = datetime.strptime(m['date'], '%Y-%m-%d').date()
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
                    tournament=m['tournament'],
                    tournament_level=m['tournament_level'],
                    player1_id=p1.id,
                    player2_id=p2.id,
                    winner_id=winner.id,
                    score=m['score'],
                    sets_detail=m.get('sets_detail', ''),
                    source='flashscore',
                )
                db.add(match)

                # Обновляем счётчики
                p1.total_matches = (p1.total_matches or 0) + 1
                p2.total_matches = (p2.total_matches or 0) + 1
                winner.total_wins = (winner.total_wins or 0) + 1

                saved += 1

            except Exception as e:
                print(f"  ⚠️ Ошибка: {e}")
                continue

        db.commit()
        db.close()
        print(f"  💾 Сохранено {saved} новых матчей в базу")
        return saved

    def save_to_csv(self, matches, filepath):
        """
        Сохранить матчи в CSV для ручной проверки.

        Аргументы:
            matches:  список dict
            filepath: путь к выходному CSV
        """
        if not matches:
            return

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'date', 'player1', 'player2', 'winner', 'score',
                'sets_detail', 'tournament', 'tournament_level',
                'country1', 'country2'
            ])
            writer.writeheader()
            writer.writerows(matches)

        print(f"  📁 CSV сохранён: {filepath} ({len(matches)} матчей)")


class FlashscoreAPIParser:
    """
    Парсер внутреннего API Flashscore (без Selenium).

    Flashscore загружает данные через AJAX запросы.
    Этот класс пытается использовать их внутренний API напрямую.

    ИНСТРУКЦИЯ ПО ОБНАРУЖЕНИЮ API:
    1. Открой https://www.flashscore.com/table-tennis/results/ в Chrome
    2. DevTools → Network → XHR
    3. Перезагрузи страницу
    4. Ищи запросы к:
       - *.flashscore.com/x/feed/*
       - d.flashscore.com/*
       - local-*.flashscore.com/*
    5. Скопируй URL и заголовки (особенно x-fsign)

    Типичный паттерн URL:
    https://d.flashscore.com/x/feed/f_1_0_table-tennis_1
    (где 1 = results, 0 = page)
    """

    # Известные эндпоинты Flashscore (могут меняться)
    FEED_BASE = "https://d.flashscore.com/x/feed"
    SPORT_ID = "table-tennis"

    def __init__(self):
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.flashscore.com/',
            'X-Requested-With': 'XMLHttpRequest',
        })

    def try_discover_api(self):
        """
        Попробовать обнаружить рабочий API эндпоинт.
        Возвращает True если удалось.
        """
        # Список потенциальных URL для проверки
        test_urls = [
            f"{self.FEED_BASE}/f_1_0_{self.SPORT_ID}_1",
            f"{self.FEED_BASE}/f_2_0_{self.SPORT_ID}_1",
            f"https://d.flashscore.com/x/feed/tr_1_{self.SPORT_ID}",
        ]

        for url in test_urls:
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200 and len(resp.text) > 100:
                    print(f"  ✅ API найден: {url}")
                    print(f"     Ответ: {len(resp.text)} байт")
                    return url
            except Exception:
                continue

        print("  ❌ API не обнаружен автоматически")
        print("  💡 Используй Selenium-скрейпер или ручной DevTools анализ")
        return None


class SetkaImporter:
    """
    Импортёр датасета Setka Cup с Kaggle.

    Setka Cup — украинская лига настольного тенниса с ежедневными турнирами.
    Датасет содержит ~7,851 матчей за сентябрь 2022.

    Скачай с Kaggle:
    https://www.kaggle.com/datasets/medaxone/one-month-table-tennis-dataset

    Формат CSV Setka Cup:
    match_id, event_id, event_date, player1, player2, player1_sets, player2_sets,
    game1_p1, game1_p2, game2_p1, game2_p2, game3_p1, game3_p2, ...
    """

    def import_setka(self, filepath):
        """
        Импортировать Setka Cup CSV в базу данных.

        Аргументы:
            filepath: путь к CSV файлу с Kaggle

        Возвращает:
            int — кол-во импортированных матчей
        """
        if not os.path.exists(filepath):
            print(f"❌ Файл не найден: {filepath}")
            print("   Скачай с: https://www.kaggle.com/datasets/medaxone/one-month-table-tennis-dataset")
            return 0

        db = get_session()
        saved = 0

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Адаптируем под разные форматы колонок Setka CSV
                    p1_name = (row.get('player1') or row.get('player_1')
                               or row.get('home') or '').strip()
                    p2_name = (row.get('player2') or row.get('player_2')
                               or row.get('away') or '').strip()

                    if not p1_name or not p2_name:
                        continue

                    # Счёт по сетам
                    s1 = int(row.get('player1_sets', row.get('home_sets', 0)) or 0)
                    s2 = int(row.get('player2_sets', row.get('away_sets', 0)) or 0)

                    if s1 == 0 and s2 == 0:
                        continue  # Нет результата

                    score_str = f"{s1}-{s2}"
                    winner_name = p1_name if s1 > s2 else p2_name

                    # Дата
                    date_str = row.get('event_date', row.get('date', ''))
                    try:
                        # Пробуем разные форматы дат
                        for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S']:
                            try:
                                match_date = datetime.strptime(date_str.strip(), fmt).date()
                                break
                            except ValueError:
                                continue
                        else:
                            match_date = date(2022, 9, 15)  # Дефолт для Setka Sept 2022
                    except Exception:
                        match_date = date(2022, 9, 15)

                    # Игроки
                    p1 = db.query(Player).filter(Player.name == p1_name).first()
                    if not p1:
                        p1 = Player(name=p1_name)
                        db.add(p1)
                        db.flush()

                    p2 = db.query(Player).filter(Player.name == p2_name).first()
                    if not p2:
                        p2 = Player(name=p2_name)
                        db.add(p2)
                        db.flush()

                    winner = p1 if winner_name == p1_name else p2

                    # Проверка дубликата
                    existing = db.query(Match).filter(
                        Match.date == match_date,
                        Match.player1_id == p1.id,
                        Match.player2_id == p2.id,
                    ).first()
                    if existing:
                        continue

                    # Собираем детали сетов
                    sets_parts = []
                    for i in range(1, 6):
                        g1 = row.get(f'game{i}_p1', row.get(f'set{i}_home', ''))
                        g2 = row.get(f'game{i}_p2', row.get(f'set{i}_away', ''))
                        if g1 and g2:
                            sets_parts.append(f"{g1}-{g2}")

                    match = Match(
                        date=match_date,
                        tournament="Setka Cup",
                        tournament_level="league",
                        player1_id=p1.id,
                        player2_id=p2.id,
                        winner_id=winner.id,
                        score=score_str,
                        sets_detail=",".join(sets_parts),
                        source='setka_kaggle',
                    )
                    db.add(match)

                    p1.total_matches = (p1.total_matches or 0) + 1
                    p2.total_matches = (p2.total_matches or 0) + 1
                    winner.total_wins = (winner.total_wins or 0) + 1

                    saved += 1

                    # Коммитим каждые 500 записей
                    if saved % 500 == 0:
                        db.commit()
                        print(f"  ... {saved} матчей импортировано")

                except Exception as e:
                    continue

        db.commit()
        db.close()
        print(f"✅ Setka Cup: импортировано {saved} матчей")
        return saved


# === CLI ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PongPredict — Flashscore Scraper')
    parser.add_argument('--mode', choices=['selenium', 'api', 'setka', 'guide'],
                        default='guide', help='Режим работы')
    parser.add_argument('--days', type=int, default=1,
                        help='Сколько дней назад скрейпить')
    parser.add_argument('--date', type=str, help='Конкретная дата (YYYY-MM-DD)')
    parser.add_argument('--file', type=str, help='Путь к CSV для Setka импорта')
    parser.add_argument('--output', type=str, default='data/scraped_matches.csv',
                        help='Путь для сохранения CSV')
    parser.add_argument('--pages', type=int, default=3,
                        help='Сколько страниц загрузить')

    args = parser.parse_args()
    init_db()

    if args.mode == 'selenium':
        # === Selenium скрейпинг ===
        scraper = FlashscoreScraper(headless=True)
        try:
            matches = scraper.scrape_results(
                days_back=args.days,
                target_date=args.date,
                load_pages=args.pages,
            )
            if matches:
                scraper.save_to_csv(matches, args.output)
                scraper.save_to_db(matches)
        finally:
            scraper.close()

    elif args.mode == 'api':
        # === Попытка использовать API ===
        parser_api = FlashscoreAPIParser()
        parser_api.try_discover_api()

    elif args.mode == 'setka':
        # === Импорт Setka Cup ===
        if not args.file:
            print("❌ Укажи --file для Setka импорта")
            print("   Скачай CSV: https://www.kaggle.com/datasets/medaxone/one-month-table-tennis-dataset")
        else:
            importer = SetkaImporter()
            importer.import_setka(args.file)

    elif args.mode == 'guide':
        # === Гайд по сбору данных ===
        print("""
╔══════════════════════════════════════════════════════╗
║  🏓 PongPredict — Гайд по сбору данных             ║
╚══════════════════════════════════════════════════════╝

📌 СПОСОБ 1: Flashscore (Selenium) — живые результаты
   ─────────────────────────────────────────────────
   Установи:  pip install selenium webdriver-manager
   Запуск:    python -m data.scraper_flashscore --mode selenium --days 7
   Что даёт:  результаты матчей за последние N дней
   Объём:     ~50-200 матчей/день (все лиги)
   Плюсы:     самые свежие данные, все турниры
   Минусы:    нужен Chrome, медленнее API

📌 СПОСОБ 2: Kaggle Setka Cup — большой датасет сразу
   ─────────────────────────────────────────────────
   Скачай:    https://www.kaggle.com/datasets/medaxone/one-month-table-tennis-dataset
   Запуск:    python -m data.scraper_flashscore --mode setka --file setka_data.csv
   Что даёт:  ~7,851 матчей украинской лиги (сентябрь 2022)
   Плюсы:     много данных сразу, отличные для тренировки ELO
   Минусы:    только одна лига, один месяц

📌 СПОСОБ 3: ITTF API — официальные данные
   ─────────────────────────────────────────────────
   Запуск:    python -m data.scraper --source ittf --tournament-id 12345
   Что даёт:  результаты конкретного турнира
   Документация: https://arcnovus.github.io/ittf-api/
   Плюсы:     официальные данные, JSON формат
   Минусы:    API может быть ограничен (CORS)

📌 СПОСОБ 4: Ручной CSV импорт
   ─────────────────────────────────────────────────
   Формат:    date,player1,player2,winner,score,tournament,level,country1,country2
   Запуск:    python -m data.scraper --source csv --file my_data.csv
   Плюсы:     полный контроль, можно собирать вручную
   Минусы:    медленно

📌 СПОСОБ 5: SportRadar API (платный) — профессиональный
   ─────────────────────────────────────────────────
   URL:       https://marketplace.sportradar.com/products/653154816a6635c3544c0750
   Что даёт:  live данные, рейтинги top-500, H2H, win probability
   Плюсы:     самый полный источник, стабильный
   Минусы:    платный (~$50/мес для минимального плана)

🎯 РЕКОМЕНДУЕМЫЙ ПЛАН:
   1. Начни с Setka Cup (7,851 матч — сразу обучаешь модель)
   2. Добавь наши 192 WTT матча (топ-игроки)
   3. Подключи Flashscore Selenium (ежедневное обновление)
   4. Когда проект взлетит — подключи SportRadar
        """)
