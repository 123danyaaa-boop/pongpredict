"""
PongPredict — Startup Script для деплоя

Инициализирует БД, загружает данные, пересчитывает ELO,
затем запускает Telegram бота.
"""

import os
import sys
import glob

sys.path.insert(0, os.path.dirname(__file__))

from data.models import init_db, get_session, Player, Match
from data.scraper import CSVImporter
from elo.elo_calculator import EloCalculator


def startup():
    print("🏓 PongPredict — Инициализация...\n")

    # 1. База данных
    init_db()

    db = get_session()
    existing = db.query(Match).count()
    db.close()

    if existing == 0:
        print("📥 Загрузка данных...")
        imp = CSVImporter()

        # Загружаем все CSV из data/
        csv_files = sorted(glob.glob('data/*.csv'))
        for csv_path in csv_files:
            print(f"   → {csv_path}")
            imp.import_file(csv_path)
    else:
        print(f"✅ В базе уже {existing} матчей")

    # 2. ELO
    print("\n📊 Пересчёт ELO...")
    db = get_session()
    matches = db.query(Match).order_by(Match.date).all()
    elo = EloCalculator()

    for m in matches:
        wid = m.winner_id
        lid = m.player2_id if wid == m.player1_id else m.player1_id
        elo.update(wid, lid, m.tournament_level or 'regular', m.date)

    for pid, ratings in elo.ratings.items():
        p = db.get(Player, pid)
        if p:
            p.elo_overall = ratings['overall']
            p.elo_major = ratings['major']
            p.elo_league = ratings['league']

    db.commit()
    db.close()

    top = elo.get_top_players(n=5, min_matches=3)
    print(f"   Игроков: {len(elo.ratings)}, Матчей: {len(matches)}")
    for i, (pid, r, mc) in enumerate(top, 1):
        db2 = get_session()
        p = db2.get(Player, pid)
        print(f"   {i}. {p.name if p else '?'}: {r:.0f}")
        db2.close()

    print("\n✅ Готово к запуску!\n")


if __name__ == '__main__':
    startup()

    # Запуск бота
    print("🤖 Запускаю Telegram бота...")
    from bot.telegram_bot import main
    main()
