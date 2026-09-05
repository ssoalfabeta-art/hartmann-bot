import logging
import os
import threading
import requests
from dataclasses import dataclass, field
from typing import Dict, Optional

import telebot
from telebot import types

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

if not BOT_TOKEN or not YANDEX_AI_KEY:
    raise RuntimeError("Missing BOT_TOKEN or YANDEX_AI_KEY")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

PROGRAMS = {
    "vitamin": {
        "name": "Витаминный заряд",
        "price": 4500,
        "reason": "Базовая поддержка тонуса и иммунитета",
        "time": "45-60 минут",
        "prep": "Не требуется. Можно есть за 2 часа до процедуры."
    },
    "tad": {
        "name": "Антиоксидант TAD 600",
        "price": 7500,
        "reason": "Мощная детоксикация и защита печени",
        "time": "60-90 минут",
        "prep": "Пить больше воды за день до процедуры."
    },
    "cinderella": {
        "name": "Золушка+ с Лаеннеком",
        "price": 15000,
        "reason": "Премиум уход за кожей и anti-age",
        "time": "90+ минут",
        "prep": "Не пить алкоголь за 24 часа до процедуры."
    },
    "sport": {
        "name": "Спортивное восстановление",
        "price": 7500,
        "reason": "Восполнение электролитов после нагрузок",
        "time": "60-90 минут",
        "prep": "Лучше сразу после тренировки."
    },
    "nad": {
        "name": "NAD+ Молекула молодости",
        "price": 18000,
        "reason": "Клеточная энергия и омоложение",
        "time": "90+ минут",
        "prep": "Лёгкий завтрак за 2 часа до процедуры."
    }
}

CLINIC_INFO = (
    "Клиника Доктор Хартманн\n"
    "Адрес: Москва, СВАО, ул. Аргуновская 3к1\n"
    "Метро: ВДНХ, Алексеевская\n"
    "Время работы:\n"
    "Пн-Пт: 9:00-20:00\n"
    "Сб-Вс: 10:00-18:00\n\n"
    "Услуги:\n"
    "- Инфузионная терапия\n"
    "- Косметология\n"
    "- Гинекология\n"
    "- Кардиология\n"
    "- Массаж\n"
    "- Ортопедия Formthotics\n"
    "- УЗИ\n\n"
    "Программы:\n"
    "- Витаминный заряд: 4500р\n"
    "- TAD 600: 7500р\n"
    "- Золушка+: 15000р\n"
    "- Спорт: 7500р\n"
    "- NAD+: 18000р\n\n"
    "Скидка 5% при записи через бота"
)

def ask_ai(question):
    try:
        url = (
            "https://llm.api.cloud.yandex.net"
            "/foundationModels/v1/completion"
        )
        headers = {
            "Authorization": "Api-Key " + YANDEX_AI_KEY,
            "Content-Type": "application/json"
        }
        system_prompt = (
            "Ты виртуальный администратор "
            "клиники Доктор Хартманн. "
            "Отвечай кратко и дружелюбно. "
            "Используй информацию: " + CLINIC_INFO +
            ". Если вопрос не по теме клиники - "
            "вежливо скажи что не можешь помочь "
            "и предложи написать @silentaltai"
        )
        data = {
            "modelUri": (
                "gpt://" + FOLDER_ID +
                "/yandexgpt-5-lite"
            ),
            "completionOptions": {
                "stream": False,
                "maxTokens": "500",
                "temperature": 0.3
            },
            "messages": [
                {
                    "role": "system",
                    "text": system_prompt
                },
                {
                    "role": "user",
                    "text": question
                }
            ]
        }
        r = requests.post(
            url, headers=headers,
            json=data, timeout=15
        )
        r.raise_for_status()
        res = r.json()
        return res["result"][
            "alternatives"
        ][0]["message"]["text"]
    except Exception as e:
        logger.error("AI error: " + str(e))
        return (
            "Извините, сейчас не могу ответить. "
            "Напишите администратору: @silentaltai"
        )

@dataclass
class Session:
    quiz_step: Optional[str] = None
    answers: Dict[str, str] = field(
        default_factory=dict
    )
    last_rec: str = ""
    book_step: int = 0
    book_data: Dict[str, str] = field(
        default_factory=dict
    )
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
    "goal": (
        "Какой результат вы хотите "
        "получить от процедуры?"
    ),
    "experience": (
        "Проходили ли вы ранее "
        "инфузионную терапию?"
    )
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

def get_recommendation(session):
    goal = session.answers.get("goal")
    exp = session.answers.get("experience")
    if goal == "beauty":
        return "cinderella"
    if goal == "sport":
        return "sport"
    if goal == "energy" and exp == "regular":
        return "nad"
    if goal in ["detox", "immunity"]:
        if exp != "first":
            return "tad"
    return "vitamin"

