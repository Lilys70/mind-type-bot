"""Telegram-бот «Тип мышления».

Учебный проект №4 Zerocoder, шаг 3: полное прохождение теста и форма
заявки на консультацию. Тест из 10 вопросов с кнопками ответов, баллы
считает данные/questions.py (calculate_result); в результате — тип,
описание и профессии, при ничьей — оба типа. Заявка: имя, время и формат
связи, контакт. Запись уходит в хранилище/заявки.json, детали заявки —
менеджеру на MANAGER_CHAT_ID из .env (если id не задан, детали печатаются
в консоль, бот не падает).

Запуск: python bot.py (из корня папки проекта; токен читается из .env).
Если api.telegram.org недоступен напрямую, в .env можно вписать прокси:
PROXY_URL=http://host:port или socks5://host:port — необязательная настройка.
"""

import asyncio
import html
import logging
import os
import sys
from pathlib import Path

from aiohttp import ClientConnectorError
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from данные.questions import QUESTIONS, calculate_result
from данные.types import TYPES
from хранилище.заявки import save_application

# Сетевые сбои: к Telegram напрямую и через прокси.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    ClientConnectorError,
    TelegramNetworkError,
)

# --- Тексты сообщений --------------------------------------------------------

WELCOME_TEXT = (
    "Здравствуйте! Это бот «Тип мышления».\n\n"
    "Тест из 10 вопросов покажет, какой способ решать задачи вам ближе: "
    "аналитический, гуманитарный, креативный или практический.\n\n"
    "После теста расскажу о вашем типе и подскажу, какие профессии "
    "ему подходят."
)

TEST_TEXT = (
    "Перед стартом — короткая инструкция.\n\n"
    "Вас ждут 10 вопросов, у каждого по 4 варианта ответа. Выбирайте "
    "тот, который ближе именно вам.\n\n"
    "Правильных и неправильных ответов нет: тест показывает, как вы "
    "чаще всего думаете и действуете."
)

ASK_NAME_TEXT = "Как вас зовут?"
NAME_ERROR_TEXT = (
    "Имя должно быть от 2 до 64 символов. "
    "Напишите, пожалуйста, ещё раз."
)

ASK_TIME_FORMAT_TEXT = (
    "Когда вам удобно созвониться и как удобнее общаться? "
    "(Например: завтра после 18:00, Telegram)"
)
TIME_FORMAT_ERROR_TEXT = (
    "Уточните, пожалуйста, время и формат связи: "
    "от 2 до 200 символов."
)

ASK_CONTACT_TEXT = "Оставьте ваш контакт для связи (телефон или username)"
CONTACT_ERROR_TEXT = (
    "Контакт не сохранился: нужно от 3 до 100 символов. "
    "Пришлите телефон или ник в Telegram."
)

THANKS_TEXT = "Спасибо! Мы свяжемся с вами в ближайшее время"
SAVE_ERROR_TEXT = (
    "Не удалось сохранить заявку: что-то сломалось на нашей стороне. "
    "Отправьте контакт ещё раз или напишите позже."
)

STALE_TEXT = "Эта кнопка устарела. Нажмите /start, чтобы открыть меню."


# --- Состояния ---------------------------------------------------------------
class TestStates(StatesGroup):
    """Прохождение теста: ждём ответ на текущий вопрос."""

    answering = State()


class RequestStates(StatesGroup):
    """Заявка на консультацию: имя, время и формат связи, контакт."""

    waiting_name = State()
    waiting_time_format = State()
    waiting_contact = State()


# --- Клавиатуры --------------------------------------------------------------
def menu_keyboard() -> InlineKeyboardMarkup:
    """Меню под приветствием: вход в тест."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать тест", callback_data="test"
                ),
            ],
        ]
    )


def question_keyboard(question: dict) -> InlineKeyboardMarkup:
    """Кнопки вариантов ответа: callback_data = answer:<номер варианта>."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=option["text"],
                    callback_data=f"answer:{index}",
                )
            ]
            for index, option in enumerate(question["options"])
        ]
    )


