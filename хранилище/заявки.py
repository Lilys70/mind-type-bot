"""Сохранение заявок на консультацию в JSON.

Заявки лежат в хранилище/заявки.json рядом с кодом: файл читается
и переписывается целиком при каждом сохранении. Заявок в учебном
проекте десятки, поэтому отдельная база данных не нужна.

Если файл повреждён (битый JSON или неожиданный формат), его копия
уходит в хранилище/заявки.битые.<дата-время>.json, а работа
продолжается с чистого списка: данные не теряются и бот не падает.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

# Папка хранилища и файл заявок рядом с этим модулем.
STORAGE_DIR = Path(__file__).resolve().parent
APPLICATIONS_FILE = STORAGE_DIR / "заявки.json"


def current_timestamp() -> str:
    """Текущее время в формате ISO 8601 с часовым поясом машины."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _backup_broken(path: Path) -> Path:
    """Кладёт копию повреждённого файла рядом и возвращает путь копии.

    Копия нужна, чтобы данные заказчиков можно было посмотреть руками,
    прежде чем файл будет перезаписан.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.битые.{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    logging.warning("Файл %s повреждён, копия: %s", path.name, backup.name)
    return backup


def load_applications(path: Path | None = None) -> list[dict]:
    """Читает список заявок из файла.

    Нет файла — возвращает пустой список. Битый JSON или не список
    внутри файла — откладывает копию и возвращает пустой список,
    чтобы сохранение новой заявки могло начаться заново.
    """
    target = Path(path) if path is not None else APPLICATIONS_FILE
    if not target.is_file():
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _backup_broken(target)
        return []

    if not isinstance(data, list):
        _backup_broken(target)
        return []

    return data


def save_application(
    user_id: int,
    name: str,
    time_format: str,
    contact: str,
    result: str,
) -> dict:
    """Дописывает заявку в хранилище/заявки.json и возвращает её запись.

    user_id — Telegram-id автора заявки, time_format — удобное время
    и формат связи («завтра после 18:00, Telegram»), result — победивший
    тип мышления (при ничьей — оба типа через «и»). Время ставится сразу
    в ISO 8601. Файл переписывается через временный: если запись
    прервётся, старый файл останется целым.
    """
    application = {
        "timestamp": current_timestamp(),
        "user_id": user_id,
        "name": name,
        "time_format": time_format,
        "contact": contact,
        "result": result,
    }

    applications = load_applications()
    applications.append(application)

    APPLICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = APPLICATIONS_FILE.with_name(APPLICATIONS_FILE.name + ".tmp")
    temp_file.write_text(
        json.dumps(applications, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    temp_file.replace(APPLICATIONS_FILE)

    logging.info(
        "Заявка сохранена: user_id=%s, всего заявок %s",
        user_id,
        len(applications),
    )
    return application
