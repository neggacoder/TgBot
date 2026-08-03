"""Сколько правок сделает переписыватель и где он откажется.

Запуск: .venv/bin/python -m tools.rewrite_report

Отчёт нужен ДО правки: отказы — это места, которые придётся смотреть руками,
и их число решает, делать ли правку одним заходом или порциями.
"""

from __future__ import annotations

import pathlib

from tools import rewrite_chat_id as r

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent
МОДУЛИ = ["db.py", "farm_actions.py", "casino_actions.py", "business_actions.py",
          "fishing_actions.py", "work_actions.py", "shop_actions.py",
          "profile_actions.py", "game_actions.py"]


def цели() -> list[pathlib.Path]:
    return sorted(set(КОРЕНЬ.glob("*.py"))
                  | set((КОРЕНЬ / "webpanel").glob("*.py"))
                  | set((КОРЕНЬ / "tests").glob("*.py")))


def имена_функций() -> dict[str, set[str]]:
    итог: dict[str, set[str]] = {}
    for файл in МОДУЛИ:
        путь = КОРЕНЬ / файл
        if путь.exists():
            итог[путь.stem] = r.функции_с_чатом(путь.read_text(encoding="utf-8"))
    return итог


def main() -> None:
    имена = имена_функций()
    всего = sum(len(v) for v in имена.values())
    print(f"Функций с chat_id первым параметром: {всего}")
    for модуль, набор in sorted(имена.items()):
        print(f"  {модуль:20} {len(набор):4}")

    правок, все_отказы, по_файлам = 0, [], {}
    for путь in цели():
        текст = путь.read_text(encoding="utf-8")
        новый, свои = текст, 0
        for модуль, набор in имена.items():
            новый, отказы, сколько = r.убрать_аргумент(новый, набор, {модуль})
            все_отказы += [f"{путь.name}: {о}" for о in отказы]
            свои += сколько
        правок += свои
        if свои:
            по_файлам[путь.name] = свои
    print(f"\nВызовов будет переписано: {правок}")
    for имя, сколько in sorted(по_файлам.items(), key=lambda x: -x[1])[:10]:
        print(f"  {имя:32} {сколько:5}")
    # Отказ в комментарии — не работа: переписыватель ищет текст, а не код,
    # и упоминание вызова в пояснении выглядит для него так же.
    настоящие = [о for о in все_отказы if "is_active=False" not in о]
    print(f"Отказов (смотреть руками): {len(настоящие)}"
          f"  [ещё {len(все_отказы) - len(настоящие)} — упоминания в комментариях]")
    все_отказы = настоящие
    for отказ in все_отказы[:30]:
        print("  ", отказ)


if __name__ == "__main__":
    main()
