import logging
import os
import re
import threading
import requests
import json
from dataclasses import dataclass, field
from typing import Dict, Optional

import telebot
from telebot import types
import gspread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_USERNAME = ADMIN_USERNAME.lstrip("@").lower()
YANDEX_AI_KEY = os.getenv("YANDEX_AI_KEY")
FOLDER_ID = "b1g19u79p3t7cr7rv14v"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
CLINIC_PHONE = "+74951234567"

if not BOT_TOKEN or not YANDEX_AI_KEY:
    raise RuntimeError("Missing BOT_TOKEN or YANDEX_AI_KEY")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# === Google Sheets ===
sheets_worksheet = None

def init_sheets():
    global sheets_worksheet
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS:
        logger.warning("Google Sheets не настроен")
        return
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        sheets_worksheet = sh.sheet1
        logger.info("Google Sheets подключен")
    except Exception as e:
        logger.error("Ошибка Sheets: " + str(e))

def save_to_sheet(data):
    if not sheets_worksheet:
        return False
    try:
        row = [
            data.get("datetime", ""),
            data.get("name", ""),
            data.get("phone", ""),
            data.get("time", ""),
            data.get("program", ""),
            data.get("price", ""),
            data.get("goal", ""),
            data.get("experience", "")
        ]
        sheets_worksheet.append_row(row)
        logger.info("Заявка сохранена в Sheets")
        return True
    except Exception as e:
        logger.error("Ошибка записи: " + str(e))
        return False

init_sheets()

PROGRAMS = {
    "vitamin": {"name": "Витаминный заряд", "price": 4500, "reason": "Базовая поддержка тонуса", "time": "45-60 мин", "prep": "Можно есть за 2 часа до процедуры."},
    "tad": {"name": "Антиоксидант TAD 600", "price": 7500, "reason": "Мощная детоксикация", "time": "60-90 мин", "prep": "Пить больше воды за день до процедуры."},
    "cinderella": {"name": "Золушка+ с Лаеннеком", "price": 15000, "reason": "Премиум уход и anti-age", "time": "90+ мин", "prep": "Не пить алкоголь за 24 часа."},
    "sport": {"name": "Спортивное восстановление", "price": 7500, "reason": "Восполнение электролитов", "time": "60-90 мин", "prep": "Лучше сразу после тренировки."},
    "nad": {"name": "NAD+ Молекула молодости", "price": 18000, "reason": "Клеточная энергия", "time": "90+ мин", "prep": "Лёгкий завтрак за 2 часа до процедуры."}
}

ARTICLES = {
    "article_1": {"title": "Хроническая усталость", "text": "Чувствуете усталость даже после выходных? Обычные витамины усваиваются лишь на 20%. Инфузионная терапия доставляет нутриенты сразу в кровь.\n\nПрограмма «Витаминный заряд» — витамины группы B, магний, витамин C.", "program": "vitamin"},
    "article_2": {"title": "Детокс и очищение", "text": "Тяжесть в боку, тусклая кожа, отеки? Глутатион — мощнейший антиоксидант. С возрастом его уровень падает.\n\n«Антиоксидант TAD 600» — итальянский глутатион. Результат: чистая кожа, лёгкость.", "program": "tad"},
    "article_3": {"title": "Красота изнутри", "text": "Кремы работают только на поверхности. Лаеннек — японский препарат на основе плаценты. Активирует регенерацию клеток.\n\n«Золушка+» — Лаеннек + витамины + антиоксиданты.", "program": "cinderella"}
}

CLINIC_INFO = (
    "Клиника Доктор Хартманн\n"
    "Адрес: Москва, СВАО, ул. Аргуновская 3к1\n"
    "Метро: ВДНХ, Алексеевская\n"
    f"Телефон: {CLINIC_PHONE}\n"
    "Время работы: Пн-Пт 9:00-21:00, Сб-Вс 10:00-18:00\n\n"
    "Услуги: Инфузионная терапия, Косметология, Гинекология, Кардиология, Массаж, Ортопедия, УЗИ."
)

def ask_ai(question):
    try:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {"Authorization": "Api-Key " + YANDEX_AI_KEY, "Content-Type": "application/json"}
        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-5-lite",
            "completionOptions": {"stream": False, "maxTokens": "500", "temperature": 0.3},
            "messages": [
                {"role": "system", "text": f"Ты администратор клиники Доктор Хартманн. Отвечай кратко. Инфо: {CLINIC_INFO}. Не по теме - предложи написать @silentaltai"},
                {"role": "user", "text": question}
            ]
        }
        r = requests.post(url, headers=headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]
    except Exception as e:
        logger.error("AI error: " + str(e))
        return "Извините, сейчас не могу ответить. Напишите: @silentaltai"