def get_main_menu():
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "💉 Подобрать капельницу",
            callback_data="quiz"
        ),
        types.InlineKeyboardButton(
            "📝 Записаться на процедуру",
            callback_data="book"
        ),
        types.InlineKeyboardButton(
            "🤖 Вопрос администратору",
            callback_data="ai"
        ),
        types.InlineKeyboardButton(
            "📞 Связь с админом",
            callback_data="contact"
        )
    )
    return markup

def get_cancel_button():
    markup = types.InlineKeyboardMarkup(
        row_width=2
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel"
        )
    )
    return markup

@bot.message_handler(commands=["start"])
def cmd_start(message):
    global admin_id
    user = message.from_user
    if ADMIN_USERNAME and user.username:
        if user.username.lower() == ADMIN_USERNAME:
            admin_id = message.chat.id
            logger.info("Admin ID: " + str(admin_id))
    reset_session(message.from_user.id)
    welcome = (
        "Добро пожаловать в клинику "
        "Доктор Хартманн!\n\n"
        "Я помогу подобрать программу, "
        "ответить на вопросы или "
        "записать вас на процедуру.\n\n"
        "Выберите действие:"
    )
    bot.send_message(
        message.chat.id,
        welcome,
        reply_markup=get_main_menu()
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "quiz"
)
def start_quiz(call):
    session = get_session(call.from_user.id)
    session.quiz_step = "goal"
    session.answers = {}
    session.last_rec = ""
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    send_quiz_question(
        call.message.chat.id, "goal", 1
    )

def send_quiz_question(cid, step_key, num):
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    for text, value in QUIZ_OPTIONS[step_key]:
        markup.add(
            types.InlineKeyboardButton(
                text,
                callback_data=(
                    "q_" + step_key + "_" + value
                )
            )
        )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel"
        )
    )
    question = (
        "Шаг " + str(num) + " из 2\n\n" +
        QUIZ_QUESTIONS[step_key]
    )
    bot.send_message(
        cid, question, reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("q_")
)
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
        next_step = QUIZ_STEPS[idx + 1]
        session.quiz_step = next_step
        send_quiz_question(
            call.message.chat.id,
            next_step,
            idx + 2
        )
    else:
        session.quiz_step = None
        bot.edit_message_text(
            "Анализирую ваши ответы...",
            call.message.chat.id,
            call.message.message_id
        )
        show_recommendation(
            call.message.chat.id, session
        )

def show_recommendation(cid, session):
    rec_key = get_recommendation(session)
    session.last_rec = rec_key
    prog = PROGRAMS[rec_key]
    price = int(prog["price"] * 0.95)
    text = (
        "✨ Рекомендация:\n\n"
        "🧪 <b>" + prog["name"] + "</b>\n\n"
        "💡 " + prog["reason"] + "\n"
        "⏱ Время: " + prog["time"] + "\n"
        "📋 Подготовка: " + prog["prep"] + "\n\n"
        "💰 Стоимость: <b>" + str(price) +
        " руб</b>\n"
        "(скидка 5% при записи через бота)"
    )
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "📝 Записаться",
            callback_data="book"
        ),
        types.InlineKeyboardButton(
            " Подобрать другую",
            callback_data="quiz"
        ),
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="main_menu"
        )
    )
    bot.send_message(
        cid, text, reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "ai"
)
def ai_menu(call):
    session = get_session(call.from_user.id)
    session.ai_mode = True
    bot.answer_callback_query(call.id)
    text = (
        " <b>Виртуальный администратор</b>\n\n"
        "Задайте любой вопрос о клинике:\n\n"
        "📍 Как добраться?\n"
        "💰 Сколько стоит процедура?\n"
        "⏰ Время работы?\n"
        " Какие услуги есть?\n\n"
        "Напишите ваш вопрос ниже 👇"
    )
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel"
        )
    )
    bot.send_message(
        call.message.chat.id, text,
        reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "contact"
)
def contact_admin(call):
    bot.answer_callback_query(call.id)
    text = (
        "📞 <b>Связь с администратором</b>\n\n"
        "Напишите напрямую:\n"
        "@silentaltai\n\n"
        "Или позвоните:\n"
        "+7 (XXX) XXX-XX-XX"
    )
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="main_menu"
        )
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "main_menu"
)
def show_main_menu(call):
    session = get_session(call.from_user.id)
    session.ai_mode = False
    session.quiz_step = None
    session.book_step = 0
    bot.answer_callback_query(call.id)
    text = (
        "Добро пожаловать в клинику "
        "Доктор Хартманн!\n\n"
        "Выберите действие:"
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=get_main_menu()
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "cancel"
)
def cancel_action(call):
    session = get_session(call.from_user.id)
    session.quiz_step = None
    session.book_step = 0
    session.ai_mode = False
    bot.answer_callback_query(call.id, "Отменено")
    text = (
        " Действие отменено.\n\n"
        "Выберите действие:"
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=get_main_menu()
    )

