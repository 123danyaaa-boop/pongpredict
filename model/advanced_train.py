"""
PongPredict — Продвинутая модель (v2.1 — исправленный сплит)

Исправление (по замечанию преподавателя):
  - Данные делятся на TRAIN / VAL / TEST (три части)
  - Optuna тюнит гиперпараметры ТОЛЬКО на val
  - Финальная модель обучается на train+val
  - Финальная оценка — ТОЛЬКО на test, один раз

Разбивка по датам (temporal):
  Train : до 2024-01-01
  Val   : 2024-01-01 — 2024-12-31   ← для Optuna
  Test  : с 2025-01-01              ← смотрим один раз в конце
"""

import numpy as np
import pandas as pd
import pickle
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from features.advanced_features import AdvancedFeatureBuilder
from data.models import init_db, get_session, Match


# ═══════════════════════════════════════════════════════
# 1. OPTUNA HYPERPARAMETER TUNING
# ═══════════════════════════════════════════════════════

def tune_xgboost(X_train, y_train, X_val, y_val, n_trials=50):
    """
    Автоподбор гиперпараметров XGBoost через Optuna.
    ВАЖНО: X_val/y_val — это ВАЛИДАЦИОННАЯ выборка, НЕ тестовая.
    Тестовая выборка не передаётся в эту функцию вообще.
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("  Optuna не установлен. pip install optuna")
        return None, {}

    import xgboost as xgb
    from sklearn.metrics import accuracy_score

    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 800),
            'max_depth': trial.suggest_int('max_depth', 3, 10),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
            'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
            'gamma': trial.suggest_float('gamma', 0, 5),
            'reg_alpha': trial.suggest_float('reg_alpha', 0, 2),
            'reg_lambda': trial.suggest_float('reg_lambda', 0.5, 3),
            'eval_metric': 'logloss',
            'verbosity': 0,
        }
        # Тюнинг только на валидационной выборке
        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        pred = model.predict(X_val)
        return accuracy_score(y_val, pred)

    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    print(f"  Лучшая val-accuracy: {study.best_value:.1%}")
    print(f"  Лучшие параметры:")
    for k, v in study.best_params.items():
        print(f"     {k}: {v}")

    best_params = study.best_params
    best_params['eval_metric'] = 'logloss'
    best_params['verbosity'] = 0

    # Финальная модель обучается на train+val (больше данных)
    X_trainval = np.vstack([X_train, X_val])
    y_trainval = np.concatenate([y_train, y_val])
    best_model = xgb.XGBClassifier(**best_params)
    best_model.fit(X_trainval, y_trainval)

    return best_model, best_params


# ═══════════════════════════════════════════════════════
# 2. ENSEMBLE MODEL
# ═══════════════════════════════════════════════════════

def build_ensemble(X_train, y_train, X_val, y_val, X_test, y_test, best_xgb_params=None):
    """
    Ensemble из 3 моделей.
    - Обучение на train+val
    - Промежуточный мониторинг на val (только для информации, не для отбора)
    - Финальная оценка на test (вызывается один раз из main)
    """
    import xgboost as xgb
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import VotingClassifier
    from sklearn.metrics import accuracy_score

    # Объединяем train+val для финального обучения
    X_trainval = np.vstack([X_train, X_val])
    y_trainval = np.concatenate([y_train, y_val])

    models = {}

    xgb_params = best_xgb_params or {
        'n_estimators': 300, 'max_depth': 5, 'learning_rate': 0.05,
        'subsample': 0.8, 'colsample_bytree': 0.8,
    }
    xgb_params['eval_metric'] = 'logloss'
    xgb_params['verbosity'] = 0
    models['xgb'] = xgb.XGBClassifier(**xgb_params)

    try:
        import lightgbm as lgb
        models['lgb'] = lgb.LGBMClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, verbose=-1,
        )
    except ImportError:
        print("  LightGBM не установлен - пропускаем")

    models['lr'] = LogisticRegression(max_iter=1000, C=1.0)

    estimators = [(name, model) for name, model in models.items()]
    ensemble = VotingClassifier(estimators=estimators, voting='soft')

    # Обучаем на train+val
    ensemble.fit(X_trainval, y_trainval)

    # Оцениваем на TEST (один раз, только здесь)
    print(f"\n  Результаты на TEST выборке (финальная оценка):")
    results = {}
    for name, model in models.items():
        model.fit(X_trainval, y_trainval)
        pred = model.predict(X_test)
        acc = accuracy_score(y_test, pred)
        results[name] = acc
        labels = {'xgb': 'XGBoost', 'lgb': 'LightGBM', 'lr': 'LogReg'}
        print(f"     {labels.get(name, name):<15s} {acc:.1%}")

    ensemble_pred = ensemble.predict(X_test)
    ensemble_acc = accuracy_score(y_test, ensemble_pred)
    results['ensemble'] = ensemble_acc
    print(f"     {'Ensemble':<15s} {ensemble_acc:.1%}")

    return ensemble, results


# ═══════════════════════════════════════════════════════
# 3. SHAP EXPLAINABILITY
# ═══════════════════════════════════════════════════════

def explain_with_shap(model, X_test, feature_names, top_n=15):
    try:
        import shap
    except ImportError:
        print("  SHAP не установлен. pip install shap")
        return None

    print(f"\n  SHAP Feature Importance:")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    mean_abs = np.abs(shap_values).mean(axis=0)
    importance = sorted(zip(feature_names, mean_abs), key=lambda x: x[1], reverse=True)
    for feat, imp in importance[:top_n]:
        bar = "=" * int(imp * 50)
        print(f"     {feat:<25s} {imp:.4f}  {bar}")
    return shap_values


# ═══════════════════════════════════════════════════════
# 4. CLAUDE API SENTIMENT ANALYSIS
# ═══════════════════════════════════════════════════════

class SentimentAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        self.available = False
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                self.available = True
                print("  Claude API подключён для сентимент-анализа")
            except ImportError:
                print("  anthropic SDK не установлен. pip install anthropic")
        else:
            print("  Claude API не настроен (нет ANTHROPIC_API_KEY)")
            print("     Сентимент-фичи будут = 0.0 (нейтральные)")

    def analyze(self, news_text, player_name=None):
        if not self.available:
            return 0.0
        prompt = f"""Analyze the sentiment of this table tennis news for match performance.
