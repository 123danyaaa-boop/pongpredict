"""
PongPredict — ELO Рейтинговый Движок

Система ELO адаптирована из шахмат для настольного тенниса.
Ключевые особенности:
  - Адаптивный K-фактор (больше для новичков, меньше для топов)
  - Множитель за уровень турнира (ЧМ важнее лиги)
  - Три отдельных ELO: overall, major, league

Формула:
  E(A) = 1 / (1 + 10^((R_B - R_A) / 400))
  R_new = R_old + K * mult * (S - E(A))
"""

import yaml
import os

# === Загружаем конфиг ===
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)['elo']


class EloCalculator:
    """
    Считает и обновляет ELO рейтинги игроков.

    Пример использования:
        elo = EloCalculator()
        elo.update(winner_id=1, loser_id=2, tournament_level="major")
        print(elo.get_rating(1))  # → 1520.0
    """

    def __init__(self):
        # {player_id: {'overall': 1500, 'major': 1500, 'league': 1500}}
        self.ratings = {}

        # {player_id: количество_матчей} — для адаптивного K-фактора
        self.match_counts = {}

        # Параметры из конфига
        self.initial = config['initial_rating']
        self.k_new = config['k_factor_new']
        self.k_default = config['k_factor_default']
        self.k_top = config['k_factor_top']
        self.multipliers = config['tournament_multiplier']

        # Лог всех изменений (для графиков и отладки)
        self.history = []  # список dict: {player_id, date, elo_before, elo_after, ...}

    def _ensure_player(self, player_id):
        """Создать запись для игрока, если её ещё нет"""
        if player_id not in self.ratings:
            self.ratings[player_id] = {
                'overall': self.initial,
                'major': self.initial,
                'league': self.initial,
            }
            self.match_counts[player_id] = 0

    def get_rating(self, player_id, rating_type='overall'):
        """
        Получить текущий ELO игрока.

        Аргументы:
            player_id:    ID игрока
            rating_type:  'overall', 'major' или 'league'

        Возвращает:
            float — текущий ELO рейтинг
        """
        self._ensure_player(player_id)
        return self.ratings[player_id][rating_type]

    def get_all_ratings(self, player_id):
        """Получить все три ELO рейтинга игрока"""
        self._ensure_player(player_id)
        return self.ratings[player_id].copy()

    def _get_k_factor(self, player_id):
        """
        Адаптивный K-фактор:
          - < 30 матчей  → K=32 (рейтинг быстро двигается)
          - ELO > 2000   → K=16 (стабильный топ-рейтинг)
          - Иначе        → K=24 (обычный)
        """
        matches = self.match_counts.get(player_id, 0)
        if matches < 30:
            return self.k_new
        elif self.ratings[player_id]['overall'] > 2000:
            return self.k_top
        return self.k_default

    @staticmethod
    def expected_score(elo_a, elo_b):
        """
        Ожидаемый результат игрока A против B.
        E(A) = 1 / (1 + 10^((R_B - R_A) / 400))

        Возвращает:
            float от 0.0 до 1.0
        """
        return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400))

    def _get_tournament_multiplier(self, tournament_level):
        """Множитель за уровень турнира (ЧМ > обычный турнир)"""
        return self.multipliers.get(tournament_level, 1.0)

    def _determine_rating_type(self, tournament_level):
        """
        Определяем, какой тип ELO обновлять:
          - grand_slam, major → 'major'
          - league             → 'league'
          - всё               → 'overall' (обновляется ВСЕГДА)
        """
        if tournament_level in ('grand_slam', 'major'):
            return 'major'
        elif tournament_level == 'league':
            return 'league'
        return None  # только overall

    def update(self, winner_id, loser_id, tournament_level='regular', match_date=None):
        """
        Обновить ELO после матча.

        Аргументы:
            winner_id:        ID победителя
            loser_id:         ID проигравшего
            tournament_level: 'grand_slam' / 'major' / 'contender' / 'regular' / 'league'
            match_date:       дата матча (для логирования)

        Возвращает:
            dict с информацией об изменениях:
            {
                'winner_elo_before': float,
                'winner_elo_after': float,
                'loser_elo_before': float,
                'loser_elo_after': float,
                'winner_change': float,
                'loser_change': float,
            }
        """
        self._ensure_player(winner_id)
        self._ensure_player(loser_id)

        mult = self._get_tournament_multiplier(tournament_level)
        secondary_type = self._determine_rating_type(tournament_level)

        result = {}

        # === Обновляем OVERALL ELO (всегда) ===
        elo_w = self.ratings[winner_id]['overall']
        elo_l = self.ratings[loser_id]['overall']

        expected_w = self.expected_score(elo_w, elo_l)
        expected_l = 1.0 - expected_w

        k_w = self._get_k_factor(winner_id) * mult
        k_l = self._get_k_factor(loser_id) * mult

        new_elo_w = elo_w + k_w * (1.0 - expected_w)
        new_elo_l = elo_l + k_l * (0.0 - expected_l)

        result['winner_elo_before'] = elo_w
        result['winner_elo_after'] = new_elo_w
        result['loser_elo_before'] = elo_l
        result['loser_elo_after'] = new_elo_l
        result['winner_change'] = new_elo_w - elo_w
        result['loser_change'] = new_elo_l - elo_l

        self.ratings[winner_id]['overall'] = new_elo_w
        self.ratings[loser_id]['overall'] = new_elo_l

        # === Обновляем SECONDARY ELO (major или league) ===
        if secondary_type:
            elo_w2 = self.ratings[winner_id][secondary_type]
            elo_l2 = self.ratings[loser_id][secondary_type]

            expected_w2 = self.expected_score(elo_w2, elo_l2)
            expected_l2 = 1.0 - expected_w2

            self.ratings[winner_id][secondary_type] = elo_w2 + k_w * (1.0 - expected_w2)
            self.ratings[loser_id][secondary_type] = elo_l2 + k_l * (0.0 - expected_l2)

        # === Обновляем счётчики матчей ===
        self.match_counts[winner_id] = self.match_counts.get(winner_id, 0) + 1
        self.match_counts[loser_id] = self.match_counts.get(loser_id, 0) + 1

        # === Логируем историю ===
        self.history.append({
            'winner_id': winner_id,
            'loser_id': loser_id,
            'date': match_date,
            'tournament_level': tournament_level,
            'winner_elo_before': elo_w,
            'winner_elo_after': new_elo_w,
            'loser_elo_before': elo_l,
            'loser_elo_after': new_elo_l,
        })

        return result

    def predict(self, player1_id, player2_id, rating_type='overall'):
        """
        Предсказать вероятность победы каждого игрока.

        Возвращает:
            (p1_prob, p2_prob) — вероятности от 0.0 до 1.0
        """
        self._ensure_player(player1_id)
        self._ensure_player(player2_id)

        elo1 = self.ratings[player1_id][rating_type]
        elo2 = self.ratings[player2_id][rating_type]

        p1 = self.expected_score(elo1, elo2)
        p2 = 1.0 - p1

        return p1, p2

    def get_top_players(self, n=20, rating_type='overall', min_matches=10):
        """
        Получить топ-N игроков по ELO.

        Аргументы:
            n:            количество игроков
            rating_type:  'overall', 'major' или 'league'
            min_matches:  минимум матчей для попадания в рейтинг

        Возвращает:
            list of (player_id, elo, match_count)
        """
        eligible = [
            (pid, self.ratings[pid][rating_type], self.match_counts[pid])
            for pid in self.ratings
            if self.match_counts.get(pid, 0) >= min_matches
        ]
        eligible.sort(key=lambda x: x[1], reverse=True)
        return eligible[:n]

    def backfill(self, matches_chronological):
        """
        Пересчитать ELO по всей истории матчей.
        Матчи ДОЛЖНЫ быть отсортированы по дате!

        Аргументы:
            matches_chronological: список dict с ключами:
                - winner_id
                - loser_id
                - tournament_level
                - date (опционально)

        Возвращает:
            dict со статистикой: кол-во обработанных матчей, accuracy baseline и т.д.
        """
        # Сброс всех рейтингов
        self.ratings = {}
        self.match_counts = {}
        self.history = []

        correct_predictions = 0
        total_matches = 0

        for match in matches_chronological:
            winner_id = match['winner_id']
            loser_id = match['loser_id']
            level = match.get('tournament_level', 'regular')
            match_date = match.get('date', None)

            # Предсказание ДО обновления — проверяем baseline accuracy
            p1_prob, p2_prob = self.predict(winner_id, loser_id)
            if p1_prob >= 0.5:
                # Модель предсказала победу player1 (winner)
                correct_predictions += 1

            # Обновляем ELO
            self.update(winner_id, loser_id, level, match_date)
            total_matches += 1

        accuracy = correct_predictions / total_matches if total_matches > 0 else 0

        stats = {
            'total_matches': total_matches,
            'correct_predictions': correct_predictions,
            'baseline_accuracy': accuracy,
            'unique_players': len(self.ratings),
        }

        print(f"✅ Backfill завершён!")
        print(f"   Матчей обработано: {total_matches}")
        print(f"   Уникальных игроков: {len(self.ratings)}")
        print(f"   Baseline accuracy (ELO only): {accuracy:.1%}")

        return stats


