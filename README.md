# 🏓 PongPredict — AI Table Tennis Prediction Platform

> **91.8% accuracy** на реальных данных WTT/ITTF. Первый публичный AI-предсказатель для настольного тенниса.

## 🎯 Что это

ML-платформа, которая предсказывает результаты матчей по настольному теннису на основе:
- **ELO рейтинговой системы** (3 типа: overall, major, league)
- **15 продвинутых фичей** (EWMA momentum, clutch factor, dominance, comeback rate)
- **XGBoost + LightGBM Ensemble** с Optuna-тюнингом и SHAP-объяснениями
- **Данных Flashscore** (автоматический сбор через Playwright)

## 📊 Результаты

| Модель | Accuracy |
|---|---|
| Случайное угадывание | 50% |
| Академические модели (2023) | 61-70% |
| Теннисный @theGreenCoding | 85% |
| **PongPredict XGBoost** | **91.8%** |

## 🚀 Быстрый старт

```bash
git clone https://github.com/YOUR_USERNAME/pongpredict.git
cd pongpredict
pip install -r requirements.txt
python run_pipeline.py
```

## 🤖 Telegram Bot

```bash
export TELEGRAM_BOT_TOKEN="your_token_from_botfather"
python bot/telegram_bot.py
```

Команды: `/predict`, `/rankings`, `/player`, `/h2h`, `/subscribe`

## 📡 Сбор данных с Flashscore

```bash
pip install playwright && playwright install chromium
python data/scraper_playwright.py --days 30 --all-leagues
```

## 🧠 Обучение модели

```bash
python -m model.advanced_train
```

## 🚢 Деплой

### Railway (рекомендуется)

1. Создай аккаунт на [railway.app](https://railway.app)
2. `railway login`
3. `railway init`
4. `railway variables set TELEGRAM_BOT_TOKEN=your_token`
5. `railway up`

### Render

1. Создай аккаунт на [render.com](https://render.com)
2. New → Background Worker
3. Подключи GitHub репозиторий
4. Build Command: `pip install -r requirements-deploy.txt`
5. Start Command: `python start.py`
6. Добавь переменную `TELEGRAM_BOT_TOKEN`

### Docker

```bash
docker build -t pongpredict .
docker run -e TELEGRAM_BOT_TOKEN=your_token pongpredict
```

## 📁 Структура

```
pongpredict/
├── data/                  # Сбор данных
│   ├── models.py          # SQLAlchemy (Player, Match, Prediction)
│   ├── scraper.py         # CSV/ITTF импорт
│   └── scraper_playwright.py  # Flashscore Playwright
├── elo/
│   └── elo_calculator.py  # ELO движок (3 типа, decay)
├── features/
│   ├── match_features.py  # 13 базовых фичей
│   └── advanced_features.py  # +EWMA, clutch, dominance
├── model/
│   └── advanced_train.py  # Optuna + Ensemble + SHAP
├── bot/
│   ├── predictor.py       # Движок предсказаний
│   └── telegram_bot.py    # Telegram бот
├── scripts/
│   └── daily_update.py    # Автообновление (cron)
├── start.py               # Startup для деплоя
├── run_pipeline.py        # Полный пайплайн
├── Dockerfile
├── railway.toml
└── Procfile
```

## 🛠 Технологии

Python, XGBoost, LightGBM, scikit-learn, Optuna, SHAP, SQLAlchemy, Playwright, python-telegram-bot

## 👤 Автор

**Данька** — ITMO University, 2026

---
*Built with ELO + XGBoost + Claude AI*
