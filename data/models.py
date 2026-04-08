"""
PongPredict — Модели базы данных (SQLAlchemy)

Три основные таблицы:
  - Player:     информация об игроке + его ELO рейтинги
  - Match:      результат матча + ELO до/после
  - Prediction:  предсказание модели + был ли прав
"""

from datetime import date, datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Boolean, Date, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import yaml
import os

# === Загружаем конфиг ===
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

# === Создаём базу ===
Base = declarative_base()
engine = create_engine(config['database']['url'], echo=False)
Session = sessionmaker(bind=engine)


class Player(Base):
    """
    Игрок в настольный теннис.
    Хранит базовую инфу + три типа ELO-рейтингов.
    """
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Основная информация ---
    name = Column(String(200), nullable=False)           # "Fan Zhendong"
    country = Column(String(3), nullable=True)            # "CHN"
    birth_year = Column(Integer, nullable=True)           # 1997
    gender = Column(String(1), nullable=True)             # "M" / "F"
    hand = Column(String(10), nullable=True)              # "right" / "left"
    style = Column(String(20), nullable=True)             # "shakehand" / "penhold"

    # --- Рейтинги ITTF ---
    ittf_ranking = Column(Integer, nullable=True)         # Текущий рейтинг ITTF
    ittf_points = Column(Integer, nullable=True)          # Очки ITTF

    # --- ELO рейтинги (считаем сами) ---
    elo_overall = Column(Float, default=1500.0)           # Общий ELO
    elo_major = Column(Float, default=1500.0)             # ELO на крупных турнирах
    elo_league = Column(Float, default=1500.0)            # ELO в лигах

    # --- Статистика ---
    total_matches = Column(Integer, default=0)            # Всего матчей в БД
    total_wins = Column(Integer, default=0)               # Всего побед

    # --- Даты ---
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Player(id={self.id}, name='{self.name}', elo={self.elo_overall:.0f})>"

    @property
    def win_rate(self):
        """Процент побед (0.0 - 1.0)"""
        if self.total_matches == 0:
            return 0.0
        return self.total_wins / self.total_matches


class Match(Base):
    """
    Результат одного матча.
    Хранит счёт, уровень турнира и ELO обоих игроков до/после матча.
    """
    __tablename__ = 'matches'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Когда и где ---
    date = Column(Date, nullable=False)                    # Дата матча
    tournament = Column(String(300), nullable=True)        # "WTT Champions Chongqing 2024"
    tournament_level = Column(String(20), nullable=True)   # "major" / "contender" / "league"
    round_name = Column(String(50), nullable=True)         # "QF" / "SF" / "F" / "R32"
    event_type = Column(String(10), default='MS')          # "MS" (Men Singles), "WS", etc.

    # --- Игроки ---
    player1_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    player2_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    winner_id = Column(Integer, ForeignKey('players.id'), nullable=False)

    # --- Счёт ---
    score = Column(String(10), nullable=True)              # "4-2" (по сетам)
    sets_detail = Column(Text, nullable=True)              # "11-7,9-11,11-5,11-8,13-11,11-6"

    # --- ELO до матча (для фичей модели) ---
    p1_elo_before = Column(Float, nullable=True)
    p2_elo_before = Column(Float, nullable=True)
    p1_elo_major_before = Column(Float, nullable=True)
    p2_elo_major_before = Column(Float, nullable=True)

    # --- ELO после матча ---
    p1_elo_after = Column(Float, nullable=True)
    p2_elo_after = Column(Float, nullable=True)

    # --- Мета ---
    source = Column(String(50), nullable=True)             # "ittf" / "flashscore" / "wtt"
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Связи ---
    player1 = relationship("Player", foreign_keys=[player1_id])
    player2 = relationship("Player", foreign_keys=[player2_id])
    winner = relationship("Player", foreign_keys=[winner_id])

    def __repr__(self):
        return (
            f"<Match(id={self.id}, date={self.date}, "
            f"p1={self.player1_id} vs p2={self.player2_id}, "
            f"winner={self.winner_id}, score='{self.score}')>"
        )

    @property
    def is_upset(self):
        """Был ли апсет — победил игрок с более низким ELO"""
        if self.p1_elo_before and self.p2_elo_before:
            higher_elo_player = (
                self.player1_id if self.p1_elo_before >= self.p2_elo_before
                else self.player2_id
            )
            return self.winner_id != higher_elo_player
        return None


class Prediction(Base):
    """
    Предсказание модели на конкретный матч.
    После матча помечаем correct = True/False.
    """
    __tablename__ = 'predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Связь с матчем ---
    match_id = Column(Integer, ForeignKey('matches.id'), nullable=False)

    # --- Предсказание ---
    p1_win_prob = Column(Float, nullable=False)            # 0.73
    p2_win_prob = Column(Float, nullable=False)            # 0.27
    predicted_winner_id = Column(Integer, ForeignKey('players.id'), nullable=False)

    # --- Результат (заполняется после матча) ---
    actual_winner_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    correct = Column(Boolean, nullable=True)

    # --- Версия модели ---
    model_version = Column(String(50), default='v0.1-xgboost')
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Связи ---
    match = relationship("Match")
    predicted_winner = relationship("Player", foreign_keys=[predicted_winner_id])
    actual_winner = relationship("Player", foreign_keys=[actual_winner_id])

    def __repr__(self):
        status = "✓" if self.correct else ("✗" if self.correct is False else "?")
        return (
            f"<Prediction(match={self.match_id}, "
            f"p1={self.p1_win_prob:.0%} / p2={self.p2_win_prob:.0%}, "
            f"status={status})>"
        )


def init_db():
    """Создать все таблицы в базе данных"""
    Base.metadata.create_all(engine)
    print("✅ База данных создана успешно!")
    print(f"   Таблицы: players, matches, predictions")
    print(f"   Путь: {config['database']['url']}")


def get_session():
    """Получить сессию для работы с БД"""
    return Session()


# === Если запускаем этот файл напрямую — создаём базу ===
if __name__ == '__main__':
    init_db()