@bot.message_handler(
    func=lambda msg: (
        get_session(msg.from_user.id).book_step == 0
        and get_session(
            msg.from_user.id
        ).quiz_step is None
        and get_session(
            msg.from_user.id
        ).ai_mode is True
        and not msg.text.startswith("/")
    )
)
def handle_ai_question(message):
    session = get_session(message.from_user.id)
    bot.send_chat_action(
        message.chat.id, "typing"
    )
    answer = ask_ai(message.text)
    bot.send_message(message.chat.id, answer)
    session.ai_mode = False
    markup = types.InlineKeyboardMarkup(
        row_width=2
    )
    markup.add(
        types.InlineKeyboardButton(
            "❓ Задать ещё вопрос",
            callback_data="ai"
        ),
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="main_menu"
        )
    )
    bot.send_message(
        message.chat.id,
        "Что хотите сделать дальше?",
        reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "book"
)
def start_booking(call):
    session = get_session(call.from_user.id)
    session.book_step = 1
    session.book_data = {}
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    text = (
        "📝 <b>Запись на процедуру</b>\n\n"
        "<b>Шаг 1 из 3:</b>\n"
        "Как к вам обращаться?"
    )
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel"
        )
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(
    func=lambda msg: (
        get_session(msg.from_user.id).book_step == 1
    )
)
def handle_name(message):
    session = get_session(message.from_user.id)
    session.book_data["name"] = message.text.strip()
    session.book_step = 2
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True
    )
    markup.add(
        types.KeyboardButton(
            "📱 Поделиться контактом",
            request_contact=True
        )
    )
    text = (
        "Приятно познакомиться, " +
        session.book_data["name"] + "!\n\n"
        "<b>Шаг 2 из 3:</b>\n"
        "Ваш номер телефона:"
    )
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup
    )

@bot.message_handler(
    func=lambda msg: (
        get_session(msg.from_user.id).book_step == 2
    ),
    content_types=["contact", "text"]
)
def handle_phone(message):
    session = get_session(message.from_user.id)
    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = message.text.strip()
    else:
        bot.send_message(
            message.chat.id,
            "Отправьте номер телефона"
        )
        return
    session.book_data["phone"] = phone
    session.book_step = 3
    text = (
        "<b>Шаг 3 из 3:</b>\n"
        "Удобная дата и время\n"
        "(например: Завтра после 18:00)"
    )
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(
    func=lambda msg: (
        get_session(msg.from_user.id).book_step == 3
    )
)
def handle_datetime(message):
    session = get_session(message.from_user.id)
    session.book_data["time"] = message.text.strip()
    
    prog = PROGRAMS.get(session.last_rec, {})
    price = int(prog.get("price", 0) * 0.95)
    
    text = (
        "✅ <b>Подтвердите данные:</b>\n\n"
        "👤 Имя: " + session.book_data["name"] + "\n"
        " Телефон: " + session.book_data["phone"] + "\n"
        "📅 Время: " + session.book_data["time"] + "\n"
        "💉 Программа: " + prog.get("name", "не указана") + "\n"
        "💰 Цена: " + str(price) + " руб\n\n"
        "Всё верно?"
    )
    
    markup = types.InlineKeyboardMarkup(
        row_width=2
    )
    markup.add(
        types.InlineKeyboardButton(
            "✅ Подтвердить",
            callback_data="confirm_booking"
        ),
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel"
        )
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup
    )

@bot.callback_query_handler(
    func=lambda call: call.data == "confirm_booking"
)
def confirm_booking(call):
    session = get_session(call.from_user.id)
    session.book_step = 0
    
    if admin_id:
        prog = PROGRAMS.get(session.last_rec, {})
        price = int(prog.get("price", 0) * 0.95)
        report = (
            " НОВАЯ ЗАЯВКА\n\n"
            "👤 Имя: " +
            session.book_data["name"] + "\n"
            "📞 Телефон: " +
            session.book_data["phone"] + "\n"
            "📅 Время: " +
            session.book_data["time"] + "\n\n"
            "💉 Программа: " +
            prog.get("name", "не указана") + "\n"
            "💰 Цена: " + str(price) + " руб\n\n"
            "🎯 Цель: " +
            session.answers.get("goal", "?") + "\n"
            "📊 Опыт: " +
            session.answers.get("experience", "?")
        )
        bot.send_message(admin_id, report)
    
    text = (
        "✅ <b>Заявка принята!</b>\n\n"
        "Администратор свяжется с вами "
        "в течение 15 минут для подтверждения."
    )
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )
    markup.add(
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="main_menu"
        )
    )
    bot.send_message(
        call.message.chat.id,
        text,
        reply_markup=markup
    )

if __name__ == "__main__":
    logger.info("Bot started with cancel buttons and confirmation")
    bot.infinity_polling(skip_pending=True)