"""Запуск веб-панели: python -m webpanel

Слушает только localhost — наружу её выставляет Tailscale Funnel, который
сам терминирует HTTPS. Открывать порт в интернет напрямую не нужно и не
стоит: тогда панель окажется доступна по голому http.
"""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    host = os.getenv("PANEL_HOST", "0.0.0.0")
    port = int(os.getenv("PANEL_PORT", "8080"))
    uvicorn.run(
        "webpanel.app:app",
        host=host,
        port=port,
        log_level=os.getenv("PANEL_LOG_LEVEL", "info"),
        # доверяем заголовкам от локального прокси Tailscale, чтобы в журнале
        # входов был реальный адрес клиента, а не 127.0.0.1
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