def book_keyboard(winners: list[str]) -> InlineKeyboardMarkup:
    """Кнопка «Оставить заявку» под результатом.

    В callback_data лежат ключи победивших типов: форма заявки узнает
    результат теста даже после state.clear().
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оставить заявку",
                    callback_data="book_consult:" + ":".join(winners),
                )
            ]
        ]
    )


# --- Тексты экранов ----------------------------------------------------------
def question_text(index: int, question: dict) -> str:
    """Экран вопроса: счётчик «Вопрос N из 10» и сам вопрос."""
    return (
        f"<b>Вопрос {index + 1} из {len(QUESTIONS)}</b>\n\n"
        f"{question['text']}"
    )


def format_result(result: dict) -> str:
    """Итоговый экран: тип, описание и профессии.

    При ничьей показываем оба типа с одинаковым максимумом баллов.
    """
    primary = result["primary"]
    if not result["is_tie"]:
        return (
            f"<b>Ваш тип мышления — {primary['title']}</b>\n\n"
            f"{primary['description']}\n\n"
            f"<b>Подходящие профессии</b>\n{primary['professions']}"
        )

    secondary = result["secondary"]
    return (
        f"<b>Вы между «{primary['title']}» и «{secondary['title']}»</b>\n\n"
        "Баллы разделились поровну, поэтому вам подходят оба типа.\n\n"
        f"<b>{primary['title']}</b>\n{primary['description']}\n"
        f"<b>Профессии:</b> {primary['professions']}\n\n"
        f"<b>{secondary['title']}</b>\n{secondary['description']}\n"
        f"<b>Профессии:</b> {secondary['professions']}"
    )


def result_title_from_keys(keys: list[str]) -> str:
    """Название результата для заявки.

    «Аналитический» при одном победителе, при ничьей —
    «Аналитический и Гуманитарный».
    """
    titles = [TYPES[key]["title"] for key in keys]
    return " и ".join(titles)


# --- Вспомогательные функции -------------------------------------------------
async def safe_delete(message: Message) -> None:
    """Удаляет сообщение и не падает, если оно уже удалено.

    В чате должно оставаться одно актуальное сообщение с кнопками:
    иначе пользователь нажимает кнопку со старого экрана, а бот
    реагирует неожиданно.
    """
    try:
        await message.delete()
    except TelegramBadRequest:
        # Сообщение старше 48 часов или уже удалено — это не ошибка.
        pass


# --- Обработчики -------------------------------------------------------------
async def on_start(message: Message, state: FSMContext) -> None:
    """Приветствие и меню; /start сбрасывает незаконченный тест."""
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=menu_keyboard())


async def on_reset(message: Message, state: FSMContext) -> None:
    """Сброс диалога: чистим состояние и показываем меню заново."""
    await state.clear()
    await message.answer(
        "Состояние сброшено.\n\n" + WELCOME_TEXT,
        reply_markup=menu_keyboard(),
    )


async def exit_form_on_command(
    message: Message, state: FSMContext
) -> bool:
    """True, если вместо данных пришла команда: форму прерываем.

    Проверка стоит первой строкой в каждом шаге заявки. Имя, время
    и контакт — свободный текст, поэтому без проверки «/start» мог бы
    уйти в поле имени. Команда важнее формы: состояние сбрасывается,
    пользователь возвращается в начало.
    """
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return False

    await on_start(message, state)
    return True


async def on_test(callback: CallbackQuery, state: FSMContext) -> None:
    """«Начать тест»: инструкция, затем первый вопрос."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    await state.set_state(TestStates.answering)
    await state.set_data({"index": 0, "answers": [], "message_id": None})
    await safe_delete(callback.message)
    await callback.message.answer(TEST_TEXT)
    await send_question(callback.message, state)
    await callback.answer()


async def send_question(message: Message, state: FSMContext) -> None:
    """Отправляет текущий вопрос и запоминает id сообщения с кнопками."""
    data = await state.get_data()
    index = data.get("index", 0)
    question = QUESTIONS[index]
    sent = await message.answer(
        question_text(index, question),
        reply_markup=question_keyboard(question),
    )
    # id нужен, чтобы отличить кнопки актуального вопроса от старых.
    await state.update_data(message_id=sent.message_id)