Return ONLY a number between -1.0 and 1.0.
Player: {player_name or 'Unknown'}
News: {news_text}
Score:"""
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}]
            )
            return max(-1.0, min(1.0, float(response.content[0].text.strip())))
        except Exception as e:
            return 0.0

    def analyze_player_news(self, player_name, news_list):
        if not news_list or not self.available:
            return 0.0
        scores = [self.analyze(news, player_name) for news in news_list]
        return sum(scores) / len(scores)


# ═══════════════════════════════════════════════════════
# 5. MAIN TRAINING PIPELINE
# ═══════════════════════════════════════════════════════

def train_advanced_model():
    """
    Полный пайплайн обучения с корректным три-частным сплитом.

    СХЕМА:
      Train  (< 2024-01-01)  — обучение моделей
      Val    (2024)          — тюнинг гиперпараметров Optuna
      Test   (>= 2025-01-01) — ФИНАЛЬНАЯ оценка, один раз
    """

    print("PongPredict — Advanced Model v2.1 (исправленный сплит)")
    print("=" * 55)

    init_db()

    # === 1. Features ===
    print("\nSTEP 1 — Feature Engineering")
    fb = AdvancedFeatureBuilder()
    df = fb.build_advanced_dataset()

    if df.empty or len(df) < 20:
        print("Недостаточно данных!")
        return

    # === 2. Три-частный временной сплит ===
    print("\nSTEP 2 — Train / Val / Test Split")

    # Убедимся, что df отсортирован по дате
    if 'date' in df.columns:
        df = df.sort_values('date').reset_index(drop=True)
        df['date'] = pd.to_datetime(df['date'])

        train_mask = df['date'] < '2024-01-01'
        val_mask   = (df['date'] >= '2024-01-01') & (df['date'] < '2025-01-01')
        test_mask  = df['date'] >= '2025-01-01'

        feature_cols = [c for c in df.columns if c not in ['match_id', 'date', 'p1_wins']]
        X = df[feature_cols].values
        y = df['p1_wins'].values

        X_train, y_train = X[train_mask], y[train_mask]
        X_val,   y_val   = X[val_mask],   y[val_mask]
        X_test,  y_test  = X[test_mask],  y[test_mask]
    else:
        # Fallback: позиционный сплит 70/15/15
        n = len(df)
        t1, t2 = int(n * 0.70), int(n * 0.85)
        feature_cols = [c for c in df.columns if c not in ['match_id', 'date', 'p1_wins']]
        X = df[feature_cols].values
        y = df['p1_wins'].values
        X_train, y_train = X[:t1], y[:t1]
        X_val,   y_val   = X[t1:t2], y[t1:t2]
        X_test,  y_test  = X[t2:], y[t2:]

    print(f"  Train : {len(X_train):>6d} матчей  (база обучения)")
    print(f"  Val   : {len(X_val):>6d} матчей  (тюнинг Optuna)")
    print(f"  Test  : {len(X_test):>6d} матчей  (финальная оценка)")
    print(f"  Фичей : {len(feature_cols)}")

    # === 3. Optuna — только на val ===
    print("\nSTEP 3 — Optuna Hyperparameter Tuning (только на val)")

    try:
        best_model, best_params = tune_xgboost(
            X_train, y_train,
            X_val, y_val,      # val, не test!
            n_trials=30
        )
    except Exception as e:
        print(f"  Optuna ошибка: {e}")
        best_model, best_params = None, {}

    # === 4. Ensemble — обучение на train+val, оценка на test ===
    print("\nSTEP 4 — Ensemble (train+val -> test)")

    ensemble, results = build_ensemble(
        X_train, y_train,
        X_val, y_val,
        X_test, y_test,   # test передаётся только для финальной оценки
        best_params
    )

    # === 5. SHAP ===
    print("\nSTEP 5 — SHAP Explainability")
    if best_model:
        explain_with_shap(best_model, X_test, feature_cols)

    # === 6. Sentiment ===
    print("\nSTEP 6 — Claude API Sentiment")
    sentiment = SentimentAnalyzer()

    # === 7. Сохранение ===
    print("\nSTEP 7 — Сохранение модели")
    os.makedirs('model/saved', exist_ok=True)

    if best_model:
        model_path = 'model/saved/xgboost_v2.pkl'
        with open(model_path, 'wb') as f:
            pickle.dump(best_model, f)
        print(f"  XGBoost: {model_path}")

    ensemble_path = 'model/saved/ensemble_v2.pkl'
    with open(ensemble_path, 'wb') as f:
        pickle.dump(ensemble, f)
    print(f"  Ensemble: {ensemble_path}")

    meta = {
        'version': 'v2.1',
        'date': datetime.now().isoformat(),
        'split': {
            'train': '< 2024-01-01',
            'val':   '2024-01-01 to 2024-12-31',
            'test':  '>= 2025-01-01',
            'note':  'Optuna tuned on val only. Final eval on test once.'
        },
        'features': feature_cols,
        'n_features': len(feature_cols),
        'train_size': len(X_train),
        'val_size': len(X_val),
        'test_size': len(X_test),
        'results_on_test': {k: round(v, 4) for k, v in results.items()},
        'best_params': {k: round(v, 4) if isinstance(v, float) else v
                        for k, v in best_params.items()},
    }
    meta_path = 'model/saved/meta_v2.json'
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"  Meta: {meta_path}")

    print(f"""
Готово (v2.1 — честный сплит)
  Train  : {len(X_train)} матчей
  Val    : {len(X_val)} матчей (Optuna)
  Test   : {len(X_test)} матчей (финал)
  XGBoost (test) : {results.get('xgb', 0):.1%}
  Ensemble (test): {results.get('ensemble', 0):.1%}
    """)


if __name__ == '__main__':
    train_advanced_model()