def validate_phone(phone):
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits[0] in ['7', '8']:
        return "+" + digits
    if len(digits) == 10:
        return "+7" + digits
    return None

@dataclass
class Session:
    quiz_step: Optional[str] = None
    answers: Dict[str, str] = field(default_factory=dict)
    last_rec: str = ""
    book_step: int = 0
    book_data: Dict[str, str] = field(default_factory=dict)
    ai_mode: bool = False

sessions: Dict[int, Session] = {}
lock = threading.Lock()
admin_id: Optional[int] = None

def get_session(uid):
    with lock:
        if uid not in sessions:
            sessions[uid] = Session()
        return sessions[uid]

def reset_session(uid):
    with lock:
        sessions[uid] = Session()

QUIZ_STEPS = ["goal", "experience"]
QUIZ_QUESTIONS = {
    "goal": "Какой результат хотите получить?",
    "experience": "Проходили ли ранее капельницы?"
}
QUIZ_OPTIONS = {
    "goal": [
        ("Энергия и тонус", "energy"),
        ("Детокс и очищение", "detox"),
        ("Красота и Anti-age", "beauty"),
        ("Иммунитет", "immunity"),
        ("Восстановление", "sport")
    ],
    "experience": [
        ("Это мой первый раз", "first"),
        ("Проходил(а) 1-2 раза", "once"),
        ("Прохожу регулярно", "regular")
    ]
}

# ЧАСЫ РАБОТЫ (разбиты на строки по 4 кнопки)
HOURS = [
    ["09:00", "10:00", "11:00", "12:00"],
    ["13:00", "14:00", "15:00", "16:00"],
    ["17:00", "18:00", "19:00", "20:00"],
    ["21:00"]
]

def get_recommendation(session):
    goal = session.answers.get("goal")
    exp = session.answers.get("experience")
    if goal == "beauty":
        return "cinderella"
    if goal == "sport":
        return "sport"
    if goal == "energy" and exp == "regular":
        return "nad"
    if goal in ["detox", "immunity"] and exp != "first":
        return "tad"
    return "vitamin"

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💉 Подобрать капельницу", callback_data="quiz"),
        types.InlineKeyboardButton("📝 Записаться", callback_data="book"),
        types.InlineKeyboardButton("📚 Полезные материалы", callback_data="articles"),
        types.InlineKeyboardButton("🤖 Вопрос администратору", callback_data="ai"),
        types.InlineKeyboardButton("📞 Связь с админом", callback_data="contact")
    )
    return markup

