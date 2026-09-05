import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

import requests
import telebot
from telebot import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME", "") or "").lstrip("@").lower()
YANDEX_AI_KEY = os.getenv("YANDEX_AI_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "b1g19u79p3t7cr7rv14v")

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

PROGRAMS = {
    "vitamin": {
        "name": "Витаминный заряд",
        "price": 4500,
        "reason": "Базовая поддержка тонуса и иммунитета",
        "time": "45-60 минут",
    },
    "tad": {
        "name": "Антиоксидант TAD 600",
        "price": 7500,
        "reason": "Мощная детоксикация и защита печени",
        "time": "60-90 минут",
    },
    "cinderella": {
        "name": "Золушка+ с Лаеннеком",
        "price": 15000,
        "reason": "Премиум уход за кожей и anti-age",
        "time": "90+ минут",
    },
    "sport": {
        "name": "Спортивное восстановление",
        "price": 7500,
        "reason": "Восполнение электролитов после нагрузок",
        "time": "60-90 минут",
    },
    "nad": {
        "name": "NAD+ Молекула молодости",
        "price": 18000,
        "reason": "Клеточная энергия и омоложение",
        "time": "90+ минут",
    },
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


def ask_ai(question: str) -> str:
    """Ask the Yandex LLM a question about the clinic."""
    if not YANDEX_AI_KEY:
        return "ИИ временно недоступен. Напишите администратору: @silentaltai"

    try:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": "Api-Key " + YANDEX_AI_KEY,
            "Content-Type": "application/json",
        }
        system_prompt = (
            "Ты виртуальный администратор клиники Доктор Хартманн. "
            "Отвечай кратко и дружелюбно. Используй информацию: "
            + CLINIC_INFO
            + ". Если вопрос не по теме клиники — вежливо скажи, "
            "что не можешь помочь, и предложи написать @silentaltai"
        )

        payload = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-5-lite",
            "completionOptions": {
                "stream": False,
                "maxTokens": 500,
                "temperature": 0.3,
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": question},
            ],
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json()
        return result["result"]["alternatives"][0]["message"]["text"]
    except Exception:
        logger.exception("AI request failed")
        return "Извините, сейчас не могу ответить. Напишите администратору: @silentaltai"


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


def get_session(uid: int) -> Session:
    with lock:
        if uid not in sessions:
            sessions[uid] = Session()
        return sessions[uid]


def reset_session(uid: int) -> None:
    with lock:
        sessions[uid] = Session()


def format_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 10:
        return "+7 " + digits[-10:]
    return raw.strip()


QUIZ_STEPS = ["goal", "experience"]
QUIZ_QUESTIONS = {
    "goal": "Какой результат вы хотите получить от процедуры?",
    "experience": "Проходили ли вы ранее инфузионную терапию?",
}
QUIZ_OPTIONS = {
    "goal": [
        ("Энергия и тонус", "energy"),
        ("Детокс и очищение", "detox"),
        ("Красота и Anti-age", "beauty"),
        ("Иммунитет", "immunity"),
        ("Восстановление", "sport"),
    ],
    "experience": [
        ("Это мой первый раз", "first"),
        ("Проходил(а) 1-2 раза", "once"),
        ("Прохожу регулярно", "regular"),
    ],
}


def get_recommendation(session: Session) -> str:
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


def send_main_menu(chat_id: int) -> None:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Подобрать капельницу", callback_data="quiz"),
        types.InlineKeyboardButton("Записаться на процедуру", callback_data="book"),
        types.InlineKeyboardButton("Вопрос администратору", callback_data="ai"),
        types.InlineKeyboardButton("Связь с админом", callback_data="contact"),
    )
    welcome = (
        "Добро пожаловать в клинику Доктор Хартманн!\n\n"
        "Я помогу подобрать программу, ответить на вопросы или записать вас на процедуру.\n\n"
        "Выберите действие:"
    )
    bot.send_message(chat_id, welcome, reply_markup=markup)


@bot.message_handler(commands=["start", "menu", "help"])
def cmd_start(message):
    global admin_id
    user = message.from_user

    if ADMIN_USERNAME and user.username and user.username.lower() == ADMIN_USERNAME:
        admin_id = message.chat.id
        logger.info("Admin ID: %s", admin_id)

    reset_session(message.from_user.id)
    send_main_menu(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "quiz")
