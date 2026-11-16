"""Тесты бота «Тип мышления»: подсчёт результата, форма заявки, хранение.

Что проверяем:
- calculate_result(): победа одного типа и ничья двух типов;
- валидацию формы заявки: имя 2-64, время и формат 2-200,
  контакт 3-100 символов;
- сохранение заявки в хранилище/заявки.json — на временном файле,
  чтобы не трогать реальные данные;
- связку «последний ответ → результат → кнопка „Оставить заявку“».

Внешнего Telegram здесь нет: Message и CallbackQuery заменены заглушками,
FSMContext взят настоящий на MemoryStorage. Уведомление менеджеру
подменяется AsyncMock — бот в тестах не печатает заявки в консоль.
"""

import itertools
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bot as bot_module
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from данные.questions import MAX_TOTAL, QUESTIONS, calculate_result
from хранилище import заявки as applications

# Один и тот же ключ хранилища на все тесты: имитируем одного пользователя.
STORAGE_KEY = StorageKey(bot_id=1, chat_id=42, user_id=42)


class SentMessage:
    """Сообщение, которое бот отправил: текст и клавиатура."""

    _ids = itertools.count(100)

    def __init__(self, text="", reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup
        self.message_id = next(SentMessage._ids)


class FakeMessage:
    """Заглушка aiogram.types.Message: запоминает, что бот отправил."""

    def __init__(self, text=None, user_id=42, message_id=1):
        self.text = text
        self.message_id = message_id
        self.from_user = SimpleNamespace(id=user_id)
        self.sent = []
        self.deleted = 0

    async def answer(self, text, reply_markup=None, **kwargs):
        message = SentMessage(text=text, reply_markup=reply_markup)
        self.sent.append(message)
        return message

    async def delete(self):
        self.deleted += 1


class FakeCallbackQuery:
    """Заглушка CallbackQuery: помнит ответы в alert."""

    def __init__(self, data, message=None):
        self.data = data
        self.message = message
        self.alerts = []

    async def answer(self, text=None, show_alert=False):
        self.alerts.append(text)


class ApplicationsFileTestCase(unittest.TestCase):
    """Общая обвязка: временная папка вместо хранилища/заявки.json."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.applications_file = Path(self.tmp_dir.name) / "заявки.json"

        patcher = mock.patch.object(
            applications, "APPLICATIONS_FILE", self.applications_file
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_raw(self) -> str:
        return self.applications_file.read_text(encoding="utf-8")

    def read_json(self) -> list:
        return json.loads(self.read_raw())

    def backups(self) -> list:
        return sorted(Path(self.tmp_dir.name).glob("заявки.битые.*.json"))


class TestApplicationsStorage(ApplicationsFileTestCase):
    """Сохранение заявок в JSON."""

    def test_save_creates_file_with_fields_and_timestamp(self):
        applications.save_application(
            user_id=42,
            name="Анна",
            time_format="завтра после 18:00, Telegram",
            contact="@anna_test",
            result="Аналитический",
        )

        self.assertTrue(self.applications_file.is_file())
        saved = self.read_json()[0]
        self.assertEqual(
            sorted(saved),
            [
                "contact",
                "name",
                "result",
                "time_format",
                "timestamp",
                "user_id",
            ],
        )
        self.assertEqual(saved["name"], "Анна")
        self.assertEqual(saved["result"], "Аналитический")
        self.assertEqual(saved["user_id"], 42)

        # timestamp — ISO 8601, разбирается обратно в дату.
        moment = datetime.fromisoformat(saved["timestamp"])
        self.assertIsNotNone(moment.tzinfo)

    def test_second_application_appends(self):
        applications.save_application(
            42, "Анна", "после 18:00", "@anna", "Гуманитарный"
        )
        applications.save_application(
            43, "Иван", "завтра утром", "+79990000000", "Практический"
        )

        saved = self.read_json()
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[1]["name"], "Иван")

    def test_tie_result_saved_as_two_titles(self):
        applications.save_application(
            42, "Анна", "завтра", "@anna", "Аналитический и Гуманитарный"
        )
        self.assertEqual(
            self.read_json()[0]["result"], "Аналитический и Гуманитарный"
        )

    def test_missing_file_gives_empty_list(self):
        self.assertEqual(applications.load_applications(), [])

    def test_broken_json_is_backed_up_and_file_rebuilt(self):
        self.applications_file.write_text(
            '[{"name": "Анна", "contact": ', encoding="utf-8"
        )

        applications.save_application(
            42, "Иван", "завтра утром", "@ivan", "Креативный"
        )

        saved = self.read_json()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "Иван")

        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertIn("Анна", backups[0].read_text(encoding="utf-8"))


def analytical_answers(count: int) -> list[dict]:
    """count ответов в пользу аналитического типа (вариант 0)."""
    return [
        {"scores": QUESTIONS[i % len(QUESTIONS)]["options"][0]["scores"]}
        for i in range(count)
    ]


class TestCalculateResult(unittest.TestCase):
    """Подсчёт результата: победа, ничья, ошибки и целостность данных."""

    def test_questions_structure(self):
        self.assertEqual(len(QUESTIONS), 10)
        self.assertEqual(MAX_TOTAL, 10)
        for question in QUESTIONS:
            self.assertEqual(len(question["options"]), 4)
            types = {
                next(iter(option["scores"])) for option in question["options"]
            }
            # Каждый вопрос отдаёт по баллу всем четырём типам сразу.
            self.assertEqual(len(types), 4)
            for option in question["options"]:
                for points in option["scores"].values():
                    self.assertEqual(points, 1)

    def test_single_winner(self):
        result = calculate_result(analytical_answers(10))

        self.assertFalse(result["is_tie"])
        self.assertEqual(result["primary"]["title"], "Аналитический")
        self.assertIsNone(result["secondary"])
        self.assertEqual(result["scores"]["analytical"], 10)
        self.assertEqual(result["max_score"], 10)
        self.assertEqual(result["max_total"], MAX_TOTAL)

    def test_tie_between_two_types(self):
        answers = analytical_answers(5)
        answers += [
            {"scores": QUESTIONS[i]["options"][1]["scores"]}
            for i in range(5, 10)
        ]
        result = calculate_result(answers)

        self.assertTrue(result["is_tie"])
        self.assertEqual(result["primary"]["title"], "Аналитический")
        self.assertEqual(result["secondary"]["title"], "Гуманитарный")
        self.assertEqual(
            [t["title"] for t in result["tie_types"]],
            ["Аналитический", "Гуманитарный"],
        )
        self.assertEqual(result["max_score"], 5)

    def test_each_type_can_win(self):
        for option_index, title in enumerate(
            ["Аналитический", "Гуманитарный", "Креативный", "Практический"]
        ):
            answers = [
                {
                    "scores": QUESTIONS[i]["options"][option_index][
                        "scores"
                    ]
                }
                for i in range(10)
            ]
            result = calculate_result(answers)
            self.assertEqual(result["primary"]["title"], title)

    def test_empty_answers_raises(self):
        with self.assertRaises(ValueError):
            calculate_result([])

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            calculate_result([{"scores": {"martian": 1}}])

    def test_result_title_single_and_tie(self):
        self.assertEqual(
            bot_module.result_title_from_keys(["practical"]),
            "Практический",
        )
        self.assertEqual(
            bot_module.result_title_from_keys(
                ["analytical", "humanitarian"]
            ),
            "Аналитический и Гуманитарный",
        )


class TestMenu(unittest.TestCase):
    """Главное меню: только вход в тест, без лишних кнопок."""

    def test_menu_has_only_start_button(self):
        keyboard = bot_module.menu_keyboard()
        buttons = [
            button
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text, "Начать тест")
        self.assertEqual(buttons[0].callback_data, "test")


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    """Обвязка тестов бота: временный файл заявок и настоящее FSM.

    Уведомление менеджеру подменяется AsyncMock: в тестах бот
    не печатает заявки в консоль и не ходит в Telegram.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.applications_file = Path(self.tmp_dir.name) / "заявки.json"

        patcher = mock.patch.object(
            applications, "APPLICATIONS_FILE", self.applications_file
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        notify = mock.patch.object(
            bot_module, "notify_manager", new=mock.AsyncMock()
        )
        notify.start()
        self.addCleanup(notify.stop)

        self.state = FSMContext(key=STORAGE_KEY, storage=MemoryStorage())

    def read_json(self) -> list:
        return json.loads(self.applications_file.read_text(encoding="utf-8"))

    async def start_request(self, keys="analytical"):
        """Нажимает «Оставить заявку» с результатом теста в callback."""
        callback = FakeCallbackQuery(
            f"book_consult:{keys}", FakeMessage()
        )
        await bot_module.on_book_consult(callback, self.state)
        return callback

    async def fill_request(
        self,
        name="Анна",
        time_format="завтра после 18:00, Telegram",
        contact="@anna_test",
    ):
        """Проходит три шага формы и возвращает последнее сообщение."""
        await self.start_request()
        await bot_module.on_request_name(FakeMessage(name), self.state)
        await bot_module.on_request_time_format(
            FakeMessage(time_format), self.state
        )
        message = FakeMessage(contact)
        await bot_module.on_request_contact(message, self.state, None)
        return message


class TestRequestForm(BotTestCase):
    """Форма заявки: шаги, валидация полей, запись в JSON."""

    async def test_book_consult_asks_name(self):
        callback = await self.start_request()

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_name.state,
        )
        self.assertEqual(callback.message.deleted, 1)
        self.assertIn("Как вас зовут?", callback.message.sent[-1].text)

    async def test_book_consult_with_unknown_type_shows_stale_alert(self):
        callback = FakeCallbackQuery("book_consult:martian", FakeMessage())

        await bot_module.on_book_consult(callback, self.state)

        self.assertEqual(len(callback.alerts), 1)
        self.assertEqual(callback.alerts[0], bot_module.STALE_TEXT)
        self.assertIsNone(await self.state.get_state())
        self.assertFalse(self.applications_file.exists())

    async def test_name_too_short_is_rejected(self):
        await self.start_request()

        message = FakeMessage("А")
        await bot_module.on_request_name(message, self.state)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_name.state,
        )
        self.assertEqual(message.sent[-1].text, bot_module.NAME_ERROR_TEXT)

    async def test_name_too_long_is_rejected(self):
        await self.start_request()

        message = FakeMessage("А" * 65)
        await bot_module.on_request_name(message, self.state)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_name.state,
        )
        self.assertEqual(message.sent[-1].text, bot_module.NAME_ERROR_TEXT)

    async def test_name_of_64_symbols_is_accepted(self):
        await self.start_request()

        message = FakeMessage("А" * 64)
        await bot_module.on_request_name(message, self.state)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_time_format.state,
        )

    async def test_time_too_short_is_rejected(self):
        await self.start_request()
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)

        message = FakeMessage("т")
        await bot_module.on_request_time_format(message, self.state)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_time_format.state,
        )
        self.assertEqual(
            message.sent[-1].text, bot_module.TIME_FORMAT_ERROR_TEXT
        )

    async def test_time_too_long_is_rejected(self):
        await self.start_request()
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)

        message = FakeMessage("т" * 201)
        await bot_module.on_request_time_format(message, self.state)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_time_format.state,
        )

    async def test_contact_too_short_is_rejected(self):
        await self.start_request()
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)
        await bot_module.on_request_time_format(
            FakeMessage("завтра после 18:00"), self.state
        )

        message = FakeMessage("кк")
        await bot_module.on_request_contact(message, self.state, None)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_contact.state,
        )
        self.assertEqual(
            message.sent[-1].text, bot_module.CONTACT_ERROR_TEXT
        )
        self.assertFalse(self.applications_file.exists())

    async def test_contact_too_long_is_rejected(self):
        await self.start_request()
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)
        await bot_module.on_request_time_format(
            FakeMessage("завтра после 18:00"), self.state
        )

        message = FakeMessage("к" * 101)
        await bot_module.on_request_contact(message, self.state, None)

        self.assertEqual(
            await self.state.get_state(),
            bot_module.RequestStates.waiting_contact.state,
        )

    async def test_full_form_saves_application_and_notifies(self):
        message = await self.fill_request()

        # Благодарность и очистка состояния.
        self.assertEqual(message.sent[-1].text, bot_module.THANKS_TEXT)
        self.assertIsNone(await self.state.get_state())

        # Заявка в файле с полями по ТЗ.
        saved = self.read_json()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "Анна")
        self.assertEqual(
            saved[0]["time_format"], "завтра после 18:00, Telegram"
        )
        self.assertEqual(saved[0]["contact"], "@anna_test")
        self.assertEqual(saved[0]["result"], "Аналитический")
        self.assertEqual(saved[0]["user_id"], 42)

        # Менеджеру ушли детали заявки.
        bot_module.notify_manager.assert_awaited_once()
        args = bot_module.notify_manager.await_args.args
        self.assertEqual(args[1], saved[0])
        self.assertEqual(args[2], 42)

    async def test_tie_result_title_in_saved_application(self):
        await self.start_request(keys="analytical:humanitarian")
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)
        await bot_module.on_request_time_format(
            FakeMessage("завтра после 18:00"), self.state
        )
        await bot_module.on_request_contact(
            FakeMessage("@anna_test"), self.state, None
        )

        self.assertEqual(
            self.read_json()[0]["result"],
            "Аналитический и Гуманитарный",
        )

    async def test_command_inside_form_resets_to_welcome(self):
        await self.start_request()
        await bot_module.on_request_name(FakeMessage("Анна"), self.state)

        message = FakeMessage("/start")
        await bot_module.on_request_time_format(message, self.state)

        self.assertIsNone(await self.state.get_state())
        self.assertIn(
            bot_module.WELCOME_TEXT, message.sent[-1].text
        )
        self.assertFalse(self.applications_file.exists())


