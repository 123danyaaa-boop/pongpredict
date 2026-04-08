"""
PongPredict — Движок предсказаний для бота

Загружает ELO рейтинги и модель, выдаёт предсказания.
Работает без Selenium/скрейпинга — только из базы данных.
"""

import sys, os
import pickle
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.models import init_db, get_session, Player, Match
from elo.elo_calculator import EloCalculator


class PredictionEngine:
    """
    Движок предсказаний.

    Загружает ELO из базы и выдаёт:
      - вероятности победы для двух игроков
      - текстовое объяснение
      - H2H статистику
    """

    def __init__(self):
        init_db()
        self.db = get_session()
        self.elo = EloCalculator()
        self._load_elo()

    def _load_elo(self):
        """Пересчитать ELO по всей базе."""
        matches = self.db.query(Match).order_by(Match.date).all()
        for m in matches:
            wid = m.winner_id
            lid = m.player2_id if wid == m.player1_id else m.player1_id
            self.elo.update(wid, lid, m.tournament_level or 'regular', m.date)

    def find_player(self, query):
        """
        Найти игрока по части имени.
        Возвращает Player или None.
        """
        query = query.strip().lower()
        players = self.db.query(Player).all()

        # Точное совпадение
        for p in players:
            if p.name.lower() == query:
                return p

        # Частичное совпадение
        matches = [p for p in players if query in p.name.lower()]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            return matches  # Список для уточнения

        # По фамилии
        matches = [p for p in players if query in p.name.lower().split()[-1]]
        if len(matches) == 1:
            return matches[0]

        return None

    def predict(self, player1_id, player2_id):
        """
        Предсказание матча.

        Возвращает dict:
        {
            'p1': Player, 'p2': Player,
            'p1_prob': float, 'p2_prob': float,
            'p1_elo': float, 'p2_elo': float,
            'elo_diff': float,
            'h2h_total': int, 'h2h_p1_wins': int, 'h2h_p2_wins': int,
            'favorite': Player,
            'confidence': str,  # 'high' / 'medium' / 'low'
        }
        """
        p1 = self.db.get(Player, player1_id)
        p2 = self.db.get(Player, player2_id)

        elo1 = self.elo.get_rating(player1_id)
        elo2 = self.elo.get_rating(player2_id)

        prob1, prob2 = self.elo.predict(player1_id, player2_id)

        # H2H
        h2h = (
            self.db.query(Match)
            .filter(
                ((Match.player1_id == player1_id) & (Match.player2_id == player2_id)) |
                ((Match.player1_id == player2_id) & (Match.player2_id == player1_id))
            )
            .all()
        )
        h2h_p1 = sum(1 for m in h2h if m.winner_id == player1_id)
        h2h_p2 = sum(1 for m in h2h if m.winner_id == player2_id)

        # Последние 5 матчей
        last_5 = sorted(h2h, key=lambda m: m.date, reverse=True)[:5]

        # Confidence
        prob_max = max(prob1, prob2)
        if prob_max > 0.75:
            confidence = 'high'
        elif prob_max > 0.60:
            confidence = 'medium'
        else:
            confidence = 'low'

        favorite = p1 if prob1 > prob2 else p2

        return {
            'p1': p1, 'p2': p2,
            'p1_prob': prob1, 'p2_prob': prob2,
            'p1_elo': elo1, 'p2_elo': elo2,
            'elo_diff': abs(elo1 - elo2),
            'h2h_total': len(h2h),
            'h2h_p1_wins': h2h_p1,
            'h2h_p2_wins': h2h_p2,
            'h2h_last5': last_5,
            'favorite': favorite,
            'confidence': confidence,
        }

    def get_rankings(self, top_n=10):
        """Топ-N игроков по ELO."""
        top = self.elo.get_top_players(n=top_n, min_matches=3)
        result = []
        for pid, rating, mc in top:
            p = self.db.get(Player, pid)
            if p:
                wr = (p.total_wins / p.total_matches * 100) if p.total_matches > 0 else 0
                result.append({
                    'player': p,
                    'elo': round(rating),
                    'matches': mc,
                    'win_rate': round(wr),
                })
        return result

    def get_player_stats(self, player_id):
        """Полная статистика игрока."""
        p = self.db.get(Player, player_id)
        if not p:
            return None

        elo = self.elo.get_all_ratings(player_id)
        mc = self.elo.match_counts.get(player_id, 0)

        # Последние 10 матчей
        recent = (
            self.db.query(Match)
            .filter(
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(10)
            .all()
        )

        form = sum(1 for m in recent[:5] if m.winner_id == player_id)

        return {
            'player': p,
            'elo_overall': round(elo['overall']),
            'elo_major': round(elo['major']),
            'elo_league': round(elo['league']),
            'matches': mc,
            'wins': p.total_wins or 0,
            'win_rate': round((p.total_wins or 0) / max(mc, 1) * 100),
            'form_5': f"{form}/5",
            'recent': recent,
        }

    def get_all_players(self):
        """Список всех игроков."""
        return self.db.query(Player).order_by(Player.name).all()