def start_quiz(call):
    session = get_session(call.from_user.id)
    session.quiz_step = "goal"
    session.answers = {}
    session.last_rec = ""
    session.ai_mode = False
    bot.answer_callback_query(call.id)
    send_quiz_question(call.message.chat.id, "goal", 1)


def send_quiz_question(cid: int, step_key: str, num: int) -> None:
    markup = types.InlineKeyboardMarkup(row_width=1)
    for text, value in QUIZ_OPTIONS[step_key]:
        markup.add(
            types.InlineKeyboardButton(text, callback_data=f"q_{step_key}_{value}")
        )

    question = f"Шаг {num} из 2\n\n{QUIZ_QUESTIONS[step_key]}"
    bot.send_message(cid, question, reply_markup=markup)


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
        next_step = QUIZ_STEPS[idx + 1]
        session.quiz_step = next_step
        send_quiz_question(call.message.chat.id, next_step, idx + 2)
        return

    session.quiz_step = None
    bot.edit_message_text(
        "Анализирую ваши ответы...",
        call.message.chat.id,
        call.message.message_id,
    )
    show_recommendation(call.message.chat.id, session)


def show_recommendation(cid: int, session: Session) -> None:
    rec_key = get_recommendation(session)
    session.last_rec = rec_key

    prog = PROGRAMS[rec_key]
    price = int(prog["price"] * 0.95)
    text = (
        f"Рекомендация:\n\n<b>{prog['name']}</b>\n\n"
        f"{prog['reason']}\n"
        f"Время: {prog['time']}\n\n"
        f"Стоимость: <b>{price} руб</b>\n"
        "(скидка 5% при записи через бота)"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Записаться", callback_data="book"),
        types.InlineKeyboardButton("Подобрать другую", callback_data="quiz"),
    )
    bot.send_message(cid, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "ai")
def ai_menu(call):
    session = get_session(call.from_user.id)
    session.ai_mode = True
    session.book_step = 0
    bot.answer_callback_query(call.id)
    text = (
        "Виртуальный администратор\n\n"
        "Задайте любой вопрос о клинике:\n\n"
        "- Как добраться?\n"
        "- Сколько стоит процедура?\n"
        "- Время работы?\n"
        "- Какие услуги есть?\n\n"
        "Напишите ваш вопрос ниже"
    )
    bot.send_message(call.message.chat.id, text)


@bot.callback_query_handler(func=lambda call: call.data == "contact")
def contact_admin(call):
    bot.answer_callback_query(call.id)
    text = (
        "Связь с администратором\n\n"
        "Напишите напрямую:\n"
        "@silentaltai\n\n"
        "Или позвоните:\n"
        "+7 (495) 123-45-67"
    )
    bot.send_message(call.message.chat.id, text)


@bot.callback_query_handler(func=lambda call: call.data == "book")
def start_booking(call):
    session = get_session(call.from_user.id)
    if not session.last_rec:
        bot.answer_callback_query(call.id, "Сначала пройдите квиз")
        return

    session.ai_mode = False
    session.book_step = 1
    session.book_data = {}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "Отлично! Давайте согласуем время.\n\n<b>Шаг 1 из 4:</b>\nКак к вам обращаться?",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.message_handler(func=lambda msg: get_session(msg.from_user.id).book_step == 1)
def handle_name(message):
    session = get_session(message.from_user.id)
    name = message.text.strip() if message.text else ""
    if len(name) < 2:
        bot.send_message(message.chat.id, "Пожалуйста, напишите корректное имя.")
        return

    session.book_data["name"] = name
    session.book_step = 2
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Поделиться контактом", request_contact=True))
    bot.send_message(
        message.chat.id,
        f"Приятно познакомиться, {name}!\n\n<b>Шаг 2 из 4:</b>\nВаш номер телефона:",
        reply_markup=markup,
    )


