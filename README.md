# PongPredict — ML-предсказание матчей по настольному теннису

Система предсказания исходов профессиональных матчей настольного тенниса на основе ELO-рейтингов и ансамбля градиентного бустинга.

## Результаты

| Модель | Accuracy | Brier Score |
|---|---|---|
| Случайный выбор | 50.00% | 0.2500 |
| ELO (baseline) | 72.90% | 0.1807 |
| Logistic Regression | 73.63% | 0.1743 |
| XGBoost | 73.62% | 0.1743 |
| LightGBM | 73.63% | 0.1742 |
| **Ансамбль (XGB+LGB+LR)** | **73.65%** | **0.1741** |

Оценка на строгой тестовой выборке: 54 052 матча (2025–2026 г.). Данные разбиты на train/val/test без утечки через тестовую выборку.

## Данные

- **Источник:** ITTF (ittf.com), парсер на Playwright
- **Объём:** 179 204 матча, 14 672 игрока
- **Период:** 2019–2026 г.
- **Разбивка:** train < 2024-01-01 (89 267) / val = 2024 (35 241) / test >= 2025-01-01 (54 052)

## Методология

**Трёхуровневый ELO** — отдельные рейтинги для overall / major / league с адаптивным K-фактором (32/24/16) и мультипликаторами турниров (1.5/1.3/1.1/1.0).

**Признаки (4):** `elo_diff`, `elo_prob`, `form_5_diff` (скользящий win rate за 5 матчей), `level_num`.

**Ансамбль:** XGBoost + LightGBM + Logistic Regression, мягкое голосование. Optuna тюнит гиперпараметры только на val-выборке, финальная модель обучается на train+val, тест используется один раз.

**Калибровка:** изотоническая регрессия (CalibratedClassifierCV).

## Быстрый старт

```bash
git clone https://github.com/123danyaaa-boop/pongpredict.git
cd pongpredict
pip install -r requirements.txt
python run_pipeline.py
```

## Telegram Bot

```bash
export TELEGRAM_BOT_TOKEN="your_token_from_botfather"
python start.py
```

Команды: `/predict`, `/rankings`, `/player`, `/h2h`, `/subscribe`

## Сбор данных

```bash
pip install playwright && playwright install chromium
python data/scraper_ittf_pw.py
```

## Обучение модели

```bash
python -m model.advanced_train
```

## Деплой

### Railway

```bash
railway login && railway init
railway variables set TELEGRAM_BOT_TOKEN=your_token
railway up
```

### Docker

```bash
docker build -t pongpredict .
docker run -e TELEGRAM_BOT_TOKEN=your_token pongpredict
```

### Render

New → Background Worker → подключи репо → Start Command: `python start.py`

## Структура проекта

```
pongpredict/
├── data/
│   ├── models.py              # SQLAlchemy модели (Player, Match, Prediction)
│   └── scraper_ittf_pw.py     # Playwright парсер ITTF
├── elo/
│   └── elo_calculator.py      # Трёхуровневый ELO-движок
├── features/
│   ├── match_features.py      # Базовые признаки
│   └── advanced_features.py   # EWMA, clutch factor, dominance
├── model/
│   └── advanced_train.py      # Optuna + Ensemble + SHAP
├── bot/
│   ├── predictor.py           # Движок предсказаний
│   └── telegram_bot.py        # Telegram бот
├── scripts/
│   └── daily_update.py        # Автообновление (cron)
├── start.py                   # Точка входа для деплоя
├── run_pipeline.py            # Полный пайплайн
├── config.yaml                # Конфигурация ELO и модели
├── Dockerfile
├── railway.toml
└── Procfile
```

## Технологии

Python 3.12, XGBoost, LightGBM, scikit-learn, Optuna, SHAP, SQLAlchemy, Playwright, python-telegram-bot

## Автор

Даниил Абызов — Университет ИТМО, Санкт-Петербург, 2026
