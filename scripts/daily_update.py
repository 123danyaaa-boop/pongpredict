"""
PongPredict — Ежедневное обновление

Скрипт для автоматического:
  1. Сбора новых матчей (Flashscore)
  2. Пересчёта ELO рейтингов
  3. Переобучения модели
  4. Генерации предсказаний на ближайшие матчи

Запуск вручную:
    python scripts/daily_update.py

Автоматический запуск (cron):
    # Каждый день в 6:00 утра
    0 6 * * * cd /path/to/pongpredict && python scripts/daily_update.py >> logs/daily.log 2>&1

GitHub Actions:
    Используй .github/workflows/daily.yml (создадим отдельно)
"""

import sys
import os
import json
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.models import init_db, get_session, Player, Match, Prediction
from data.scraper import CSVImporter
from elo.elo_calculator import EloCalculator


def step_scrape():
    """Попробовать собрать новые данные."""
    print("=" * 50)
    print("1️⃣  Сбор новых данных")
    print("=" * 50)

    new_matches = 0

    # Попытка Flashscore (если Selenium доступен)
    try:
        from data.scraper_flashscore import FlashscoreScraper
        scraper = FlashscoreScraper(headless=True)
        matches = scraper.scrape_results(days_back=1, load_pages=2)
        new_matches += scraper.save_to_db(matches)
        scraper.close()
    except ImportError:
        print("  ℹ️ Selenium не доступен — пропускаем Flashscore")
    except Exception as e:
        print(f"  ⚠️ Flashscore ошибка: {e}")

    print(f"  📊 Новых матчей: {new_matches}")
    return new_matches


def step_recalculate_elo():
    """Пересчитать ELO по всей базе."""
    print("\n" + "=" * 50)
    print("2️⃣  Пересчёт ELO")
    print("=" * 50)

    db = get_session()
    matches = db.query(Match).order_by(Match.date).all()

    if not matches:
        print("  ❌ Нет матчей")
        return None

    elo = EloCalculator()
    match_dicts = []
    for m in matches:
        wid = m.winner_id
        lid = m.player2_id if wid == m.player1_id else m.player1_id
        match_dicts.append({
            'winner_id': wid,
            'loser_id': lid,
            'tournament_level': m.tournament_level or 'regular',
            'date': m.date,
        })

    stats = elo.backfill(match_dicts)

    # Обновляем ELO в базе
    for pid, ratings in elo.ratings.items():
        player = db.get(Player, pid)
        if player:
            player.elo_overall = ratings['overall']
            player.elo_major = ratings['major']
            player.elo_league = ratings['league']

    db.commit()
    db.close()
    return elo


def step_generate_report(elo):
    """Генерация краткого отчёта."""
    print("\n" + "=" * 50)
    print("3️⃣  Отчёт")
    print("=" * 50)

    db = get_session()
    total_matches = db.query(Match).count()
    total_players = db.query(Player).count()
    today_matches = db.query(Match).filter(Match.date == date.today()).count()

    print(f"  📊 Всего матчей: {total_matches}")
    print(f"  👥 Всего игроков: {total_players}")
    print(f"  🆕 Матчей сегодня: {today_matches}")

    if elo:
        top5 = elo.get_top_players(n=5, min_matches=5)
        print(f"\n  🏆 Топ-5 ELO:")
        for i, (pid, rating, mc) in enumerate(top5, 1):
            p = db.get(Player, pid)
            print(f"    {i}. {p.name if p else '?':<25s} {rating:.0f}")

    db.close()

    report = {
        'date': date.today().isoformat(),
        'total_matches': total_matches,
        'total_players': total_players,
        'today_matches': today_matches,
    }

    # Сохраняем отчёт
    os.makedirs('logs', exist_ok=True)
    report_path = f"logs/report_{date.today().isoformat()}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n  💾 Отчёт: {report_path}")


def main():
    print(f"""
╔══════════════════════════════════════╗
║  🏓 PongPredict — Daily Update      ║
║  {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<36s} ║
╚══════════════════════════════════════╝
    """)

    init_db()
    step_scrape()
    elo = step_recalculate_elo()
    step_generate_report(elo)

    print("\n✅ Обновление завершено!")


if __name__ == '__main__':
    main()
