# invest-calc — сайдкар расчётного движка инвестиционного дозора

Отдельный контейнер в том же compose, что OpenClaw. OpenClaw — датчики, триггеры и расписание;
invest-calc — детерминированные расчёты (Монте-Карло, valuation, портфель). LLM не считает.

- Образ: `python:3.12-slim` + numpy, pandas, scipy, fastapi (см. `requirements.txt`).
- Код моделей: `./calc/engine` — монтируется в контейнер как `/app/engine` (только чтение),
  правки видны сразу; пересборка образа нужна только при смене зависимостей.
- Данные: тот же named volume, что у OpenClaw, смонтирован в `/data`; workspace агента —
  `/data/workspace-invest`. Записи прогонов пишутся в `portfolio/_runs/<run_id>.json`.
- Сеть: только `app_net` (192.168.100.30, имя `calc`); наружу порт 8000 опубликован как
  `127.0.0.1:18791` для отладки с хоста.
- Пользователь процесса: uid 1000 (как `node` в OpenClaw), чтобы файлы прогонов были доступны агенту.

Проверка с хоста (PowerShell):

    Invoke-RestMethod http://127.0.0.1:18791/health
    Invoke-RestMethod -Method Post -ContentType 'application/json' -Uri http://127.0.0.1:18791/run `
      -Body '{"model":"selftest","inputs":{"years":5,"mu":0.15,"sigma":0.35},"seed":42}'

Из агента OpenClaw (exec): `curl -s http://calc:8000/health`.

Сборка/запуск: `docker compose up -d --build calc`. Тесты движка на хосте: `C:\Python312\python.exe -m pytest calc\tests -q`.