class TestTestFlow(BotTestCase):
    """Прохождение теста: результат и защита от старых кнопок."""

    async def test_last_answer_shows_result_and_clears_state(self):
        await self.state.set_state(bot_module.TestStates.answering)
        await self.state.set_data(
            {
                "index": 9,
                "answers": [{"scores": {"analytical": 1}}] * 9,
                "message_id": 7,
            }
        )
        callback = FakeCallbackQuery("answer:0", FakeMessage(message_id=7))

        await bot_module.on_answer(callback, self.state)

        self.assertIsNone(await self.state.get_state())
        screen = callback.message.sent[-1]
        self.assertIn(
            "Ваш тип мышления — Аналитический", screen.text
        )
        buttons = screen.reply_markup.inline_keyboard
        self.assertEqual(
            buttons[0][0].callback_data, "book_consult:analytical"
        )

    async def test_stale_button_is_ignored(self):
        await self.state.set_state(bot_module.TestStates.answering)
        await self.state.set_data(
            {
                "index": 3,
                "answers": [],
                "message_id": 7,
            }
        )
        callback = FakeCallbackQuery("answer:0", FakeMessage(message_id=99))

        await bot_module.on_answer(callback, self.state)

        self.assertEqual(callback.alerts, [bot_module.STALE_TEXT])
        self.assertEqual(
            await self.state.get_state(),
            bot_module.TestStates.answering.state,
        )
        self.assertEqual(callback.message.sent, [])

    async def test_middle_answer_moves_to_next_question(self):
        await self.state.set_state(bot_module.TestStates.answering)
        await self.state.set_data(
            {
                "index": 0,
                "answers": [],
                "message_id": 7,
            }
        )
        callback = FakeCallbackQuery("answer:2", FakeMessage(message_id=7))

        await bot_module.on_answer(callback, self.state)

        data = await self.state.get_data()
        self.assertEqual(data["index"], 1)
        self.assertEqual(len(data["answers"]), 1)
        self.assertEqual(
            data["answers"][0], {"scores": {"creative": 1}}
        )
        # Старый экран удалён, новый вопрос отправлен.
        self.assertEqual(callback.message.deleted, 1)
        self.assertIn(
            "Вопрос 2 из 10", callback.message.sent[-1].text
        )