async def on_answer(callback: CallbackQuery, state: FSMContext) -> None:
    """Ответ на вопрос: следующий вопрос или итог теста."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    data = await state.get_data()
    # Кнопка со старого экрана: её id уже не совпадает с текущим.
    if callback.message.message_id != data.get("message_id"):
        await callback.answer(STALE_TEXT, show_alert=True)
        return

    index = data.get("index", 0)
    answers = list(data.get("answers") or [])
    options = QUESTIONS[index]["options"]

    try:
        variant = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Не поняла ответ, выберите вариант заново")
        return

    if not 0 <= variant < len(options):
        await callback.answer("Такого варианта нет, выберите заново")
        return

    # Веса копируем: словарь вопросов общий для всех пользователей.
    # Формат как в calculate_result: {"scores": {"analytical": 1}}.
    answers.append({"scores": dict(options[variant]["scores"])})
    next_index = index + 1

    await callback.answer()
    await safe_delete(callback.message)

    if next_index < len(QUESTIONS):
        await state.update_data(
            index=next_index,
            answers=answers,
            message_id=None,
        )
        await send_question(callback.message, state)
        return

    result = calculate_result(answers)
    winners = [
        type_id
        for type_id, score in result["scores"].items()
        if score == result["max_score"]
    ]
    # Тест закончен: состояние чистим полностью, результат уходит
    # в callback_data кнопки «Оставить заявку».
    await state.clear()
    await callback.message.answer(
        format_result(result),
        reply_markup=book_keyboard(winners),
    )


# --- Заявка на консультацию --------------------------------------------------
async def on_book_consult(callback: CallbackQuery, state: FSMContext) -> None:
    """«Оставить заявку» под результатом: начинаем форму с имени."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    keys = callback.data.split(":")[1:]
    if not keys or any(key not in TYPES for key in keys):
        await callback.answer(STALE_TEXT, show_alert=True)
        return

    await state.update_data(result=result_title_from_keys(keys))
    await state.set_state(RequestStates.waiting_name)
    await safe_delete(callback.message)
    await callback.message.answer(ASK_NAME_TEXT)
    await callback.answer()


async def on_request_name(message: Message, state: FSMContext) -> None:
    """Имя из заявки: проверяем длину, спрашиваем время и формат связи."""
    if await exit_form_on_command(message, state):
        return

    name = (message.text or "").strip()
    if not 2 <= len(name) <= 64:
        await message.answer(NAME_ERROR_TEXT)
        return

    await state.update_data(request_name=name)
    await state.set_state(RequestStates.waiting_time_format)
    await message.answer(ASK_TIME_FORMAT_TEXT)


async def on_request_time_format(message: Message, state: FSMContext) -> None:
    """Время и формат связи: проверяем длину, спрашиваем контакт."""
    if await exit_form_on_command(message, state):
        return

    time_format = (message.text or "").strip()
    if not 2 <= len(time_format) <= 200:
        await message.answer(TIME_FORMAT_ERROR_TEXT)
        return

    await state.update_data(request_time_format=time_format)
    await state.set_state(RequestStates.waiting_contact)
    await message.answer(ASK_CONTACT_TEXT)


