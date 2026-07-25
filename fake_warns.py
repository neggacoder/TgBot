"""Обманные варны («&варн») — розыгрыш, неотличимый в чате от настоящего варна.

Команда выводит ту же карточку, что и «варн», так же наращивает счётчик и так же
показывается в списке «варны», но в таблицу warns ничего не пишет и на лимите
никого не банит. Нужна она затем, чтобы разыграть человека, а не наказать его.

Что здесь важно:

* Записи живут **в памяти процесса**, не в базе. Так розыгрыш физически не может
  смешаться с настоящими варнами, по которым бот банит, а перезапуск бота его
  обнуляет — для шутки скорее плюс, чем потеря.
* Обманные варны показываются вместе с настоящими: у человека с одним реальным
  варном «&варн» обязан показать 2/3, а «варны» — обе строки. Иначе первая же
  проверка списка выдаёт подделку.
* Срок у них тоже настоящий: истёкшие перестают считаться, как и обычные варны.
* В журнал бота розыгрыш пишется отдельным событием (fake_warn) — в чате он
  неотличим, но другой модератор, глядя в панель, должен видеть, что варна не
  было. Иначе он выдаст «третий» варн по ложному следу, и человек получит
  настоящий бан из-за шутки.

Модуль без Telegram и без базы — чтобы проверялся тестами напрямую.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

# (chat_id, user_id) -> выданные обманные варны, в порядке выдачи
_issued: dict[tuple[int, int], list[dict]] = {}


def add(
    chat_id: int,
    user_id: int,
    *,
    reason: Optional[str],
    warned_by: int,
    created_at: datetime,
    expires_at: Optional[datetime],
) -> None:
    """«Выдаёт» обманный варн. Поля те же, что у настоящего, — из них потом
    собирается строка в списке «варны»."""
    _issued.setdefault((chat_id, user_id), []).append({
        "reason": reason,
        "warned_by": warned_by,
        "created_at": created_at,
        "expires_at": expires_at,
    })


def active(chat_id: int, user_id: int, now: datetime) -> list[dict]:
    """Ещё не истёкшие обманные варны. Истёкшие тихо забываются — настоящие
    ведут себя так же, и расхождение бросалось бы в глаза."""
    rows = _issued.get((chat_id, user_id))
    if not rows:
        return []
    alive = [r for r in rows if r["expires_at"] is None or r["expires_at"] > now]
    if alive:
        _issued[(chat_id, user_id)] = alive
    else:
        _issued.pop((chat_id, user_id), None)
    return alive


def count(chat_id: int, user_id: int, now: datetime) -> int:
    return len(active(chat_id, user_id, now))


def drop(chat_id: int, user_id: int, now: datetime) -> int:
    """Снимает последний обманный варн («&-варн»), возвращает остаток. Снимать
    нечего — просто ноль, без ошибки: модератор не обязан помнить, кого
    разыгрывали."""
    rows = active(chat_id, user_id, now)
    if rows:
        rows.pop()
    if rows:
        _issued[(chat_id, user_id)] = rows
    else:
        _issued.pop((chat_id, user_id), None)
    return len(rows)


def clear(chat_id: int, user_id: int) -> int:
    """Снимает все обманные варны разом, возвращает сколько их было."""
    return len(_issued.pop((chat_id, user_id), []))


def reset_all() -> None:
    """Полная очистка — нужна тестам, чтобы соседние проверки не влияли друг
    на друга."""
    _issued.clear()
