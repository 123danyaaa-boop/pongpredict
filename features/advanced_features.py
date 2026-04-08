"""
PongPredict — Продвинутые фичи (v2)

Новые фичи поверх базовых:
  - Momentum (EWMA) — экспоненциально-взвешенный моментум
  - Clutch factor — процент побед в решающих сетах (4-3)
  - ELO decay — штраф за неактивность
  - Score dominance — средняя разница очков в сетах
  - Upset rate — как часто игрок побеждает фаворита
  - Tournament experience — сколько матчей на этом уровне

По исследованиям (Wang et al. 2025, Nature):
  Momentum через EWMA + XGBoost даёт до 84% accuracy в теннисе.
"""

import numpy as np
import pandas as pd
from datetime import timedelta
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from data.models import Player, Match, get_session
from elo.elo_calculator import EloCalculator


def compute_ewma_momentum(results, span=5):
    """
    Экспоненциально-взвешенное скользящее среднее (EWMA) по результатам.
    Недавние матчи весят больше, чем старые.

    Аргументы:
        results: список из 1 (победа) и 0 (поражение), хронологический
        span:    окно EWMA (чем меньше, тем быстрее реагирует)

    Возвращает:
        float от 0.0 до 1.0 — текущий моментум
    """
    if not results:
        return 0.5
    series = pd.Series(results)
    ewma = series.ewm(span=span, adjust=False).mean()
    return float(ewma.iloc[-1])