@bot.message_handler(func=lambda msg: get_session(msg.from_user.id).book_step == 2, content_types=["contact", "text"])
def handle_phone(message):
    session = get_session(message.from_user.id)

    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = format_phone(message.text)
    else:
        bot.send_message(message.chat.id, "Отправьте номер телефона")
        return

    if len(phone) < 5:
        bot.send_message(message.chat.id, "Пожалуйста, укажите номер телефона корректно.")
        return

    session.book_data["phone"] = phone
    session.book_step = 3
    bot.send_message(
        message.chat.id,
        "<b>Шаг 3 из 4:</b>\nУдобная дата и время\n(например: Завтра после 18:00)",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.message_handler(func=lambda msg: get_session(msg.from_user.id).book_step == 3)
def handle_datetime(message):
    session = get_session(message.from_user.id)
    date = (message.text or "").strip()
    if len(date) < 3:
        bot.send_message(message.chat.id, "Пожалуйста, укажите дату и время.")
        return

    session.book_data["date"] = date
    session.book_step = 4

    program_key = session.last_rec or "vitamin"
    program_name = PROGRAMS[program_key]["name"]
    price = int(PROGRAMS[program_key]["price"] * 0.95)

    summary = (
        "Проверьте данные записи:\n\n"
        f"<b>Программа:</b> {program_name}\n"
        f"<b>Имя:</b> {session.book_data.get('name', '-')}\n"
        f"<b>Телефон:</b> {session.book_data.get('phone', '-')}\n"
        f"<b>Дата/время:</b> {date}\n"
        f"<b>Стоимость:</b> {price} руб\n\n"
        "Подтвердить запись?"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Подтвердить", callback_data="book_confirm"),
        types.InlineKeyboardButton("Отмена", callback_data="book_cancel"),
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "book_confirm")
def confirm_booking(call):
    session = get_session(call.from_user.id)
    program_key = session.last_rec or "vitamin"
    program_name = PROGRAMS[program_key]["name"]
    session.book_step = 0

    text = (
        "Запись успешно оформлена!\n\n"
        f"<b>Программа:</b> {program_name}\n"
        f"<b>Имя:</b> {session.book_data.get('name', '-')}\n"
        f"<b>Телефон:</b> {session.book_data.get('phone', '-')}\n"
        f"<b>Дата/время:</b> {session.book_data.get('date', '-')}\n\n"
        "Наш администратор скоро свяжется с вами."
    )
    bot.answer_callback_query(call.id, "Запись подтверждена")
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

    admin_message = (
        "Новая заявка на запись:\n\n"
        f"<b>Пользователь:</b> {call.from_user.first_name} {call.from_user.last_name or ''}\n"
        f"<b>Telegram:</b> @{call.from_user.username or 'no_username'}\n"
        f"<b>Программа:</b> {program_name}\n"
        f"<b>Имя:</b> {session.book_data.get('name', '-')}\n"
        f"<b>Телефон:</b> {session.book_data.get('phone', '-')}\n"
        f"<b>Дата/время:</b> {session.book_data.get('date', '-')}"
    )
    if admin_id:
        bot.send_message(admin_id, admin_message)

    session.book_data = {}
    send_main_menu(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "book_cancel")
def cancel_booking(call):
    session = get_session(call.from_user.id)
    session.book_step = 0
    session.book_data = {}
    bot.answer_callback_query(call.id, "Запись отменена")
    bot.edit_message_text(
        "Запись отменена. Можете начать заново.",
        call.message.chat.id,
        call.message.message_id,
    )
    send_main_menu(call.message.chat.id)


@bot.message_handler(content_types=["text"])
def handle_text_message(message):
    session = get_session(message.from_user.id)

    if session.ai_mode:
        bot.send_chat_action(message.chat.id, "typing")
        answer = ask_ai(message.text)
        session.ai_mode = False
        bot.send_message(message.chat.id, answer)
        send_main_menu(message.chat.id)
        return

    if session.book_step in {1, 2, 3, 4}:
        return

    if message.text and message.text.lower() in {"/admin", "/start", "/menu", "/help"}:
        return

    if message.text and message.text.startswith("/"):
        bot.send_message(message.chat.id, "Используйте меню ниже или команду /start.")
        return

    bot.send_message(
        message.chat.id,
        "Я могу помочь подобрать программу, ответить на вопросы или записать вас на приём.\n\nНажмите /start, чтобы открыть меню.",
    )


if __name__ == "__main__":
    logger.info("Starting bot")
    bot.infinity_polling(none_stop=True, interval=0, timeout=20)