# === Демо при запуске ===
if __name__ == '__main__':
    elo = EloCalculator()

    # Симулируем несколько матчей
    print("=== Демо ELO Калькулятора ===\n")

    # Fan Zhendong (id=1) vs Ma Long (id=2)
    result = elo.update(winner_id=1, loser_id=2, tournament_level='major')
    print(f"Матч 1: Player 1 побеждает Player 2 (major)")
    print(f"  P1: {result['winner_elo_before']:.0f} → {result['winner_elo_after']:.0f} "
          f"(+{result['winner_change']:.1f})")
    print(f"  P2: {result['loser_elo_before']:.0f} → {result['loser_elo_after']:.0f} "
          f"({result['loser_change']:.1f})")

    # Ещё матч: Player 2 побеждает Player 3
    result = elo.update(winner_id=2, loser_id=3, tournament_level='regular')
    print(f"\nМатч 2: Player 2 побеждает Player 3 (regular)")
    print(f"  P2: {result['winner_elo_before']:.0f} → {result['winner_elo_after']:.0f}")
    print(f"  P3: {result['loser_elo_before']:.0f} → {result['loser_elo_after']:.0f}")

    # Предсказание
    p1, p2 = elo.predict(1, 3)
    print(f"\nПредсказание P1 vs P3: {p1:.1%} / {p2:.1%}")

    # Топ игроки
    print(f"\nВсе рейтинги:")
    for pid in [1, 2, 3]:
        ratings = elo.get_all_ratings(pid)
        matches = elo.match_counts[pid]
        print(f"  Player {pid}: overall={ratings['overall']:.0f}, "
              f"major={ratings['major']:.0f}, matches={matches}")
