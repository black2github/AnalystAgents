# Задание для облачной сессии Claude Code — миграция артефактов SpaceX (SPCX) на Company Artifact Schema v1.0.5

Дата постановки: 30.09.2026. Автор постановки: интегратор (Claude Code, локальная сессия). Заказчик: владелец.
Два репозитория в одной сессии (добавить второй через «+» в селекторе репозиториев):
- `black2github/AnalystAgents` (лаборатория: движок `calc/engine`, инструменты `calc/tools`, тесты `calc/tests`);
- `black2github/ai_investment_system` (workspace агента invest: `portfolio/<тикер>/…`, `methodology/…`; ветка **master**).
Результат: два pull request (по одному в каждый репозиторий), связанные ссылками в описаниях. Ничего сверх описанного.

## 0. Контекст, которого в репозиториях нет (читать первым)

Папка `portfolio/spacex/` (тикер SPCX) — самая первая компания системы (сентябрь 2026), её пять артефактов написаны ДО принятия
Company Artifact Schema v1.0.x и до сих пор в «старом формате». Остальные 15 папок компаний (`portfolio/nbis`, `nvda`, `asml`, …)
были мигрированы детерминированным инструментом `calc/tools/migrate_artifacts_v1_0_1.py` (правила MIG-101…122) и проходят
валидатор папки `calc/engine/artifact_validator.py` (гейт G5). Инструмент миграции сознательно пропускает spacex
(`SKIP_FOLDERS = {"spacex"}`, «старый формат, отдельное решение») — это и есть отдельное решение.

Текущий результат валидатора для `portfolio/spacex` (сайдкар, 30.09.2026): `pass: False`, 250 ошибок схемы и 35 ошибок целостности.
Раскладка по файлам (сообщения валидатора, сгруппированы):
- `states.yaml` (78): 27× поле `definition` не разрешено и 27× нет обязательного `criteria` (у состояний осей); 5× не разрешены
  `current_snapshot`, `transition_triggers`, 5× нет `current`, `current_evidence`, `source_refs` (у осей); в корне не разрешены
  `evaluation_rule`, `legacy_compatibility`, `source_policy`, `transition_semantics`.
- `kpis.yaml` (53): у 10 KPI нет `value_type`, `source_class`, `verified`, `provenance`; 7× не разрешено `last_value_raw`; в корне
  не разрешены `calculated_metrics`, `data_quality`, `derived_checks` и т. п.
- `triggers.yaml` (83): 29× нет `condition_provenance`; 18× не разрешено `strategy_ref`, 4× `probability_in_strategy`, 6× `notes_kpi`,
  4× `calculated_metrics`; 5× `None is not of type 'object'` (пустые `transition` у SPCX-E-34…E-38 → целостность ART-REF-002
  «состояние None не найдено в оси Capital_Intensity», 10 ошибок).
- `mpc_inputs.yaml` (3): нет `schema_version`, нет `driver_vector_provenance`; не разрешены `methodology_refs`, `model_notes`,
  `semantics`, `st…`.
- `state.json` (33): 10× нет `provenance` (у наблюдений KPI), 6× не разрешены `level`, `text`, `trigger_id` и 6× нет `summary`
  (записи info_log/events в старой форме), 5× нет `verified`, 3× нет `kind`; не разрешены `calc_inputs`, `gaap_profit_quarters`.
- Целостность (35): ART-REF-002 ×10 (пустые transition), ART-REF-005 ×10 (`source_class` None), ART-REF-008 ×10 (`value_type` None),
  ART-REF-016 ×5 (`schema_version` отсутствует во всех пяти файлах, требуется '1.0.5').

Нормативные источники — в репозитории workspace: `methodology/Company_Artifact_Schema_v1.0.5.yaml` (JSON Schema Draft 2020-12 по
файлам + `integrity_rules` + `field_catalog` + `legacy_reference_coverage`), `methodology/Source_Policy_v1.0.yaml` (классы
источников `source_class`, guidance ≠ actual), `methodology/Dozor_Verification_Protocol_v1.2.1.yaml` (форма `kpi_observations`,
`verified`, `verification_run_id`). Эталон уже мигрированной папки того же архетипа (капиталоёмкий переход, есть `states.yaml` с осями
и переходами) — `portfolio/nbis/` и `portfolio/rklb/`; смотреть на них как на образец формы.