class AdvancedFeatureBuilder:
    """
    Генератор продвинутых фичей v2.

    Добавляет к базовым фичам:
      - ewma_momentum_diff:     разница EWMA моментума
      - clutch_diff:            разница clutch factor (победы 4-3)
      - dominance_diff:         разница средней доминации по сетам
      - upset_rate_diff:        разница upset rate
      - elo_with_decay:         ELO со штрафом за неактивность
      - tournament_exp_diff:    разница опыта на уровне турнира
      - comeback_rate_diff:     как часто игрок отыгрывается
    """

    def __init__(self):
        self.db = get_session()
        self.elo = EloCalculator()

    def _get_player_results(self, player_id, before_date, n=20):
        """Получить последние N результатов (1=win, 0=loss) в хронологическом порядке."""
        matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.asc())
            .all()
        )
        results = [1 if m.winner_id == player_id else 0 for m in matches[-n:]]
        return results

    def _get_clutch_factor(self, player_id, before_date):
        """
        Clutch factor — win% в матчах, дошедших до решающего сета (4-3).
        Показывает психологическую устойчивость.
        """
        matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id),
                Match.score.in_(['4-3', '3-4'])
            )
            .all()
        )
        if len(matches) < 2:
            return 0.5  # Недостаточно данных
        wins = sum(1 for m in matches if m.winner_id == player_id)
        return wins / len(matches)

    def _get_dominance_score(self, player_id, before_date, n=10):
        """
        Средняя разница сетов (sets won - sets lost) за последние N матчей.
        Показывает насколько убедительно игрок побеждает/проигрывает.
        Пример: побеждает 4-1 в среднем → dominance = +3
        """
        matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(n)
            .all()
        )
        if not matches:
            return 0.0

        total_diff = 0
        for m in matches:
            if not m.score or '-' not in m.score:
                continue
            try:
                parts = m.score.split('-')
                s1, s2 = int(parts[0]), int(parts[1])
                if m.player1_id == player_id:
                    total_diff += (s1 - s2)
                else:
                    total_diff += (s2 - s1)
            except (ValueError, IndexError):
                continue

        return total_diff / len(matches)

    def _get_upset_rate(self, player_id, before_date, n=20):
        """
        Upset rate — как часто игрок побеждает соперника с более высоким ELO.
        Высокий upset rate = опасный underdog.
        """
        matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(n)
            .all()
        )

        upsets = 0
        upset_opportunities = 0

        for m in matches:
            if not m.p1_elo_before or not m.p2_elo_before:
                continue

            is_p1 = (m.player1_id == player_id)
            my_elo = m.p1_elo_before if is_p1 else m.p2_elo_before
            opp_elo = m.p2_elo_before if is_p1 else m.p1_elo_before

            if my_elo < opp_elo:  # Я аутсайдер
                upset_opportunities += 1
                if m.winner_id == player_id:
                    upsets += 1

        if upset_opportunities < 2:
            return 0.5
        return upsets / upset_opportunities

    def _get_tournament_experience(self, player_id, tournament_level, before_date):
        """Кол-во матчей игрока на данном уровне турнира."""
        count = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                Match.tournament_level == tournament_level,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .count()
        )
        return count

    def _get_comeback_rate(self, player_id, before_date, n=20):
        """
        Comeback rate — как часто игрок выигрывает, проигрывая по сетам.
        Считаем долю матчей с победой в решающем сете.
        """
        matches = (
            self.db.query(Match)
            .filter(
                Match.date < before_date,
                Match.winner_id == player_id,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .limit(n)
            .all()
        )
        if len(matches) < 3:
            return 0.5

        comebacks = 0
        for m in matches:
            if m.score in ['4-3', '3-4']:
                comebacks += 1

        return comebacks / len(matches)

    def _apply_elo_decay(self, player_id, match_date, base_elo, decay_rate=0.995, max_days=90):
        """
        ELO со штрафом за неактивность.
        Если игрок не играл > max_days, его ELO постепенно сдвигается к 1500.
        """
        last_match = (
            self.db.query(Match)
            .filter(
                Match.date < match_date,
                (Match.player1_id == player_id) | (Match.player2_id == player_id)
            )
            .order_by(Match.date.desc())
            .first()
        )

        if not last_match:
            return base_elo

        days_inactive = (match_date - last_match.date).days
        if days_inactive <= max_days:
            return base_elo

        # Постепенно двигаем к 1500
        excess_days = days_inactive - max_days
        decay_factor = decay_rate ** excess_days
        return 1500 + (base_elo - 1500) * decay_factor

    def build_advanced_dataset(self):
        """
        Построить датасет с продвинутыми фичами.
        Включает все базовые + новые momentum/clutch/dominance фичи.
        """
        matches = self.db.query(Match).order_by(Match.date).all()
        if not matches:
            print("❌ Нет матчей!")
            return pd.DataFrame()

        print(f"🧠 Генерация продвинутых фичей для {len(matches)} матчей...")

        # Прогоняем ELO с сохранением данных до каждого матча
        elo_snapshots = []
        for m in matches:
            snap = {
                'p1_elo': self.elo.get_rating(m.player1_id),
                'p2_elo': self.elo.get_rating(m.player2_id),
                'p1_elo_major': self.elo.get_rating(m.player1_id, 'major'),
                'p2_elo_major': self.elo.get_rating(m.player2_id, 'major'),
            }
            elo_snapshots.append(snap)

            wid = m.winner_id
            lid = m.player2_id if wid == m.player1_id else m.player1_id
            self.elo.update(wid, lid, m.tournament_level or 'regular', m.date)

        rows = []
        for i, m in enumerate(matches):
            p1, p2 = m.player1_id, m.player2_id
            snap = elo_snapshots[i]

            # === БАЗОВЫЕ ФИЧИ ===
            elo_diff = snap['p1_elo'] - snap['p2_elo']
            elo_major_diff = snap['p1_elo_major'] - snap['p2_elo_major']

            # === MOMENTUM (EWMA) ===
            res1 = self._get_player_results(p1, m.date, n=20)
            res2 = self._get_player_results(p2, m.date, n=20)
            momentum1 = compute_ewma_momentum(res1, span=5)
            momentum2 = compute_ewma_momentum(res2, span=5)
            momentum1_long = compute_ewma_momentum(res1, span=10)
            momentum2_long = compute_ewma_momentum(res2, span=10)

            # === CLUTCH ===
            clutch1 = self._get_clutch_factor(p1, m.date)
            clutch2 = self._get_clutch_factor(p2, m.date)

            # === DOMINANCE ===
            dom1 = self._get_dominance_score(p1, m.date)
            dom2 = self._get_dominance_score(p2, m.date)

            # === UPSET RATE ===
            upset1 = self._get_upset_rate(p1, m.date)
            upset2 = self._get_upset_rate(p2, m.date)

            # === ELO WITH DECAY ===
            elo_decay1 = self._apply_elo_decay(p1, m.date, snap['p1_elo'])
            elo_decay2 = self._apply_elo_decay(p2, m.date, snap['p2_elo'])

            # === TOURNAMENT EXPERIENCE ===
            exp1 = self._get_tournament_experience(p1, m.tournament_level, m.date)
            exp2 = self._get_tournament_experience(p2, m.tournament_level, m.date)

            # === COMEBACK RATE ===
            comeback1 = self._get_comeback_rate(p1, m.date)
            comeback2 = self._get_comeback_rate(p2, m.date)

            # === FORM (простые) ===
            form5_1 = sum(res1[-5:]) / max(len(res1[-5:]), 1) if res1 else 0.5
            form5_2 = sum(res2[-5:]) / max(len(res2[-5:]), 1) if res2 else 0.5
            form10_1 = sum(res1[-10:]) / max(len(res1[-10:]), 1) if res1 else 0.5
            form10_2 = sum(res2[-10:]) / max(len(res2[-10:]), 1) if res2 else 0.5

            # === H2H ===
            h2h = (
                self.db.query(Match)
                .filter(
                    Match.date < m.date,
                    ((Match.player1_id == p1) & (Match.player2_id == p2)) |
                    ((Match.player1_id == p2) & (Match.player2_id == p1))
                )
                .all()
            )
            h2h_total = len(h2h)
            h2h_wr = sum(1 for x in h2h if x.winner_id == p1) / max(h2h_total, 1) if h2h_total > 0 else 0.5

            # === LEVEL ===
            level_map = {'grand_slam': 4, 'major': 3, 'contender': 2, 'regular': 1, 'league': 1}
            t_level = level_map.get(m.tournament_level, 1)

            # === TARGET ===
            p1_wins = 1 if m.winner_id == p1 else 0

            rows.append({
                'match_id': m.id, 'date': m.date,
                # ELO
                'elo_diff': elo_diff,
                'elo_major_diff': elo_major_diff,
                'elo_decay_diff': elo_decay1 - elo_decay2,
                # Momentum (EWMA)
                'momentum_short_diff': momentum1 - momentum2,
                'momentum_long_diff': momentum1_long - momentum2_long,
                # Form
                'form_5_diff': form5_1 - form5_2,
                'form_10_diff': form10_1 - form10_2,
                # Clutch & Mental
                'clutch_diff': clutch1 - clutch2,
                'comeback_diff': comeback1 - comeback2,
                'upset_rate_diff': upset1 - upset2,
                # Dominance
                'dominance_diff': dom1 - dom2,
                # H2H
                'h2h_total': h2h_total,
                'h2h_p1_winrate': h2h_wr,
                # Experience
                'tournament_exp_diff': exp1 - exp2,
                'tournament_level': t_level,
                # Target
                'p1_wins': p1_wins,
            })

            if (i + 1) % 50 == 0:
                print(f"  ... {i + 1}/{len(matches)}")

        df = pd.DataFrame(rows)
        print(f"✅ Продвинутый датасет: {len(df)} строк, {len(df.columns)} колонок")
        return df


if __name__ == '__main__':
    fb = AdvancedFeatureBuilder()
    df = fb.build_advanced_dataset()
    if not df.empty:
        feature_cols = [c for c in df.columns if c not in ['match_id', 'date', 'p1_wins']]
        corr = df[feature_cols + ['p1_wins']].corr()['p1_wins'].drop('p1_wins')
        corr = corr.dropna().sort_values(key=abs, ascending=False)
        print(f"\n📊 Корреляции с target:")
        for feat, val in corr.items():
            bar = "█" * int(abs(val) * 30)
            print(f"  {feat:<25s} {'+' if val > 0 else '-'}{abs(val):.3f}  {bar}")