async def on_request_contact(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    """Контакт: последний шаг формы — сохраняем заявку и уведомляем."""
    if await exit_form_on_command(message, state):
        return

    contact = (message.text or "").strip()
    if not 3 <= len(contact) <= 100:
        await message.answer(CONTACT_ERROR_TEXT)
        return

    data = await state.get_data()
    try:
        application = save_application(
            user_id=message.from_user.id,
            name=data.get("request_name", ""),
            time_format=data.get("request_time_format", ""),
            contact=contact,
            result=data.get("result", ""),
        )
    except OSError:
        # Файл недоступен (нет прав, диск занят). Состояние не снимаем:
        # пользователь может отправить контакт ещё раз.
        logging.exception("Не удалось сохранить заявку")
        await message.answer(SAVE_ERROR_TEXT)
        return

    await state.clear()
    await message.answer(THANKS_TEXT)
    await notify_manager(bot, application, message.from_user.id)


async def notify_manager(
    bot: Bot, application: dict, user_id: int
) -> None:
    """Отправляет детали заявки менеджеру на MANAGER_CHAT_ID из .env.

    Если id не задан или Telegram его не принял, заявка печатается
    в консоль — бот не падает. В консоли виден и Telegram-id
    отправителя: его можно вписать в MANAGER_CHAT_ID, чтобы заявки
    приходили в ваш чат.
    """
    text = (
        "Новая заявка на консультацию!\n\n"
        f"Имя: {html.escape(application['name'])}\n"
        f"Время и формат: {html.escape(application['time_format'])}\n"
        f"Контакт: {html.escape(application['contact'])}\n"
        f"Результат теста: {html.escape(application['result'])}"
    )
    manager_id = os.getenv("MANAGER_CHAT_ID", "").strip()
    if manager_id and manager_id != "ваш_id":
        try:
            await bot.send_message(chat_id=manager_id, text=text)
            return
        except (TelegramBadRequest, TelegramNetworkError) as error:
            logging.warning("Заявка менеджеру не ушла: %s", error)

    print("ЗАЯВКА (MANAGER_CHAT_ID не задан — менеджеру не отправлена):")
    print(text)
    print(
        f"Telegram-id отправителя: {user_id}. Впишите его в "
        "MANAGER_CHAT_ID в .env, чтобы заявки приходили в ваш чат."
    )


# --- Сборка приложения -------------------------------------------------------
async def on_stale(callback: CallbackQuery) -> None:
    """Незнакомая или устаревшая кнопка: подсказываем вернуться в меню."""
    await callback.answer(STALE_TEXT, show_alert=True)


def register_handlers(dp: Dispatcher) -> None:
    """Подключает обработчики к диспетчеру.

    Порядок важен: /start и /reset стоят первыми и сбрасывают любое
    состояние, поэтому тест и форму можно прервать командой. Шаги формы
    ловятся только в своих состояниях.
    """
    dp.message.register(on_start, CommandStart())
    dp.message.register(on_reset, Command("reset"))
    dp.callback_query.register(on_test, F.data == "test")
    dp.callback_query.register(
        on_answer,
        StateFilter(TestStates.answering),
        F.data.startswith("answer:"),
    )
    dp.callback_query.register(
        on_book_consult, F.data.startswith("book_consult:")
    )
    dp.message.register(
        on_request_name,
        StateFilter(RequestStates.waiting_name),
    )
    dp.message.register(
        on_request_time_format,
        StateFilter(RequestStates.waiting_time_format),
    )
    dp.message.register(
        on_request_contact,
        StateFilter(RequestStates.waiting_contact),
    )
    dp.callback_query.register(on_stale)


def read_token() -> str:
    """Читает токен из окружения.

    Токен хранится только в .env — в коде и в репозитории его быть
    не должно.
    """
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "ваш_токен_здесь":
        raise RuntimeError(
            "Не найден BOT_TOKEN. Скопируйте .env.example в .env "
            "и вставьте токен, который выдал @BotFather."
        )
    return token


def read_proxy() -> str | None:
    """Прокси из .env: пустое значение — подключаемся напрямую.

    PROXY_URL — необязательная настройка. Пустая строка, пробелы и вовсе
    отсутствующая переменная означают «прокси не нужен».
    """
    proxy = os.getenv("PROXY_URL", "").strip()
    return proxy or None


def create_session() -> AiohttpSession:
    """Сессия для Telegram: через прокси, если он указан в .env.

    Сам URL прокси в лог не пишем: в нём бывают логин и пароль.
    """
    proxy = read_proxy()
    if proxy is None:
        logging.info("Прокси не задан: подключаюсь к Telegram напрямую")
        return AiohttpSession()

    try:
        session = AiohttpSession(proxy=proxy)
    except RuntimeError as error:
        # aiogram так сообщает, что для прокси не хватает aiohttp-socks.
        raise RuntimeError(
            "PROXY_URL задан, но пакет aiohttp-socks не установлен. "
            "Выполните: pip install aiohttp-socks"
        ) from error

    logging.info("Прокси включён: запросы к Telegram идут через него")
    return session


def network_error_message(error: Exception) -> str:
    """Подсказка при сетевой ошибке: что проверить и куда вписать прокси."""
    return (
        f"Бот не запущен: нет связи с api.telegram.org "
        f"({error.__class__.__name__}).\n"
        "Проверьте интернет и VPN. Если Telegram недоступен напрямую, "
        "впишите прокси в .env, например:\n"
        "PROXY_URL=http://host:port или PROXY_URL=socks5://host:port"
    )


async def main() -> None:
    """Настраивает бота и запускает получение сообщений (long polling)."""
    # Токен читаем строго из .env рядом с bot.py: без явного пути
    # python-dotenv поднимается по дереву папок и может взять токен
    # из соседнего проекта.
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = Bot(
        token=read_token(),
        session=create_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # MemoryStorage держит состояние в памяти: при перезапуске
    # незаконченные тесты сбрасываются, для учебного проекта хватает.
    dp = Dispatcher(storage=MemoryStorage())

    register_handlers(dp)

    # Снимаем старый вебхук, чтобы polling не конфликтовал с ним.
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as error:
        # Понятное сообщение вместо трейсбека, если не заполнен .env
        # или для прокси не хватает aiohttp-socks.
        print(f"Бот не запущен: {error}")
        sys.exit(1)
    except NETWORK_ERRORS as error:
        # Сеть не пускает к api.telegram.org: это не ошибка кода,
        # а ограничение доступа.
        print(network_error_message(error))
        sys.exit(1)
    except TelegramUnauthorizedError:
        # Токен не принят Telegram (401): подсказываем проверить .env.
        print(
            "Бот не запущен: Telegram не принял токен (ошибка авторизации). "
            "Проверьте BOT_TOKEN в .env: возможно, токен устарел или "
            "перепутан с другим ботом."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")