Инварианты миграции (из docstring `migrate_artifacts_v1_0_1.py`, обязательны и здесь):
- И1 семантическая нейтральность: ни один канонический ID (KPI, ось, состояние, триггер), состояние оси, условие триггера, значение
  KPI или дата НЕ меняются — меняется только форма и добавляются обязательные поля;
- И2 построчный патч без переформатирования (комментарии, кавычки, порядок ключей, CRLF/LF сохраняются); результат построчного патча
  должен совпасть с эталонной миграцией в памяти;
- И3 идемпотентность (повторный запуск ничего не меняет); И4 файл пишется только при изменении.

Правила репозиториев (обязательны): русский язык комментариев/docstring/сообщений/тестов; для поля `provenance` в русских текстах
пишется «происхождение», не калька с английского; новые зависимости не добавлять; коммиты — только своих файлов (явный
`git add -- <файлы>`); версия инструмента миграции поднимается (SCHEMA_VERSION остаётся 1.0.5, версия самого инструмента/docstring —
добавить раздел про spacex-профиль); числа не выдумывать.

## 1. Что сделать в AnalystAgents (инструмент)

1. Добавить в `calc/tools/migrate_artifacts_v1_0_1.py` профиль миграции «legacy spacex» (правила с ID `MIG-SPCX-01…` в docstring
   и коде), снять spacex из `SKIP_FOLDERS`, оставить общие MIG-правила применимыми после spacex-профиля. Каждое правило — одно
   преобразование формы, с указанием, откуда берётся значение:
   - `schema_version: '1.0.5'` во все пять файлов (как у остальных папок; место — как в мигрированных файлах nbis);
   - `states.yaml`: `definition` → `criteria` (текст критерия — из `definition`, дословно, без переписывания; если `definition` —
     строка, то `criteria` в той форме, что в схеме и у nbis; если требуется структура критериев с полями — заполнить из текста
     `definition` только там, где это чистое переименование, иначе `criteria` из текста + пометка `legacy_text: true` там, где схема
     это позволяет — проверить по `field_catalog`); осям добавить `current` (из `current_snapshot`, если он там, иначе из
     `state.json → scenario_state[axis].state`), `current_evidence`, `source_refs` (из `current_snapshot`/`transition_triggers`, если
     есть, иначе пустой список с `verified: null` — не выдумывать источники); лишние корневые ключи (`evaluation_rule`,
     `legacy_compatibility`, `source_policy`, `transition_semantics`) — перенести дословно в `legacy_notes`/разрешённый схемой ключ
     свободного текста, если такой есть в `field_catalog`; если нет — вынести в `portfolio/spacex/_legacy/states_legacy_notes.yaml`
     (новый файл вне валидируемых пяти) со ссылкой в комментарии; `transition_triggers` осей → сверить с `triggers.yaml` (условия
     переходов живут ТОЛЬКО в triggers.yaml) и убрать из states.yaml, ничего не потеряв (если в triggers.yaml нет соответствующего
     триггера — НЕ создавать его, а записать расхождение в отчёт исполнителя);
   - `kpis.yaml`: `value_type` — `actual` для значений с `last_date` в прошлом и источником SEC/релиз, `company_guidance` там, где
     из `name`/`formula`/комментария явно следует прогноз компании (иначе `actual`; неоднозначные — перечислить в отчёте);
     `source_class` — по `Source_Policy_v1.0.yaml` из поля `source` (SEC → `regulatory_filing`, Investor Relations → класс релиза
     эмитента по политике, FAA → регулятор, Yahoo/StockAnalysis → рыночные данные/агрегатор по политике; точные имена enum — из
     схемы); `verified: null` (ещё не проверялось дозором), `provenance: verified_fact` только если значение цитирует
     первоисточник по `source_url`, иначе `derived_fact` с `formula` (у KPI с формулой) — не выдумывать; `last_value_raw` →
     перенести в `note`/разрешённое поле (значение не терять); корневые `calculated_metrics`, `data_quality`, `derived_checks` — как
     для states.yaml (разрешённый ключ или `_legacy/`);
   - `triggers.yaml`: `condition_provenance` — `owner_judgment` для порогов стратегии владельца (реестр SPCX формировался
     владельцем в сентябре 2026), `model_assumption` для порогов, помеченных как расчётные; `strategy_ref`, `probability_in_strategy`,
     `notes_kpi`, `calculated_metrics` — перенести в разрешённые поля (`note`/`legacy`) или `_legacy/`, ничего не терять; пустые
     `transition: null` у SPCX-E-34…E-38 — ЭТО НЕ ПЕРЕХОДЫ: убрать ключ `transition` (валидатор трактует `None` как переход с
     состояниями None), проверив, что у этих триггеров нет `axis`/`from`/`to`;
   - `mpc_inputs.yaml`: `schema_version`, `driver_vector_provenance` (значение `model_assumption` с `note` «перенос из v1.0
     экспертной оценки 20.09.2026», если в файле нет иного указания источника), лишние ключи — как выше;
   - `state.json`: наблюдения KPI — добавить `provenance` (`verified_fact`, если у наблюдения есть `source_url` первоисточника и
     `verified: true`; иначе `derived_fact` при наличии формулы; иначе `verified_fact` с `verified: null` — сверить с правилом
     Dozor Protocol v1.2.1 и `field_catalog`; не выдумывать), `verified` (null там, где нет `verification_run_id`), `kind` у записей,
     где схема его требует; записи info_log/events в старой форме (`level`, `text`, `trigger_id`) → форма схемы с `summary`
     (текст из `text`, id триггера — в разрешённое поле); `calc_inputs`, `gaap_profit_quarters` — перенести в разрешённое
     расширение или `_legacy/state_legacy.json`, значения не терять.
