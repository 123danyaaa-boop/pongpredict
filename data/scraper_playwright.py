"""
PongPredict — Flashscore Playwright Scraper

Продакшен-скрейпер для сбора данных с Flashscore.
Использует Playwright (быстрее и стабильнее Selenium).

УСТАНОВКА (на твоём компьютере):
    pip install playwright
    python -m playwright install chromium

ЗАПУСК:
    python data/scraper_playwright.py                     # вчера
    python data/scraper_playwright.py --days 7            # неделя
    python data/scraper_playwright.py --days 30 --pages 8 # месяц
    python data/scraper_playwright.py --all-leagues       # включая нижние лиги

ВЫХОД:
    data/scraped_YYYY-MM-DD.csv  — CSV с матчами
    + автоматически сохраняется в SQLite базу
"""

import re
import csv
import sys
import os
import argparse
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Уровни турниров
LEVEL_MAP = {
    'olympic': 'grand_slam', 'world championships': 'grand_slam',
    'world cup': 'grand_slam',
    'champions': 'major', 'grand smash': 'major', 'finals': 'major',
    'star contender': 'contender', 'contender': 'contender',
    'feeder': 'regular', 'challenger': 'regular',
    'bundesliga': 'league', 'super league': 'league',
    'liga pro': 'league', 'setka': 'league',
    'tt-cup': 'league', 'win cup': 'league',
    'tt cup': 'league', 'tt star': 'league',
}


def classify_level(name):
    nl = name.lower()
    for keyword, level in LEVEL_MAP.items():
        if keyword in nl:
            return level
    return 'regular'


