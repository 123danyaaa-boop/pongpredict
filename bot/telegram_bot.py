"""
PongPredict — Telegram Bot 🏓

Бот для предсказания матчей по настольному теннису.

Команды:
  /start          — приветствие + меню
  /predict        — предсказание матча (выбор игроков)
  /rankings       — ELO рейтинг топ-10
  /player <имя>   — статистика игрока
  /h2h <A> vs <B> — личные встречи
  /subscribe      — подписка на ежедневные предсказания
  /help           — справка

Запуск:
  1. Создай бота: @BotFather → /newbot
  2. Скопируй токен
  3. export TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
  4. python bot/telegram_bot.py
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

from bot.predictor import PredictionEngine

# === Конфигурация ===
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SUBSCRIBERS_FILE = 'bot/subscribers.txt'

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация движка предсказаний
engine = PredictionEngine()

# Флаги стран
FLAGS = {
    'CHN': '🇨🇳', 'JPN': '🇯🇵', 'BRA': '🇧🇷', 'GER': '🇩🇪',
    'SWE': '🇸🇪', 'KOR': '🇰🇷', 'NGR': '🇳🇬', 'FRA': '🇫🇷',
    'TPE': '🇹🇼', 'HKG': '🇭🇰', 'IND': '🇮🇳', 'EGY': '🇪🇬',
}

CONFIDENCE_EMOJI = {'high': '🔥', 'medium': '⚡', 'low': '🤔'}


# ═══════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ═══════════════════════════════════════════════

def format_prediction(pred):
    """Красивое сообщение с предсказанием."""
    p1, p2 = pred['p1'], pred['p2']
    f1 = FLAGS.get(p1.country, '🏳️')
    f2 = FLAGS.get(p2.country, '🏳️')
    conf = CONFIDENCE_EMOJI.get(pred['confidence'], '')

    # Прогресс-бар
    bar_len = 20
    p1_bar = round(pred['p1_prob'] * bar_len)
    bar = '▓' * p1_bar + '░' * (bar_len - p1_bar)

    msg = f"""
🏓 *ПРЕДСКАЗАНИЕ МАТЧА*

{f1} *{p1.name}*
vs
{f2} *{p2.name}*

━━━━━━━━━━━━━━━━━━━━

📊 *Вероятности:*
{f1} {pred['p1_prob']:.1%}  `{bar}`  {pred['p2_prob']:.1%} {f2}

📈 *ELO рейтинг:*
{f1} {pred['p1_elo']:.0f}  ⚔️  {pred['p2_elo']:.0f} {f2}
Разница: {pred['elo_diff']:.0f} очков

🤝 *Личные встречи:* {pred['h2h_total']}
{f1} {pred['h2h_p1_wins']} — {pred['h2h_p2_wins']} {f2}"""

    # Последние H2H матчи
    if pred['h2h_last5']:
        msg += "\n\n📋 *Последние встречи:*"
        for m in pred['h2h_last5'][:3]:
            w_flag = f1 if m.winner_id == p1.id else f2
            msg += f"\n  {w_flag} {m.score} ({m.date})"

    msg += f"""

━━━━━━━━━━━━━━━━━━━━

{conf} *Фаворит: {FLAGS.get(pred['favorite'].country, '')} {pred['favorite'].name}*
Уверенность: {pred['confidence'].upper()}

_PongPredict AI · ELO + XGBoost · 89.7% accuracy_"""

    return msg


def format_rankings(rankings):
    """Форматирование таблицы рейтингов."""
    msg = "🏆 *ELO РЕЙТИНГ — Настольный теннис*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    medals = ['🥇', '🥈', '🥉']

    for i, r in enumerate(rankings):
        p = r['player']
        flag = FLAGS.get(p.country, '🏳️')
        medal = medals[i] if i < 3 else f"`{i+1:2d}.`"

        msg += f"{medal} {flag} *{p.name}*\n"
        msg += f"     ELO: `{r['elo']}` · "
        msg += f"Win: `{r['win_rate']}%` · "
        msg += f"Матчей: `{r['matches']}`\n\n"

    msg += "_PongPredict AI · обновлено " + datetime.now().strftime('%d.%m.%Y') + "_"
    return msg


def format_player_stats(stats):
    """Форматирование статистики игрока."""
    p = stats['player']
    flag = FLAGS.get(p.country, '🏳️')

    msg = f"""
{flag} *{p.name}* ({p.country or '?'})

