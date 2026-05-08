# TenderPlatform — Интеллектуальная платформа государственных закупок

Автоматизация участия в государственных закупках по **44-ФЗ** и **223-ФЗ**.

## Функции

| Модуль | Описание |
|--------|----------|
| **Парсер документации** | Извлечение требований из PDF/DOCX через NLP (spaCy + regex) |
| **Сопоставление требований** | Семантическое сравнение с профилем компании (sentence-transformers) |
| **Анализ рисков** | Выявление штрафных санкций, нацрежима, нереальных сроков |
| **Генерация документов** | Заявка, техпредложение, декларация, форма 2 (DOCX) |
| **Модель вероятности победы** | LightGBM/LogisticRegression, калибровка на истории участий |

## Быстрый старт

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Скачать русскую модель spaCy
python -m spacy download ru_core_news_lg

# 3. Скопировать конфиг окружения
cp .env.example .env

# 4. Запустить демо (создаёт тестовые тендеры и прогоняет пайплайн)
python demo/seed_data.py

# 5. Запустить UI
streamlit run ui/app.py

# или запустить REST API
python api/main.py
```

## Структура проекта

```
tender_platform/
├── core/
│   ├── database.py          # SQLAlchemy engine + session
│   └── models.py            # ORM-модели (Tender, CompanyProfile, ...)
├── modules/
│   ├── document_parser.py   # Парсинг PDF/DOCX, извлечение требований
│   ├── requirement_matcher.py  # Семантическое сопоставление
│   ├── risk_analyzer.py     # Анализ рисков по паттернам
│   ├── doc_generator.py     # Генерация DOCX-документов
│   └── win_probability_model.py  # ML-модель вероятности победы
├── api/
│   ├── main.py              # FastAPI приложение
│   └── routers/
│       ├── tenders.py       # POST /upload, GET /, POST /{id}/analyze
│       ├── company.py       # CRUD профиля компании
│       └── documents.py     # POST /generate, GET /{id}/download
├── ui/
│   └── app.py               # Streamlit UI (5 вкладок)
├── demo/
│   └── seed_data.py         # Демо-данные + прогон пайплайна
├── tests/
│   └── test_pipeline.py     # pytest-тесты
├── templates/               # DOCX-шаблоны (опционально)
├── output/
│   └── generated_docs/      # Сгенерированные документы
├── .env.example
└── requirements.txt
```

## REST API

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/v1/tenders/upload` | Загрузить файл тендерной документации |
| GET | `/api/v1/tenders/` | Список тендеров |
| GET | `/api/v1/tenders/{id}` | Детали тендера |
| POST | `/api/v1/tenders/{id}/analyze?company_id={id}` | Запустить анализ |
| DELETE | `/api/v1/tenders/{id}` | Удалить тендер |
| POST | `/api/v1/company/` | Создать профиль компании |
| GET | `/api/v1/company/{id}` | Получить профиль |
| PUT | `/api/v1/company/{id}` | Обновить профиль |
| POST | `/api/v1/company/{id}/history` | Добавить результат участия |
| POST | `/api/v1/documents/generate` | Сгенерировать документы |
| GET | `/api/v1/documents/{id}/download` | Скачать файл |

Swagger UI: `http://localhost:8000/docs`

## Тесты

```bash
# Запустить из папки tender_platform/
pytest tests/ -v
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `DATABASE_URL` | `sqlite:///tender_platform.db` | Строка подключения к БД |
| `OUTPUT_DIR` | `output/` | Директория для файлов |
| `MODEL_CACHE_DIR` | `output/model_cache/` | Кеш ML-моделей |