def scrape_flashscore(days_back=1, max_pages=5, include_leagues=False):
    """
    Скрейпит результаты настольного тенниса с Flashscore.

    Аргументы:
        days_back:       сколько дней назад собирать
        max_pages:       сколько раз нажать "показать ещё"
        include_leagues: включать нижние лиги (Setka, Liga Pro и т.д.)

    Возвращает:
        list of dict — матчи
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright не установлен!")
        print("   pip install playwright")
        print("   python -m playwright install chromium")
        return []

    matches = []
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    print(f"🏓 Flashscore Scraper — настольный теннис")
    print(f"   Период: последние {days_back} дней")
    print(f"   Страниц: {max_pages}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()

        print("  🌐 Загружаю flashscore.com/table-tennis/results/...")
        page.goto('https://www.flashscore.com/table-tennis/results/', timeout=30000)
        page.wait_for_timeout(3000)

        # Принять куки
        try:
            page.click('#onetrust-accept-btn-handler', timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Нажимаем "показать ещё"
        for i in range(max_pages):
            try:
                btn = page.query_selector('a.event__more--static')
                if btn:
                    btn.click()
                    page.wait_for_timeout(2000)
                    print(f"  📄 Загружена страница {i + 2}")
                else:
                    break
            except Exception:
                break

        # Парсим результаты
        print("  🔍 Парсинг результатов...")

        current_tournament = ""
        current_level = "regular"

        # Все строки на странице
        elements = page.query_selector_all(
            'div.event__header--table-tennis, '
            'div.event__match--table-tennis, '
            'div.event__header, '
            'div.event__match'
        )

        print(f"  📊 Найдено {len(elements)} элементов")

        for el in elements:
            try:
                classes = el.get_attribute('class') or ''

                # Заголовок турнира
                if 'header' in classes:
                    title = el.query_selector('.event__title--name')
                    if title:
                        current_tournament = title.inner_text().strip()
                        current_level = classify_level(current_tournament)
                    continue

                # Матч
                if 'match' in classes:
                    # Имена игроков
                    participants = el.query_selector_all('.event__participant')
                    if len(participants) < 2:
                        continue

                    p1_name = participants[0].inner_text().strip()
                    p2_name = participants[1].inner_text().strip()

                    if not p1_name or not p2_name:
                        continue

                    # Убираем "(serving)" и подобные пометки
                    p1_name = re.sub(r'\s*\(.*?\)\s*', '', p1_name).strip()
                    p2_name = re.sub(r'\s*\(.*?\)\s*', '', p2_name).strip()

                    # Счёт
                    scores = el.query_selector_all('.event__score--home, .event__score--away')
                    if len(scores) < 2:
                        # Альтернативный селектор
                        scores = el.query_selector_all('.event__score')

                    if len(scores) < 2:
                        continue

                    try:
                        s1 = int(scores[0].inner_text().strip())
                        s2 = int(scores[1].inner_text().strip())
                    except (ValueError, TypeError):
                        continue

                    if s1 == s2:
                        continue  # Не завершён

                    winner = p1_name if s1 > s2 else p2_name
                    score_str = f"{s1}-{s2}"

                    # Дата
                    match_date = date.today().isoformat()
                    time_el = el.query_selector('.event__time')
                    if time_el:
                        time_text = time_el.inner_text().strip()
                        dm = re.search(r'(\d{2})\.(\d{2})\.(\d{4})?', time_text)
                        if dm:
                            day = int(dm.group(1))
                            month = int(dm.group(2))
                            year = int(dm.group(3)) if dm.group(3) else date.today().year
                            match_date = f"{year}-{month:02d}-{day:02d}"
                        elif re.match(r'\d{2}:\d{2}$', time_text):
                            match_date = date.today().isoformat()

                    # Фильтр по дате
                    if match_date < cutoff:
                        continue

                    # Фильтр нижних лиг
                    if not include_leagues and current_level == 'league':
                        if any(skip in current_tournament.lower()
                               for skip in ['setka', 'liga pro', 'tt-cup', 'win cup']):
                            continue

                    # Детали сетов
                    set_scores = el.query_selector_all('.event__part--home, .event__part--away')
                    sets_detail = ""
                    if set_scores and len(set_scores) >= 2:
                        homes = [s.inner_text().strip() for s in set_scores[::2]]
                        aways = [s.inner_text().strip() for s in set_scores[1::2]]
                        pairs = [f"{h}-{a}" for h, a in zip(homes, aways) if h and a]
                        sets_detail = ",".join(pairs)

                    matches.append({
                        'date': match_date,
                        'player1': p1_name,
                        'player2': p2_name,
                        'winner': winner,
                        'score': score_str,
                        'sets_detail': sets_detail,
                        'tournament': current_tournament,
                        'level': current_level,
                        'country1': '',
                        'country2': '',
                    })

            except Exception as e:
                continue

        browser.close()

    print(f"\n  ✅ Спарсено: {len(matches)} матчей")

    # Статистика по турнирам
    tournaments = {}
    for m in matches:
        t = m['tournament']
        tournaments[t] = tournaments.get(t, 0) + 1

    if tournaments:
        print(f"\n  📋 Турниры:")
        for t, count in sorted(tournaments.items(), key=lambda x: -x[1])[:10]:
            level = classify_level(t)
            print(f"     [{level:>10s}] {t}: {count} матчей")

    return matches


def save_csv(matches, filepath):
    """Сохранить в CSV."""
    if not matches:
        return

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'date', 'player1', 'player2', 'winner', 'score',
            'sets_detail', 'tournament', 'level', 'country1', 'country2'
        ])
        writer.writeheader()
        writer.writerows(matches)

    print(f"  💾 CSV: {filepath}")


def save_to_db(matches):
    """Сохранить в базу данных PongPredict."""
    from data.models import init_db, get_session, Player, Match
    init_db()
    db = get_session()
    saved = 0

    for m in matches:
        try:
            p1 = db.query(Player).filter(Player.name == m['player1']).first()
            if not p1:
                p1 = Player(name=m['player1'], country=m.get('country1') or None)
                db.add(p1)
                db.flush()

            p2 = db.query(Player).filter(Player.name == m['player2']).first()
            if not p2:
                p2 = Player(name=m['player2'], country=m.get('country2') or None)
                db.add(p2)
                db.flush()

            winner = p1 if m['winner'] == m['player1'] else p2
            match_date = datetime.strptime(m['date'], '%Y-%m-%d').date()

            existing = db.query(Match).filter(
                Match.date == match_date,
                Match.player1_id == p1.id,
                Match.player2_id == p2.id,
            ).first()
            if existing:
                continue

            match = Match(
                date=match_date,
                tournament=m['tournament'],
                tournament_level=m['level'],
                player1_id=p1.id,
                player2_id=p2.id,
                winner_id=winner.id,
                score=m['score'],
                sets_detail=m.get('sets_detail', ''),
                source='flashscore_playwright',
            )
            db.add(match)
            p1.total_matches = (p1.total_matches or 0) + 1
            p2.total_matches = (p2.total_matches or 0) + 1
            winner.total_wins = (winner.total_wins or 0) + 1
            saved += 1

        except Exception:
            continue

    db.commit()
    db.close()
    print(f"  🗄️ В базу: {saved} новых матчей")
    return saved


# === CLI ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PongPredict Flashscore Playwright Scraper')
    parser.add_argument('--days', type=int, default=1, help='Дней назад')
    parser.add_argument('--pages', type=int, default=5, help='Страниц загрузить')
    parser.add_argument('--all-leagues', action='store_true', help='Включить нижние лиги')
    parser.add_argument('--no-db', action='store_true', help='Не сохранять в БД')
    args = parser.parse_args()

    matches = scrape_flashscore(
        days_back=args.days,
        max_pages=args.pages,
        include_leagues=args.all_leagues,
    )

    if matches:
        # CSV
        csv_path = f"data/scraped_{date.today().isoformat()}.csv"
        save_csv(matches, csv_path)

        # DB
        if not args.no_db:
            save_to_db(matches)

        print(f"\n🎉 Готово! {len(matches)} матчей собрано.")
    else:
        print("\n😐 Матчей не найдено. Попробуй --days 7 --pages 8")
