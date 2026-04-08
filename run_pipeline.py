"""
PongPredict — Главный пайплайн

Запускает весь процесс от загрузки данных до обучения модели.
Это точка входа в проект.

Использование:
    python run_pipeline.py              — полный пайплайн с тестовыми данными
    python run_pipeline.py --skip-data  — пропустить загрузку (данные уже есть)
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

# Добавляем корень проекта
sys.path.insert(0, os.path.dirname(__file__))

from data.models import init_db, get_session, Player, Match
from data.scraper import CSVImporter, create_sample_csv
from elo.elo_calculator import EloCalculator
from features.match_features import FeatureBuilder


def step_1_load_data():
    """Шаг 1: Загрузка данных в БД"""
    print("=" * 60)
    print("STEP 1 — Загрузка данных")
    print("=" * 60)

    # Инициализируем базу
    init_db()

    # Проверяем есть ли уже данные
    db = get_session()
    existing = db.query(Match).count()
    db.close()

    if existing > 0:
        print(f"  ℹ️ В базе уже {existing} матчей")
        return existing

    # Создаём и загружаем тестовые данные
    filepath = create_sample_csv()
    importer = CSVImporter()
    count = importer.import_file(filepath)
    return count


def step_2_calculate_elo():
    """Шаг 2: Расчёт ELO по всей истории"""
    print("\n" + "=" * 60)
    print("STEP 2 — Расчёт ELO рейтингов")
    print("=" * 60)

    db = get_session()

    # Получаем все матчи в хронологическом порядке
    matches = (
        db.query(Match)
        .order_by(Match.date)
        .all()
    )

    if not matches:
        print("  ❌ Нет матчей в базе!")
        return None

    # Конвертируем в формат для backfill
    match_dicts = []
    for m in matches:
        winner_id = m.winner_id
        loser_id = m.player2_id if winner_id == m.player1_id else m.player1_id
        match_dicts.append({
            'winner_id': winner_id,
            'loser_id': loser_id,
            'tournament_level': m.tournament_level or 'regular',
            'date': m.date,
        })

    # Прогоняем backfill
    elo = EloCalculator()
    stats = elo.backfill(match_dicts)

    # Обновляем ELO в базе
    for player_id, ratings in elo.ratings.items():
        player = db.query(Player).get(player_id)
        if player:
            player.elo_overall = ratings['overall']
            player.elo_major = ratings['major']
            player.elo_league = ratings['league']

    db.commit()

    # Показываем топ игроков
    print("\n  🏆 Топ-10 игроков по ELO:")
    top = elo.get_top_players(n=10, min_matches=1)
    for i, (pid, rating, mc) in enumerate(top, 1):
        player = db.query(Player).get(pid)
        name = player.name if player else f"Player {pid}"
        print(f"    {i:2d}. {name:<25s} ELO: {rating:.0f}  ({mc} матчей)")

    db.close()
    return elo


def step_3_build_features():
    """Шаг 3: Генерация фичей"""
    print("\n" + "=" * 60)
    print("STEP 3 — Feature Engineering")
    print("=" * 60)

    fb = FeatureBuilder()
    df = fb.build_dataset()

    if df.empty:
        return None

    # Показываем корреляции
    print("\n  📊 Корреляции с target (p1_wins):")
    feature_cols = [c for c in df.columns if c not in ['match_id', 'date', 'p1_wins']]
    corr = df[feature_cols + ['p1_wins']].corr()['p1_wins'].drop('p1_wins')
    corr_sorted = corr.abs().sort_values(ascending=False)

    for feat in corr_sorted.index:
        val = corr[feat]
        if pd.isna(val):
            continue
        bar = "█" * int(abs(val) * 30)
        sign = "+" if val > 0 else "-"
        print(f"    {feat:<22s} {sign}{abs(val):.3f}  {bar}")

    return df


def step_4_train_model(df):
    """Шаг 4: Обучение XGBoost"""
    print("\n" + "=" * 60)
    print("STEP 4 — Обучение модели")
    print("=" * 60)

    if df is None or df.empty:
        print("  ❌ Нет данных для обучения!")
        return None

    # Фичи и target
    feature_cols = [c for c in df.columns if c not in ['match_id', 'date', 'p1_wins']]
    X = df[feature_cols].values
    y = df['p1_wins'].values

    print(f"  📐 Размер данных: {X.shape[0]} матчей, {X.shape[1]} фичей")

    # Для тестовых данных (мало строк) — используем cross-validation
    if len(df) < 50:
        print("  ⚠️ Мало данных для train/test split!")
        print("  ℹ️ Используем Leave-One-Out для оценки")

        from sklearn.model_selection import cross_val_score
        from sklearn.linear_model import LogisticRegression

        # Простая логистическая регрессия (XGBoost нужно больше данных)
        model = LogisticRegression(max_iter=1000, C=1.0)

        if len(df) >= 5:
            scores = cross_val_score(model, X, y, cv=min(5, len(df)), scoring='accuracy')
            print(f"\n  📈 Cross-validation accuracy: {scores.mean():.1%} ± {scores.std():.1%}")

        # Обучаем на всех данных для демо
        model.fit(X, y)

        # Feature importance (через коэффициенты)
        print(f"\n  🔍 Feature importance (LogReg coefficients):")
        importances = sorted(
            zip(feature_cols, abs(model.coef_[0])),
            key=lambda x: x[1], reverse=True
        )
        for feat, imp in importances:
            bar = "█" * int(imp * 10)
            print(f"    {feat:<22s} {imp:.3f}  {bar}")

        return model

    else:
        # Полноценный train/test split по дате
        try:
            import xgboost as xgb
            from sklearn.metrics import accuracy_score, classification_report

            split_idx = int(len(df) * 0.8)
            X_train, X_test = X[:split_idx], X[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]

            model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric='logloss',
                use_label_encoder=False,
                verbosity=0,
            )

            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                verbose=False,
            )

            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)

            print(f"\n  📈 Test accuracy: {accuracy:.1%}")
            print(f"\n  📋 Classification report:")
            print(classification_report(y_test, y_pred, target_names=['P2 wins', 'P1 wins']))

            # Feature importance
            print(f"  🔍 Feature importance (XGBoost):")
            importances = sorted(
                zip(feature_cols, model.feature_importances_),
                key=lambda x: x[1], reverse=True
            )
            for feat, imp in importances:
                bar = "█" * int(imp * 50)
                print(f"    {feat:<22s} {imp:.3f}  {bar}")

            return model

        except ImportError:
            print("  ⚠️ XGBoost не установлен. Установи: pip install xgboost")
            return None


def step_5_summary(elo, df, model):
    """Шаг 5: Итоги"""
    print("\n" + "=" * 60)
    print("STEP 5 — Итоги")
    print("=" * 60)

    db = get_session()
    n_players = db.query(Player).count()
    n_matches = db.query(Match).count()
    db.close()

    print(f"""
  🏓 PongPredict MVP — статус:

    Игроков в базе:    {n_players}
    Матчей в базе:     {n_matches}
    Фичей в модели:    {len(df.columns) - 2 if df is not None else 0}
    Модель обучена:    {'✅ Да' if model else '❌ Нет'}

  📋 Следующие шаги:

    1. Собрать больше данных (цель: 10,000+ матчей)
       → Парсить worldtabletennis.com через DevTools API
       → Или скачать датасеты с Kaggle / OSAI

    2. Улучшить ELO систему
       → Добавить ELO по формату (best-of-5 vs best-of-7)
       → Decay для неактивных игроков

    3. Добавить фичи
       → Процент побед по сетам (clutch factor)
       → Средний счёт в проигранных сетах (competitiveness)

    4. Развернуть веб-приложение
       → Streamlit для быстрого MVP
       → Предсказания на ближайшие турниры

    5. Валидация на реальном турнире
       → Предсказать матчи ДО начала
       → Сравнить с результатами
    """)


def main():
    parser = argparse.ArgumentParser(description='PongPredict — Полный пайплайн')
    parser.add_argument('--skip-data', action='store_true',
                        help='Пропустить загрузку данных')
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════╗
    ║  🏓 PongPredict — AI Table Tennis       ║
    ║     Match Prediction Pipeline            ║
    ╚══════════════════════════════════════════╝
    """)

    # Step 1: Данные
    if not args.skip_data:
        step_1_load_data()

    # Step 2: ELO
    elo = step_2_calculate_elo()

    # Step 3: Фичи
    df = step_3_build_features()

    # Step 4: Модель
    model = step_4_train_model(df)

    # Step 5: Итоги
    step_5_summary(elo, df, model)


if __name__ == '__main__':
    main()
