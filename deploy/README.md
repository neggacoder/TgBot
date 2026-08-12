# Автозапуск через systemd

Два юнита: `tgbot.service` — сам бот, `botpanel.service` — веб-панель.
Они независимы, панель можно ставить и без автозапуска бота.

## 1. Куда положить проект

Юниты написаны под путь `/opt/neongelion/bot` и пользователя `neongelion`.
Если у вас иначе — поправьте в обоих файлах `WorkingDirectory`, `ExecStart`,
`User`, `Group` и `ReadWritePaths`.

```bash
sudo useradd --system --home /opt/neongelion --shell /usr/sbin/nologin neongelion
sudo mkdir -p /opt/neongelion
sudo cp -r bot /opt/neongelion/
sudo chown -R neongelion:neongelion /opt/neongelion
```

## 2. Виртуальное окружение

Юниты запускают питон из venv внутри папки бота — так обновление системных
пакетов не ломает зависимости:

```bash
cd /opt/neongelion/bot
sudo -u neongelion python3 -m venv venv
sudo -u neongelion venv/bin/pip install -r requirements.txt
```

## 3. Настройки

`.env` читает сам python-dotenv из рабочего каталога, поэтому
`EnvironmentFile` в юнитах не нужен. Файл должен быть доступен только своему
пользователю — в нём токен бота и пароль от базы:

```bash
sudo -u neongelion cp env.example .env
sudo -u neongelion nano .env          # BOT_TOKEN, DB_*, PANEL_SESSION_SECRET
sudo chmod 600 .env
```

`PANEL_SESSION_SECRET` задайте обязательно, иначе после каждого перезапуска
панели всех будет выкидывать:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. Установка юнитов

```bash
sudo cp deploy/tgbot.service deploy/botpanel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tgbot botpanel
```

Проверить:

```bash
systemctl status botpanel
journalctl -u botpanel -f          # тут будет ссылка /setup?token=… при первом запуске
```

## 5. Публикация панели наружу

### Локальная сеть через NGINX

Если панель нужна в домашней сети, NGINX может отдавать её на
`http://IP_СЕРВЕРА:80`, а сама панель останется на `127.0.0.1:8080`.
Конфигурация лежит в `deploy/nginx/tgbot-panel.conf`:

```bash
sudo install -m 644 deploy/nginx/tgbot-panel.conf /etc/nginx/sites-available/tgbot-panel
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/tgbot-panel /etc/nginx/sites-enabled/tgbot-panel
sudo nginx -t
sudo systemctl enable --now nginx
```

Это обычный HTTP для LAN: не открывайте порт 80 в интернет. Для Telegram Mini
App продолжайте использовать HTTPS-адрес `PANEL_PUBLIC_URL`.

### Публичный HTTPS через Tailscale Funnel

```bash
tailscale funnel --bg 8080
tailscale funnel status
```

`--bg` делает правило постоянным — оно переживёт перезагрузку, отдельный юнит
для этого не нужен.

Публичной ссылкой будет значение `PANEL_PUBLIC_URL` из `.env` (адрес вида
`https://имя-устройства.tailnet.ts.net`). Не задавайте `PANEL_SITE_URL`: тогда
бот использует этот же HTTPS-адрес для кнопки «Открыть панель» и для Telegram
Mini App.

⚠️ `funnel` открывает панель **всему интернету**. Если доступ нужен только с
ваших устройств, возьмите `tailscale serve --bg 8080` — тогда она будет
видна лишь внутри вашей tailnet.

## Обновление кода

```bash
cd /opt/neongelion/bot
sudo -u neongelion git pull
sudo -u neongelion venv/bin/pip install -r requirements.txt
sudo systemctl restart tgbot botpanel
```

## Запуск вручную (для проверки перед systemd)

```bash
cd /home/nurasyl/TgBot/neong        # папка, где лежат bot.py и db.py
venv/bin/python -m webpanel          # или python3 -m webpanel без venv
```

`ModuleNotFoundError: No module named 'db'` означает одно из двух:

- запускали файл напрямую (`python webpanel/app.py`) — так нельзя, это
  модуль пакета; нужен `python -m webpanel`;
- запускали не из папки бота — `cd` в неё и повторите.

Панель сама добавляет свою родительскую папку в пути поиска, поэтому из
systemd (где рабочий каталог задан `WorkingDirectory`) всё работает.

## Если сервис не поднимается

- `journalctl -u botpanel -n 50` — что именно упало.
- Юниты сдаются после 5 неудачных попыток за 2–3 минуты и остаются в
  `failed`, чтобы не крутить бесконечный цикл перезапусков. После починки:
  `sudo systemctl reset-failed botpanel && sudo systemctl start botpanel`.
- `Permission denied` на `assets/` — бот пишет туда шрифты для стикеров:
  `sudo chown -R neongelion:neongelion /opt/neongelion/bot/assets`.
- Панель не видит базу — MySQL должен подняться раньше. Если база на другой
  машине, уберите `mysql.service` из строки `After=`.