2. Тесты (`calc/tests/test_migrate_artifacts.py`): (а) spacex-профиль на синтетической копии старого формата (минимальный фикстурный
   набор из пяти файлов, воспроизводящий каждый класс ошибок выше) → после миграции валидатор папки в процессе
   (`artifact_validator.run({"folders": [<путь>], "workspace": <корень workspace>}, 0)`; схемы валидатор берёт из
   `<workspace>/methodology`) даёт `pass: True`; (б) идемпотентность; (в) семантическая нейтральность: множества ID (KPI, оси,
   состояния, триггеры), значения `last_value`, даты и условия триггеров до/после совпадают; (г) остальные папки (фикстуры
   существующих тестов) не меняются (существующие тесты — без изменений).
3. Полный `python -m pytest calc/tests -q` зелёный (в облаке тесты, зависящие от workspace, пропускаются — это ожидаемо; поэтому
   тест (а) должен работать на фикстуре, а не на реальной папке).

## 2. Что сделать в ai_investment_system (данные)

1. Применить инструмент к реальной папке: `python <AnalystAgents>/calc/tools/migrate_artifacts_v1_0_1.py <корень workspace> --apply
   --only spacex` (сначала сухой прогон без `--apply`, диф в отчёт). Затем валидатор папки в процессе (как в тесте) —
   `pass: True`, 0 ошибок схемы и целостности; вывод валидатора приложить в отчёт исполнителя.
2. Ничего, кроме `portfolio/spacex/{states.yaml,kpis.yaml,triggers.yaml,mpc_inputs.yaml,state.json}` и, при необходимости,
   `portfolio/spacex/_legacy/*`, не менять. Файлы `portfolio/spacex/mc_calibration_*.yaml`, `calibration_v1.0.yaml`, `thesis.md`,
   `watch-price.js`, `_verify/*` не трогать. `state.json` пишется целиком как обычный JSON (без Markdown-экранирования), ключи не
   переименовывать сверх схемы.
3. Запись в `STATUS.md` НЕ добавлять (её сделает интегратор при приёмке).

## 3. Критерии приёмки
- PR в AnalystAgents: профиль MIG-SPCX-01…, тесты (а)–(г), docstring обновлён, полный pytest зелёный.
- PR в ai_investment_system: пять файлов spacex проходят валидатор папки (`pass: True`), диф семантически нейтрален (проверяемо по
  тесту (в) и по глазам: ID, значения, даты, условия неизменны), ничего не потеряно (перенесённое — в разрешённых полях или
  `_legacy/`).
- Описание каждого PR — по-русски: что сделано, принятые трактовки (особенно `value_type`, `source_class`, `provenance` наблюдений),
  список перенесённого в `_legacy/`, расхождения `transition_triggers` ↔ `triggers.yaml`, как проверено. В конце этого файла —
  раздел «## Отчёт исполнителя» с теми же пунктами и открытыми вопросами интегратору.
- Никаких изменений вне `calc/tools/migrate_artifacts_v1_0_1.py`, `calc/tests/test_migrate_artifacts.py`, этого файла и
  `portfolio/spacex/**` во втором репозитории.
