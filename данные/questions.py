"""Банк вопросов теста и логика подсчёта по четырём типам мышления.

Как считается результат:
- тест из 10 вопросов, у каждого 4 варианта ответа;
- каждый вариант добавляет 1 балл своему типу (analytical, humanitarian,
  creative или practical);
- баллы всех ответов складываются, побеждает тип с максимальной суммой;
- если максимум набрали два и более типа, результат считается ничьей:
  бот покажет оба типа с описаниями и профессиями.

Максимум баллов: 10 вопросов * 1 балл = 10.
"""

from данные.types import TYPES

QUESTIONS = [
    {
        "id": 1,
        "text": "Что вы предпочитаете делать в свободное время?",
        "options": [
            {
                "text": "Разгадывать головоломки / читать научпоп",
                "scores": {"analytical": 1},
            },
            {
                "text": "Общаться с друзьями / читать романы",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Рисовать / писать музыку",
                "scores": {"creative": 1},
            },
            {
                "text": "Мастерить что-то руками / разбирать технику",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 2,
        "text": "Как вы принимаете важные решения?",
        "options": [
            {
                "text": "Взвешиваю все «за» и «против»",
                "scores": {"analytical": 1},
            },
            {
                "text": "Прислушиваюсь к своей интуиции и эмоциям",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Ищу нестандартный, креативный выход",
                "scores": {"creative": 1},
            },
            {
                "text": "Опираюсь на свой прошлый опыт и практику",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 3,
        "text": "Что вас больше всего раздражает в работе?",
        "options": [
            {
                "text": "Беспорядок в данных и отсутствие логики",
                "scores": {"analytical": 1},
            },
            {
                "text": "Конфликты в коллективе и непонимание",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Жесткие рамки и отсутствие свободы творчества",
                "scores": {"creative": 1},
            },
            {
                "text": "Долгие разговоры без реальных действий",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 4,
        "text": "Какой предмет в школе вам нравился больше всего?",
        "options": [
            {
                "text": "Математика и физика",
                "scores": {"analytical": 1},
            },
            {
                "text": "Литература и история",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Рисование и музыка",
                "scores": {"creative": 1},
            },
            {
                "text": "Труд и технология",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 5,
        "text": "Какая задача вызывает у вас наибольший интерес?",
        "options": [
            {
                "text": "Найти ошибку в сложной системе",
                "scores": {"analytical": 1},
            },
            {
                "text": "Помочь человеку разобраться в его проблеме",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Придумать концепцию нового продукта",
                "scores": {"creative": 1},
            },
            {
                "text": "Организовать процесс с нуля до результата",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 6,
        "text": "Как вы ведете себя в споре?",
        "options": [
            {
                "text": "Привожу аргументы и факты",
                "scores": {"analytical": 1},
            },
            {
                "text": "Стараюсь понять точку зрения другого",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Предлагаю неожиданное решение",
                "scores": {"creative": 1},
            },
            {
                "text": "Говорю о том, как это можно применить на деле",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 7,
        "text": "Что вам легче всего дается?",
        "options": [
            {
                "text": "Работа с формулами и таблицами",
                "scores": {"analytical": 1},
            },
            {
                "text": "Написание текстов и выступления",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Генерация идей и визуализация",
                "scores": {"creative": 1},
            },
            {
                "text": "Настройка рабочих процессов",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 8,
        "text": "Какой отдых вы предпочтете?",
        "options": [
            {
                "text": "Решение стратегических задач за компьютером",
                "scores": {"analytical": 1},
            },
            {
                "text": "Поездку в новую страну с экскурсиями",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Посещение выставки или концерта",
                "scores": {"creative": 1},
            },
            {
                "text": "Активный отдых или работа в саду",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 9,
        "text": "Что для вас важнее всего в коллективе?",
        "options": [
            {
                "text": "Четкие правила и регламенты",
                "scores": {"analytical": 1},
            },
            {
                "text": "Дружелюбная атмосфера и поддержка",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Свобода творчества и отсутствие застоя",
                "scores": {"creative": 1},
            },
            {
                "text": "Дисциплина и слаженная работа",
                "scores": {"practical": 1},
            },
        ],
    },
    {
        "id": 10,
        "text": "Какую книгу или фильм вы выберете?",
        "options": [
            {
                "text": "Научно-популярный или документальный",
                "scores": {"analytical": 1},
            },
            {
                "text": "Психологический роман или драму",
                "scores": {"humanitarian": 1},
            },
            {
                "text": "Фантастику или авангардное кино",
                "scores": {"creative": 1},
            },
            {
                "text": "Инструкцию по применению или бизнес-литературу",
                "scores": {"practical": 1},
            },
        ],
    },
]


# Максимум баллов считаем из данных: 10 вопросов * 1 балл = 10.
MAX_TOTAL = sum(
    max(sum(option["scores"].values()) for option in question["options"])
    for question in QUESTIONS
)


def calculate_result(answers: list[dict]) -> dict:
    """Считает результат теста по ответам пользователя.

    answers — список словарей вида {"scores": {"analytical": 1}},
    по одному на каждый ответ (такие словари лежат в QUESTIONS).

    Возвращает словарь:
    - is_tie: True, если максимальный балл набрали два типа или больше;
    - primary: словарь победителя из TYPES (при ничьей — первый
      из лидеров);
    - secondary: второй тип при ничьей, иначе None;
    - tie_types: все типы с максимальным баллом (для ничьей из трёх);
    - scores: баллы по всем четырём типам;
    - max_score: лучший результат теста;
    - max_total: сколько баллов можно было набрать.
    """
    if not answers:
        raise ValueError("Нет ни одного ответа: считать результат не из чего")

    scores = {type_id: 0 for type_id in TYPES}
    for answer in answers:
        for type_id, points in answer["scores"].items():
            if type_id not in scores:
                raise ValueError(f"Неизвестный тип в ответе: {type_id}")
            scores[type_id] += points

    max_score = max(scores.values())
    winners = [
        type_id for type_id, score in scores.items() if score == max_score
    ]
    primary = TYPES[winners[0]]

    if len(winners) == 1:
        return {
            "is_tie": False,
            "primary": primary,
            "secondary": None,
            "tie_types": [],
            "scores": scores,
            "max_score": max_score,
            "max_total": MAX_TOTAL,
        }

    secondary = TYPES[winners[1]]
    return {
        "is_tie": True,
        "primary": primary,
        "secondary": secondary,
        "tie_types": [TYPES[type_id] for type_id in winners],
        "scores": scores,
        "max_score": max_score,
        "max_total": MAX_TOTAL,
    }