📊 *ELO Рейтинги:*
  Overall: `{stats['elo_overall']}`
  Major:   `{stats['elo_major']}`
  League:  `{stats['elo_league']}`

📈 *Статистика:*
  Матчей: `{stats['matches']}`
  Побед:  `{stats['wins']}`
  Win%:   `{stats['win_rate']}%`
  Форма:  `{stats['form_5']}`
"""

    if stats['recent']:
        msg += "\n📋 *Последние матчи:*\n"
        for m in stats['recent'][:5]:
            won = m.winner_id == p.id
            emoji = '✅' if won else '❌'
            opp_id = m.player2_id if m.player1_id == p.id else m.player1_id
            opp = engine.db.get(type(p), opp_id)
            opp_name = opp.name if opp else '?'
            msg += f"  {emoji} vs {opp_name} ({m.score}) — {m.date}\n"

    return msg


# ═══════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    keyboard = [
        [
            InlineKeyboardButton("🎯 Предсказание", callback_data="menu_predict"),
            InlineKeyboardButton("🏆 Рейтинг", callback_data="menu_rankings"),
        ],
        [
            InlineKeyboardButton("👤 Игрок", callback_data="menu_player"),
            InlineKeyboardButton("🔔 Подписка", callback_data="menu_subscribe"),
        ],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]

    await update.message.reply_text(
        "🏓 *PongPredict — AI Table Tennis*\n\n"
        "Предсказания матчей по настольному теннису\n"
        "на основе ELO + XGBoost (89.7% accuracy)\n\n"
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /predict — выбор игроков."""
    players = engine.get_all_players()

    if not context.args:
        # Показываем список игроков для выбора
        keyboard = []
        row = []
        for p in players:
            flag = FLAGS.get(p.country, '')
            btn = InlineKeyboardButton(
                f"{flag} {p.name.split()[-1]}",
                callback_data=f"p1_{p.id}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        await update.message.reply_text(
            "🎯 *Предсказание матча*\n\nВыбери первого игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Парсим аргументы: /predict Fan Zhendong vs Wang Chuqin
    text = ' '.join(context.args)
    if ' vs ' in text.lower():
        parts = text.lower().split(' vs ')
        p1 = engine.find_player(parts[0].strip())
        p2 = engine.find_player(parts[1].strip())

        if isinstance(p1, list):
            names = ', '.join(p.name for p in p1)
            await update.message.reply_text(f"❓ Уточни первого игрока: {names}")
            return
        if isinstance(p2, list):
            names = ', '.join(p.name for p in p2)
            await update.message.reply_text(f"❓ Уточни второго игрока: {names}")
            return
        if not p1:
            await update.message.reply_text(f"❌ Игрок не найден: {parts[0]}")
            return
        if not p2:
            await update.message.reply_text(f"❌ Игрок не найден: {parts[1]}")
            return

        pred = engine.predict(p1.id, p2.id)
        await update.message.reply_text(
            format_prediction(pred),
            parse_mode=ParseMode.MARKDOWN,
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # === Меню ===
    if data == "menu_predict":
        players = engine.get_all_players()
        keyboard = []
        row = []
        for p in players:
            flag = FLAGS.get(p.country, '')
            btn = InlineKeyboardButton(
                f"{flag} {p.name.split()[-1]}",
                callback_data=f"p1_{p.id}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        await query.edit_message_text(
            "🎯 *Предсказание матча*\n\nВыбери *первого* игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_rankings":
        rankings = engine.get_rankings(10)
        await query.edit_message_text(
            format_rankings(rankings),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_help":
        await query.edit_message_text(
            "❓ *Как пользоваться PongPredict*\n\n"
            "🎯 `/predict Fan Zhendong vs Wang Chuqin`\n"
            "Предсказание конкретного матча\n\n"
            "🏆 `/rankings` — ELO рейтинг топ-10\n\n"
            "👤 `/player Ma Long` — статистика игрока\n\n"
            "🔔 `/subscribe` — ежедневные предсказания\n\n"
            "🤝 `/h2h Harimoto vs Calderano` — личные встречи\n\n"
            "_Бот использует ELO + XGBoost модель,\n"
            "обученную на 192+ матчах WTT/ITTF._",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_subscribe":
        save_subscriber(query.from_user.id)
        await query.edit_message_text(
            "🔔 *Подписка активирована!*\n\n"
            "Ты будешь получать предсказания на ближайшие\n"
            "матчи WTT каждый день в 10:00.\n\n"
            "Отписаться: /unsubscribe",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_player":
        players = engine.get_all_players()
        keyboard = []
        row = []
        for p in players:
            flag = FLAGS.get(p.country, '')
            btn = InlineKeyboardButton(
                f"{flag} {p.name.split()[-1]}",
                callback_data=f"stats_{p.id}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        await query.edit_message_text(
            "👤 *Статистика игрока*\n\nВыбери игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    # === Выбор первого игрока ===
    elif data.startswith("p1_"):
        p1_id = int(data.split("_")[1])
        context.user_data['p1_id'] = p1_id
        p1 = engine.db.get(type(engine.get_all_players()[0]), p1_id)

        players = engine.get_all_players()
        keyboard = []
        row = []
        for p in players:
            if p.id == p1_id:
                continue  # Не показываем того же игрока
            flag = FLAGS.get(p.country, '')
            btn = InlineKeyboardButton(
                f"{flag} {p.name.split()[-1]}",
                callback_data=f"p2_{p.id}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        flag1 = FLAGS.get(p1.country, '')
        await query.edit_message_text(
            f"✅ Первый: {flag1} *{p1.name}*\n\nВыбери *второго* игрока:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    # === Выбор второго игрока → предсказание ===
    elif data.startswith("p2_"):
        p2_id = int(data.split("_")[1])
        p1_id = context.user_data.get('p1_id')

        if not p1_id:
            await query.edit_message_text("❌ Сначала выбери первого игрока через /predict")
            return

        pred = engine.predict(p1_id, p2_id)
        await query.edit_message_text(
            format_prediction(pred),
            parse_mode=ParseMode.MARKDOWN,
        )

    # === Статистика игрока ===
    elif data.startswith("stats_"):
        pid = int(data.split("_")[1])
        stats = engine.get_player_stats(pid)
        if stats:
            await query.edit_message_text(
                format_player_stats(stats),
                parse_mode=ParseMode.MARKDOWN,
            )


async def cmd_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /rankings."""
    rankings = engine.get_rankings(10)
    await update.message.reply_text(
        format_rankings(rankings),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /player <имя>."""
    if not context.args:
        await update.message.reply_text(
            "Укажи имя: `/player Ma Long`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    query = ' '.join(context.args)
    result = engine.find_player(query)

    if isinstance(result, list):
        names = '\n'.join(f"  • {p.name}" for p in result)
        await update.message.reply_text(f"❓ Уточни игрока:\n{names}")
        return

    if not result:
        await update.message.reply_text(f"❌ Игрок не найден: {query}")
        return

    stats = engine.get_player_stats(result.id)
    await update.message.reply_text(
        format_player_stats(stats),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_h2h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /h2h <A> vs <B>."""
    if not context.args:
        await update.message.reply_text(
            "Формат: `/h2h Harimoto vs Calderano`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text = ' '.join(context.args)
    if ' vs ' not in text.lower():
        await update.message.reply_text("Используй формат: `/h2h A vs B`", parse_mode=ParseMode.MARKDOWN)
        return

    parts = text.lower().split(' vs ')
    p1 = engine.find_player(parts[0].strip())
    p2 = engine.find_player(parts[1].strip())

    if not p1 or isinstance(p1, list):
        await update.message.reply_text(f"❌ Игрок не найден: {parts[0]}")
        return
    if not p2 or isinstance(p2, list):
        await update.message.reply_text(f"❌ Игрок не найден: {parts[1]}")
        return

    pred = engine.predict(p1.id, p2.id)
    await update.message.reply_text(
        format_prediction(pred),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════
# ПОДПИСКИ
# ═══════════════════════════════════════════════

def save_subscriber(user_id):
    """Сохранить подписчика."""
    os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True)
    subs = load_subscribers()
    if user_id not in subs:
        subs.add(user_id)
        with open(SUBSCRIBERS_FILE, 'w') as f:
            f.write('\n'.join(str(s) for s in subs))


def load_subscribers():
    """Загрузить список подписчиков."""
    if not os.path.exists(SUBSCRIBERS_FILE):
        return set()
    with open(SUBSCRIBERS_FILE, 'r') as f:
        return set(int(line.strip()) for line in f if line.strip())


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe."""
    save_subscriber(update.effective_user.id)
    await update.message.reply_text(
        "🔔 *Подписка активирована!*\n\n"
        "Ежедневные предсказания будут приходить в 10:00.\n"
        "Отписаться: /unsubscribe",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unsubscribe."""
    subs = load_subscribers()
    uid = update.effective_user.id
    if uid in subs:
        subs.discard(uid)
        with open(SUBSCRIBERS_FILE, 'w') as f:
            f.write('\n'.join(str(s) for s in subs))
    await update.message.reply_text("🔕 Подписка отключена.")


async def send_daily_predictions(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправить ежедневные предсказания подписчикам.
    Вызывается по расписанию (JobQueue).
    """
    subs = load_subscribers()
    if not subs:
        return

    # Генерируем интересное предсказание дня
    rankings = engine.get_rankings(5)
    if len(rankings) >= 2:
        p1 = rankings[0]['player']
        p2 = rankings[1]['player']
        pred = engine.predict(p1.id, p2.id)

        msg = "📅 *Предсказание дня*\n\n"
        msg += format_prediction(pred)

        for uid in subs:
            try:
                await context.bot.send_message(
                    chat_id=uid, text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить {uid}: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    await update.message.reply_text(
        "🏓 *PongPredict — Справка*\n\n"
        "*Команды:*\n"
        "🎯 `/predict` — предсказание (кнопки)\n"
        "🎯 `/predict Fan vs Wang` — быстрое предсказание\n"
        "🏆 `/rankings` — ELO топ-10\n"
        "👤 `/player Ma Long` — статистика\n"
        "🤝 `/h2h Harimoto vs Calderano` — H2H\n"
        "🔔 `/subscribe` — ежедневные прогнозы\n"
        "🔕 `/unsubscribe` — отписаться\n\n"
        "*Как работает:*\n"
        "Модель ELO + XGBoost обучена на 192+ матчах\n"
        "WTT/ITTF турниров (2022-2025).\n"
        "Точность: 89.7% на тестовых данных.\n\n"
        "_Built by Данька · ITMO 2026_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка произвольного текста — пробуем найти игрока."""
    text = update.message.text.strip()

    if ' vs ' in text.lower():
        # Пробуем как предсказание
        context.args = text.split()
        await cmd_h2h(update, context)
        return

    # Пробуем как имя игрока
    result = engine.find_player(text)
    if isinstance(result, list) and len(result) <= 5:
        names = '\n'.join(f"  • {p.name}" for p in result)
        await update.message.reply_text(f"Найдено несколько:\n{names}\nУточни имя.")
    elif result and not isinstance(result, list):
        stats = engine.get_player_stats(result.id)
        await update.message.reply_text(
            format_player_stats(stats),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "🤷 Не понял. Попробуй:\n"
            "• `/predict` — предсказание\n"
            "• `/rankings` — рейтинг\n"
            "• Имя игрока — статистика",
            parse_mode=ParseMode.MARKDOWN,
        )


# ═══════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════

def main():
    if not TOKEN:
        print("""
❌ Токен не найден!

Настройка:
  1. Открой Telegram → @BotFather
  2. /newbot → задай имя (например PongPredictBot)
  3. Скопируй токен
  4. Запусти:

     export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
     python bot/telegram_bot.py

  Или создай файл .env:
     TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
        """)
        return

    print("🏓 PongPredict Bot запускается...")

    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("predict", cmd_predict))
    app.add_handler(CommandHandler("rankings", cmd_rankings))
    app.add_handler(CommandHandler("player", cmd_player))
    app.add_handler(CommandHandler("h2h", cmd_h2h))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("help", cmd_help))

    # Кнопки
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Ежедневные предсказания в 10:00
    job_queue = app.job_queue
    if job_queue:
        from datetime import time as dt_time
        job_queue.run_daily(
            send_daily_predictions,
            time=dt_time(hour=10, minute=0),
            name="daily_predictions",
        )
        print("  ⏰ Ежедневные предсказания: 10:00")

    print("  ✅ Бот запущен! Ctrl+C для остановки.\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
