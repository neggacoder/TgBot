"""
Скрипт скачивает фото с https://img.daeeros.ru/photos/{id}
используя Playwright (обходит CORS, т.к. запросы идут не из JS
в браузере со страницы, а напрямую через API запросов Playwright).

Установка (один раз):
    pip install playwright
    playwright install chromium

Запуск:
    python download_photos.py

Результат: все найденные фото сохраняются в папку ./photos/
в виде photo_1.jpg, photo_2.jpg и т.д. (расширение определяется
автоматически по Content-Type ответа).
"""

import os
import time
from playwright.sync_api import sync_playwright

BASE_URL = "https://img.daeeros.ru/photos/{id}"
OUTPUT_DIR = "photos"
START_ID = 1
END_ID = 2924
DELAY_SEC = 0.15          # пауза между запросами, чтобы не долбить сервер
RETRIES = 3                # сколько раз повторить при сетевой ошибке
TIMEOUT_MS = 15000

# Сопоставление content-type -> расширение файла
EXT_MAP = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}


def guess_extension(content_type: str) -> str:
    if not content_type:
        return "jpg"
    content_type = content_type.split(";")[0].strip().lower()
    return EXT_MAP.get(content_type, "jpg")


def download_one(context, photo_id: int) -> str:
    """
    Возвращает:
      "ok"       — успешно скачано
      "missing"  — сервер ответил 404 (фото реально нет)
      "error"    — не удалось скачать после всех попыток
    """
    url = BASE_URL.format(id=photo_id)

    for attempt in range(1, RETRIES + 1):
        try:
            response = context.request.get(url, timeout=TIMEOUT_MS)

            if response.status == 404:
                return "missing"

            if not response.ok:
                print(f"  [!] Фото {photo_id}: статус {response.status} (попытка {attempt}/{RETRIES})")
                time.sleep(0.5)
                continue

            content_type = response.headers.get("content-type", "")
            ext = guess_extension(content_type)
            body = response.body()

            filepath = os.path.join(OUTPUT_DIR, f"photo_{photo_id}.{ext}")
            with open(filepath, "wb") as f:
                f.write(body)

            return "ok"

        except Exception as e:
            print(f"  [!] Фото {photo_id}: ошибка {e} (попытка {attempt}/{RETRIES})")
            time.sleep(0.5)

    return "error"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ok_count = 0
    missing_count = 0
    error_ids = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        for photo_id in range(START_ID, END_ID + 1):
            # Пропускаем, если файл уже скачан ранее (можно перезапускать скрипт)
            already_done = any(
                os.path.exists(os.path.join(OUTPUT_DIR, f"photo_{photo_id}.{ext}"))
                for ext in EXT_MAP.values()
            )
            if already_done:
                ok_count += 1
                continue

            status = download_one(context, photo_id)

            if status == "ok":
                ok_count += 1
                print(f"[{photo_id}/{END_ID}] сохранено")
            elif status == "missing":
                missing_count += 1
                print(f"[{photo_id}/{END_ID}] отсутствует (404)")
            else:
                error_ids.append(photo_id)
                print(f"[{photo_id}/{END_ID}] ОШИБКА после {RETRIES} попыток")

            time.sleep(DELAY_SEC)

        browser.close()

    print("\n=== Готово ===")
    print(f"Скачано: {ok_count}")
    print(f"Отсутствует (404): {missing_count}")
    print(f"Ошибки: {len(error_ids)}")
    if error_ids:
        print(f"ID с ошибками (можно перезапустить скрипт, они пропущенные докачаются): {error_ids}")


if __name__ == "__main__":
    main()