@bot.message_handler(commands=["start"])
def cmd_start(message):
    global admin_id
    user = message.from_user
    if ADMIN_USERNAME and user.username and user.username.lower() == ADMIN_USERNAME:
        admin_id = message.chat.id
        logger.info("Admin ID: " + str(admin_id))
    reset_session(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "Добро пожаловать в клинику Доктор Хартманн!\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )

@bot.callback_query_handler(func=lambda call: call.data == "articles")
def show_articles(call):
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⚡ Хроническая усталость", callback_data="article_1"),
        types.InlineKeyboardButton("🌿 Детокс и очищение", callback_data="article_2"),
        types.InlineKeyboardButton("✨ Красота изнутри", callback_data="article_3"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )
    bot.send_message(
        call.message.chat.id,
        "📚 <b>Полезные материалы</b>\n\nУзнайте больше о программах:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("article_"))
def show_article(call):
    article = ARTICLES.get(call.data)
    if not article:
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(" Записаться", callback_data="book_from_article_" + article["program"]),
        types.InlineKeyboardButton("📚 Все статьи", callback_data="articles"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )
    bot.send_message(
        call.message.chat.id,
        f"📖 <b>{article['title']}</b>\n\n{article['text']}",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("book_from_article_"))
def book_from_article(call):
    program_id = call.data.replace("book_from_article_", "")
    session = get_session(call.from_user.id)
    session.last_rec = program_id
    session.book_step = 1
    session.book_data = {}
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    prog = PROGRAMS.get(program_id, {})
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    bot.send_message(
        call.message.chat.id,
        f"📝 <b>Запись</b>\n\nПрограмма: <b>{prog.get('name', '')}</b>\n\n<b>Шаг 1 из 4:</b>\nКак к вам обращаться?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "quiz")
def start_quiz(call):
    session = get_session(call.from_user.id)
    session.quiz_step = "goal"
    session.answers = {}
    session.last_rec = ""
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    send_quiz_question(call.message.chat.id, "goal", 1)

def send_quiz_question(cid, step_key, num):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for text, value in QUIZ_OPTIONS[step_key]:
        markup.add(types.InlineKeyboardButton(text, callback_data=f"q_{step_key}_{value}"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    bot.send_message(cid, f"Шаг {num} из 2\n\n{QUIZ_QUESTIONS[step_key]}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def handle_quiz_answer(call):
    parts = call.data.split("_", 2)
    if len(parts) != 3:
        return
    _, step_key, value = parts
    session = get_session(call.from_user.id)
    if session.quiz_step != step_key:
        bot.answer_callback_query(call.id)
        return
    session.answers[step_key] = value
    bot.answer_callback_query(call.id)
    idx = QUIZ_STEPS.index(step_key)
    if idx < len(QUIZ_STEPS) - 1:
        session.quiz_step = QUIZ_STEPS[idx + 1]
        send_quiz_question(call.message.chat.id, session.quiz_step, idx + 2)
    else:
        session.quiz_step = None
        bot.edit_message_text("Анализирую...", call.message.chat.id, call.message.message_id)
        show_recommendation(call.message.chat.id, session)

def show_recommendation(cid, session):
    rec_key = get_recommendation(session)
    session.last_rec = rec_key
    prog = PROGRAMS[rec_key]
    price = int(prog["price"] * 0.95)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📝 Записаться", callback_data="book"),
        types.InlineKeyboardButton("🔄 Другую программу", callback_data="quiz"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )
    bot.send_message(
        cid,
        f"✨ Рекомендация:\n\n🧪 <b>{prog['name']}</b>\n\n {prog['reason']}\n⏱ Время: {prog['time']}\n📋 Подготовка: {prog['prep']}\n\n💰 Стоимость: <b>{price} руб</b>\n(скидка 5% через бота)",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "ai")
def ai_menu(call):
    session = get_session(call.from_user.id)
    session.ai_mode = True
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    bot.send_message(
        call.message.chat.id,
        "🤖 <b>Виртуальный администратор</b>\n\nЗадайте вопрос:\n Как добраться?\n💰 Цены?\n Время работы?\n\nНапишите вопрос ниже ",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "contact")
def contact_admin(call):
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
    bot.send_message(
        call.message.chat.id,
        f" <b>Связь с администратором</b>\n\nTelegram: @silentaltai\n\nТелефон: <a href='tel:{CLINIC_PHONE}'>{CLINIC_PHONE}</a>\n<i>(Нажмите на номер выше, чтобы позвонить)</i>",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def show_main_menu(call):
    session = get_session(call.from_user.id)
    session.ai_mode = False
    session.quiz_step = None
    session.book_step = 0
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Добро пожаловать в клинику Доктор Хартманн!\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_action(call):
    session = get_session(call.from_user.id)
    session.quiz_step = None
    session.book_step = 0
    session.ai_mode = False
    session.book_data = {}
    bot.answer_callback_query(call.id, "Отменено")
    bot.send_message(
        call.message.chat.id,
        "❌ Отменено.\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )

@bot.message_handler(
    func=lambda msg: (
        get_session(msg.from_user.id).book_step == 0
        and get_session(msg.from_user.id).quiz_step is None
        and get_session(msg.from_user.id).ai_mode
        and not msg.text.startswith("/")
    )
)
def handle_ai_question(message):
    session = get_session(message.from_user.id)
    bot.send_chat_action(message.chat.id, "typing")
    bot.send_message(message.chat.id, ask_ai(message.text))
    session.ai_mode = False
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("❓ Ещё вопрос", callback_data="ai"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )
    bot.send_message(message.chat.id, "Что дальше?", reply_markup=markup)

# === ЗАПИСЬ: ШАГ 1 (Имя) ===
@bot.callback_query_handler(func=lambda call: call.data == "book")
def start_booking(call):
    session = get_session(call.from_user.id)
    session.book_step = 1
    session.book_data = {}
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    bot.send_message(
        call.message.chat.id,
        "📝 <b>Запись на процедуру</b>\n\n<b>Шаг 1 из 4:</b>\nКак к вам обращаться?",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: get_session(msg.from_user.id).book_step == 1)
def handle_name(message):
    session = get_session(message.from_user.id)
    session.book_data["name"] = message.text.strip()
    session.book_step = 2
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
    bot.send_message(
        message.chat.id,
        f"Приятно познакомиться, {session.book_data['name']}!\n\n<b>Шаг 2 из 4:</b>\nВаш номер телефона:",
        reply_markup=markup
    )

# === ЗАПИСЬ: ШАГ 2 (Телефон) ===
@bot.message_handler(
    func=lambda msg: get_session(msg.from_user.id).book_step == 2,
    content_types=["contact", "text"]
)
def handle_phone(message):
    session = get_session(message.from_user.id)
    if message.contact:
        phone = str(message.contact.phone_number)
    elif message.text:
        phone = message.text.strip()
    else:
        bot.send_message(message.chat.id, " Отправьте номер телефона")
        return
    
    validated = validate_phone(phone)
    if not validated:
        bot.send_message(
            message.chat.id,
            "❌ Неверный формат телефона.\n\nНапример: +7 999 123-45-67\nПопробуйте ещё раз:"
        )
        return
    
    session.book_data["phone"] = validated
    session.book_step = 3
    bot.send_message(
        message.chat.id,
        "<b>Шаг 3 из 4:</b>\nНапишите удобную дату (например: Завтра, 15.09, Понедельник)",
        reply_markup=types.ReplyKeyboardRemove()
    )

# === ЗАПИСЬ: ШАГ 3 (Дата) ===
@bot.message_handler(func=lambda msg: get_session(msg.from_user.id).book_step == 3)
def handle_date(message):
    session = get_session(message.from_user.id)
    session.book_data["date"] = message.text.strip()
    session.book_step = 4
    
    # Создаем сетку кнопок времени (по 4 в строке)
    markup = types.InlineKeyboardMarkup(row_width=4)
    for row in HOURS:
        buttons = [types.InlineKeyboardButton(t, callback_data=f"time_{t}") for t in row]
        markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    
    bot.send_message(
        message.chat.id,
        "<b>Шаг 4 из 4:</b>\nВыберите точное время:",
        reply_markup=markup
    )

# === ЗАПИСЬ: ШАГ 4 (Время) ===
@bot.callback_query_handler(func=lambda call: call.data.startswith("time_"))
def handle_time_selection(call):
    time_val = call.data.replace("time_", "")
    session = get_session(call.from_user.id)
    session.book_data["time"] = time_val
    session.book_step = 5
    bot.answer_callback_query(call.id)
    show_confirmation(call.message.chat.id, session)

# === ЗАПИСЬ: ШАГ 5 (Подтверждение) ===
def show_confirmation(cid, session):
    prog = PROGRAMS.get(session.last_rec, {})
    price = int(prog.get("price", 0) * 0.95)
    text = (
        "✅ <b>Подтвердите данные:</b>\n\n"
        f"👤 Имя: {session.book_data.get('name', '')}\n"
        f" Телефон: {session.book_data.get('phone', '')}\n"
        f"📅 Дата: {session.book_data.get('date', '')}\n"
        f"⏰ Время: {session.book_data.get('time', '')}\n"
        f"💉 Программа: {prog.get('name', 'не указана')}\n"
        f" Цена: {price} руб\n\nВсё верно?"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_booking"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
    bot.send_message(cid, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_booking")
def confirm_booking(call):
    session = get_session(call.from_user.id)
    session.book_step = 0
    prog = PROGRAMS.get(session.last_rec, {})
    price = int(prog.get("price", 0) * 0.95)
    
    sheet_data = {
        "datetime": f"{session.book_data.get('date', '')} {session.book_data.get('time', '')}",
        "name": session.book_data.get("name", ""),
        "phone": session.book_data.get("phone", ""),
        "time": session.book_data.get("time", ""),
        "program": prog.get("name", ""),
        "price": str(price),
        "goal": session.answers.get("goal", ""),
        "experience": session.answers.get("experience", "")
    }
    saved = save_to_sheet(sheet_data)
    
    if admin_id:
        report = (
            f" НОВАЯ ЗАЯВКА\n\n"
            f"👤 Имя: {session.book_data.get('name', '')}\n"
            f"📞 Телефон: {session.book_data.get('phone', '')}\n"
            f" Дата: {session.book_data.get('date', '')}\n"
            f"⏰ Время: {session.book_data.get('time', '')}\n\n"
            f"💉 Программа: {prog.get('name', 'не указана')}\n"
            f"💰 Цена: {price} руб\n\n"
            f"🎯 Цель: {session.answers.get('goal', '?')}\n"
            f"📊 Опыт: {session.answers.get('experience', '?')}"
        )
        if saved:
            report += "\n\n✅ Сохранено в Google Sheets"
        bot.send_message(admin_id, report)
    
    text = (
        "✅ <b>Заявка принята!</b>\n\n"
        "Администратор свяжется с вами в течение 15 минут.\n\n"
        "📋 <b>Памятка перед визитом:</b>\n"
        "1. Выпейте стакан воды за час до визита\n"
        "2. Возьмите тёплые носки\n"
        f"3. {prog.get('prep', 'Специальной подготовки не требуется')}\n\n"
        " <b>Адрес:</b>\nМосква, ул. Аргуновская 3к1 (м. ВДНХ, Алексеевская)\n\n"
        f"🗺 <a href='https://yandex.ru/maps/?text=Москва, ул. Аргуновская 3к1'>Открыть на Яндекс.Картах</a>\n\n"
        f"📞 <a href='tel:{CLINIC_PHONE}'>Позвонить: {CLINIC_PHONE}</a>"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=markup,
        disable_web_page_preview=False
    )

if __name__ == "__main__":
    logger.info("Bot v2.1 started (Hourly booking)")
    bot.infinity_polling(skip_pending=True)