# OpenClaw lab

Локальный стенд [OpenClaw](https://docs.openclaw.ai) в Docker Desktop (Windows) за nginx-прокси.
Агент доступен через Control UI в браузере и через Telegram-бота, умеет отправлять почту.

## Состав

| Компонент | Контейнер | Адрес в сети `app_net` | Порт на хосте |
|---|---|---|---|
| OpenClaw gateway (`ghcr.io/openclaw/openclaw:latest`) | `openclaw-builder` | 192.168.100.10:18789 | случайный (только для отладки) |
| nginx (`nginx:alpine`) | `openclaw-lab-nginx-1` | 192.168.100.20:18790 | **18790** |

Файлы:

- `docker-compose.yml` — сервисы, сеть со статическими адресами, external volume.
- `nginx.conf` — прокси на gateway с заголовками `X-Forwarded-*` и `Upgrade` (WebSocket).
- `.env` — секреты (в git не попадает): ключи моделей, `OPENCLAW_GATEWAY_TOKEN`, `SMTP_*`.
- `data` — симлинк на живые данные gateway (см. ниже).

## Запуск

```powershell
docker compose up -d
docker compose logs -f openclaw
```

Control UI: <http://127.0.0.1:18790>. Полезные страницы внутри UI:

- <http://127.0.0.1:18790/chat> — чат с агентом;
- <http://127.0.0.1:18790/config> — редактор `openclaw.json` (правки уходят в тот же файл в volume;
  секция `gateway.*` требует перезапуска контейнера);
- <http://127.0.0.1:18790/settings> — настройки по группам («Подключения», «Агенты и инструменты»,
  «Конфиденциальность и безопасность», «Система»), с поиском по настройкам.

При первом входе браузер спросит секрет gateway —
значение `OPENCLAW_GATEWAY_TOKEN` из `.env`. Затем новое устройство нужно одобрить:

```powershell
docker exec openclaw-builder openclaw devices list
docker exec openclaw-builder openclaw devices approve <request-id>
```

## Где лежат данные и как править конфиг

Состояние gateway (`openclaw.json`, сессии, workspace агента, спаренные устройства) хранится
в named volume `openclaw-lab_openclaw_data`. Volume объявлен как `external`, поэтому
`docker compose down -v` его не удаляет.

Docker Desktop показывает volume как обычную папку Windows:

```
\wsl.localhost\docker-desktop\mnt\docker-desktop-disk\data\docker\volumes\openclaw-lab_openclaw_data\_data
```

На этот путь указывает симлинк `data` (создаётся один раз из PowerShell **от администратора**):

```powershell
New-Item -ItemType SymbolicLink -Path 'C:\openclaw-lab\data' -Target '\wsl.localhost\docker-desktop\mnt\docker-desktop-disk\data\docker\volumes\openclaw-lab_openclaw_data\_data'
```

Живой конфиг — `data\openclaw.json`, workspace агента — `data\workspace\`. Изменения секции
`gateway.*` вступают в силу после перезапуска:

```powershell
docker compose restart openclaw
```

Альтернатива правке файла — CLI внутри контейнера:

```powershell
docker exec openclaw-builder openclaw config get gateway
docker exec openclaw-builder openclaw config set gateway.trustedProxies '["192.168.100.20"]'
```

### Почему не bind-mount `./data`

OpenClaw 2026.9.x пишет файлы через `@openclaw/fs-safe`: временный файл → `rename` → `fstat`
по открытому дескриптору. На bind-mount Docker Desktop/Windows (gRPC-FUSE) последний шаг даёт
`ENOENT`, и падают миграции (`doctor --session-sqlite import`) и любые атомарные записи.
Named volume лежит на ext4 внутри VM, там проблемы нет.

### Владелец файлов при правке с хоста

Файл, сохранённый с хоста через временный файл с переименованием (PyCharm «Use safe write»,
часть редакторов), становится `root:root` — gateway его прочитает, но записать не сможет.
Правка «на месте» (Notepad, VS Code) владельца сохраняет. Если что-то стало `root`:

```powershell
docker exec -u root openclaw-builder chown -R node:node /home/node/.openclaw
```

## Прокси и доверенные адреса

- `gateway.trustedProxies` в `openclaw.json` — **только** адрес nginx `192.168.100.20`.
  Подсеть `192.168.100.0/24` ломает атрибуцию: хост виден из сети Docker как `192.168.100.1`,
  вся цепочка `X-Forwarded-For` считается доверенной, клиентский IP не извлекается,
  gateway отвечает `403 proxy_attribution_required`.
- `gateway.controlUi.allowedOrigins` содержит `http://localhost:18790` и `http://127.0.0.1:18790`.
- Переменные `OPENCLAW_GATEWAY_TRUSTED_PROXIES` и `OPENCLAW_GATEWAY_BIND` в compose OpenClaw
  **не читает** (из env поддерживаются только `OPENCLAW_GATEWAY_TOKEN`, `_PASSWORD`, `_PORT`, `_URL`).

## Почта из агента

`data\workspace\send_mail.py` отправляет письмо через SMTP (SSL, порт 465) с параметрами
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` из `.env` (для Gmail — пароль приложения).
Инструкция для агента — раздел «Отправка почты» в `data\workspace\AGENTS.md`.

Проверка вручную:

```powershell
docker exec openclaw-builder python3 /home/node/.openclaw/workspace/send_mail.py you@example.com "test" "hello"
```

## Обновление образа

```powershell
docker compose pull
docker compose up -d
docker exec openclaw-builder openclaw doctor --fix --non-interactive
```

Если после обновления gateway пишет «requires session store migration» и уходит в перезапуск:

```powershell
docker compose stop openclaw
docker compose run --rm --no-deps --entrypoint openclaw openclaw doctor --session-sqlite dry-run
docker compose run --rm --no-deps --entrypoint openclaw openclaw doctor --session-sqlite import
docker compose up -d
```

## Смена токена gateway

1. Сгенерировать новый (48 hex) и записать в `.env` как `OPENCLAW_GATEWAY_TOKEN`.
2. Обновить `gateway.auth.token` в `data\openclaw.json` тем же значением.
3. `docker compose up -d --force-recreate openclaw` — обычный `up -d` может лишь перезапустить
   контейнер со старым окружением.
4. В браузере ввести новый секрет.

## Расчётный движок invest-calc (сайдкар)

Отдельный сервис `calc` в этом же compose: детерминированные расчёты для инвестиционного дозора (numpy/pandas/scipy, FastAPI). Подробности, эндпоинты и проверка — `calc/README.md`. Порт на хосте 127.0.0.1:18791, внутри сети — `http://calc:8000`.
