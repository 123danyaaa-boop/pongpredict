"""
PongPredict — Feature Engineering

Превращаем сырые данные матчей в фичи для ML модели.
Каждый матч → вектор из ~16 фичей.

Главные фичи (по исследованиям):
  1. elo_diff          — разница ELO (самый важный!)
  2. rank_diff_log     — нелинейная разница рейтингов
  3. form_5 / form_10  — форма за последние N матчей
  4. h2h_winrate       — история личных встреч
"""

import pandas as pd
import numpy as np
from datetime import timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.models import Player, Match, get_session
from elo.elo_calculator import EloCalculator


class FeatureBuilder:
    """
    Генератор фичей для каждого матча.

    Использование:
        fb = FeatureBuilder()
        df = fb.build_dataset()
        # df — DataFrame с фичами + target column 'p1_wins'
    """

    def __init__(self):
        self.elo = EloCalculator()
        self.db = get_session()

    def _get_recent_form(self, player_id, before_date, n_matches=5):
        """
        Win% игрока за последние N матчей до указанной даты.
        Возвращает float от 0.0 до 1.0, или 0.5 если мало данных.
        """
        recent = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(n_matches)
            .all()
        )

        if len(recent) < 3:
            return 0.5  # Недостаточно данных — нейтральное значение

        wins = sum(1 for m in recent if m.winner_id == player_id)
        return wins / len(recent)

    def _get_h2h(self, player1_id, player2_id, before_date):
        """
        Статистика личных встреч player1 vs player2 до указанной даты.
        Возвращает (total_matches, p1_winrate).
        """
        h2h_matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (
                    (Match.player1_id == player1_id) & (Match.player2_id == player2_id)
                ) | (
                    (Match.player1_id == player2_id) & (Match.player2_id == player1_id)
                )
            )
            .all()
        )

        total = len(h2h_matches)
        if total == 0:
            return 0, 0.5  # Нет встреч — нейтральное значение

        p1_wins = sum(1 for m in h2h_matches if m.winner_id == player1_id)
        return total, p1_wins / total

    def _get_streak(self, player_id, before_date):
        """
        Текущая серия побед (+) или поражений (-) игрока.
        Например: +5 = выиграл 5 последних матчей.
        """
        recent = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(20)
            .all()
        )

        if not recent:
            return 0

        streak = 0
        first_result = recent[0].winner_id == player_id  # True = победа

        for m in recent:
            won = (m.winner_id == player_id)
            if won == first_result:
                streak += 1
            else:
                break

        return streak if first_result else -streak

    def _get_days_since_last_match(self, player_id, match_date):
        """Дней с последнего матча (показатель усталости/простоя)."""
        last = (
            self.db.query(Match)
            .filter(
                Match.date < match_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .first()
        )

        if not last:
            return 30  # Нет данных — ставим 30 дней по умолчанию

        delta = (match_date - last.date).days
        return delta

    def build_dataset(self):
        """
        Построить полный датасет фичей из всех матчей в БД.

        Возвращает:
            pd.DataFrame с колонками:
                - match_id, date
                - elo_diff, elo_major_diff, elo_league_diff
                - rank_diff, rank_diff_log
                - form_5_diff, form_10_diff, form_20_diff
                - h2h_total, h2h_p1_winrate
                - streak_diff
                - days_rest_diff
                - tournament_level (encoded)
                - p1_wins (target: 1 если player1 выиграл, 0 иначе)
        """
        # Получаем все матчи отсортированные по дате
        matches = (
            self.db.query(Match)
            .order_by(Match.date)
            .all()
        )

        if not matches:
            print("❌ В базе нет матчей! Сначала импортируй данные.")
            return pd.DataFrame()

        print(f"📊 Генерация фичей для {len(matches)} матчей...")

        # Сначала прогоняем ELO по всей истории
        elo_data = []
        for m in matches:
            # Сохраняем ELO ДО матча
            elo_before_p1 = self.elo.get_rating(m.player1_id)
            elo_before_p2 = self.elo.get_rating(m.player2_id)
            elo_major_p1 = self.elo.get_rating(m.player1_id, 'major')
            elo_major_p2 = self.elo.get_rating(m.player2_id, 'major')
            elo_league_p1 = self.elo.get_rating(m.player1_id, 'league')
            elo_league_p2 = self.elo.get_rating(m.player2_id, 'league')

            elo_data.append({
                'p1_elo': elo_before_p1,
                'p2_elo': elo_before_p2,
                'p1_elo_major': elo_major_p1,
                'p2_elo_major': elo_major_p2,
                'p1_elo_league': elo_league_p1,
                'p2_elo_league': elo_league_p2,
            })

            # Обновляем ELO
            winner_id = m.winner_id
            loser_id = m.player2_id if winner_id == m.player1_id else m.player1_id
            level = m.tournament_level or 'regular'
            self.elo.update(winner_id, loser_id, level, m.date)

        # Теперь строим фичи для каждого матча
        rows = []
        for i, m in enumerate(matches):
            p1_id = m.player1_id
            p2_id = m.player2_id

            # --- ELO фичи (из предрасчёта) ---
            elo = elo_data[i]
            elo_diff = elo['p1_elo'] - elo['p2_elo']
            elo_major_diff = elo['p1_elo_major'] - elo['p2_elo_major']
            elo_league_diff = elo['p1_elo_league'] - elo['p2_elo_league']

            # --- Рейтинг ITTF ---
            p1_obj = self.db.query(Player).get(p1_id)
            p2_obj = self.db.query(Player).get(p2_id)
            rank1 = p1_obj.ittf_ranking or 500
            rank2 = p2_obj.ittf_ranking or 500
            rank_diff = rank2 - rank1  # Положительное = P1 выше в рейтинге
            rank_diff_log = np.log(rank2 + 1) - np.log(rank1 + 1)

            # --- Форма ---
            form5_p1 = self._get_recent_form(p1_id, m.date, 5)
            form5_p2 = self._get_recent_form(p2_id, m.date, 5)
            form10_p1 = self._get_recent_form(p1_id, m.date, 10)
            form10_p2 = self._get_recent_form(p2_id, m.date, 10)
            form20_p1 = self._get_recent_form(p1_id, m.date, 20)
            form20_p2 = self._get_recent_form(p2_id, m.date, 20)

            # --- H2H ---
            h2h_total, h2h_p1_wr = self._get_h2h(p1_id, p2_id, m.date)

            # --- Серии ---
            streak1 = self._get_streak(p1_id, m.date)
            streak2 = self._get_streak(p2_id, m.date)

            # --- Дни отдыха ---
            rest1 = self._get_days_since_last_match(p1_id, m.date)
            rest2 = self._get_days_since_last_match(p2_id, m.date)

            # --- Уровень турнира (числовой) ---
            level_map = {
                'grand_slam': 4,
                'major': 3,
                'contender': 2,
                'regular': 1,
                'league': 1,
            }
            tournament_lvl = level_map.get(m.tournament_level, 1)

            # --- Target ---
            p1_wins = 1 if m.winner_id == p1_id else 0

            rows.append({
                'match_id': m.id,
                'date': m.date,
                # ELO фичи
                'elo_diff': elo_diff,
                'elo_major_diff': elo_major_diff,
                'elo_league_diff': elo_league_diff,
                # Рейтинг фичи
                'rank_diff': rank_diff,
                'rank_diff_log': rank_diff_log,
                # Форма
                'form_5_diff': form5_p1 - form5_p2,
                'form_10_diff': form10_p1 - form10_p2,
                'form_20_diff': form20_p1 - form20_p2,
                # H2H
                'h2h_total': h2h_total,
                'h2h_p1_winrate': h2h_p1_wr,
                # Серии и отдых
                'streak_diff': streak1 - streak2,
                'days_rest_diff': rest1 - rest2,
                # Турнир
                'tournament_level': tournament_lvl,
                # Target
                'p1_wins': p1_wins,
            })

        df = pd.DataFrame(rows)
        print(f"✅ Датасет готов: {len(df)} строк, {len(df.columns)} колонок")
        print(f"   P1 win rate в датасете: {df['p1_wins'].mean():.1%}")
        return df


# === CLI ===
if __name__ == '__main__':
    fb = FeatureBuilder()
    df = fb.build_dataset()

    if not df.empty:
        print(f"\n📊 Превью датасета:")
        print(df.describe().round(2))
        print(f"\nКорреляции с target (p1_wins):")
        corr = df.drop(['match_id'], axis=1).corr()['p1_wins'].sort_values(ascending=False)
        print(corr.round(3))
