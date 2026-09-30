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

## Отчёт исполнителя

Исполнитель: облачная сессия Claude Code, 30.09.2026. Базовая проверка: `pip install -r calc/requirements.txt`,
`python -m pytest calc/tests -q` — 116 passed, 16 skipped (пропуски — тесты, которым нужен workspace/тег S0). Для инструмента
доустановлен `ruamel.yaml` (он уже был зависимостью хост-инструмента по docstring; в `calc/requirements.txt` не добавлен, тесты
профиля делают `importorskip`). После изменений: **119 passed, 17 skipped** (+3 теста; тест валидатора пропускается без
workspace). С `INVEST_WORKSPACE=<клон ai_investment_system>`: 129 passed, 6 skipped, 1 failed — `test_workspace_after_migration_passes`
(тест валидатора, не этого PR) падает одинаково и на `main`: клон workspace неглубокий, тега `S0` в нём нет.

### Что сделано

- `calc/tools/migrate_artifacts_v1_0_1.py` → инструмент 1.1.0 (`TOOL_VERSION`; `SCHEMA_VERSION` остаётся 1.0.5): профиль legacy spacex
  MIG-SPCX-01…19 (перечень правил и источник каждого значения — в docstring), `SKIP_FOLDERS` пуст, `SPCX_FOLDERS = {"spacex"}`.
  Профиль идёт ПЕРЕД общими правилами MIG-1xx (они применяются к результату профиля без изменений). Архитектура та же, что у
  общих правил: эталон в памяти (`spcx_migrate_docs`) + построчный патч (`spcx_patch_yaml`; state.json дамп-идемпотентен →
  дамп), патч обязан совпасть с эталоном (И2), перенесённое в `_legacy/` сверяется с эталоном переноса. Если профиль отказал
  хоть в одном файле — папка не пишется целиком. Существующий `_legacy/` не перезаписывается (отличие → ошибка).
- Тесты (`calc/tests/test_migrate_artifacts.py`): синтетическая копия старого формата (5 файлов, CRLF в triggers/mpc как у
  реального spacex, каждый класс ошибок из постановки), `test_spcx_profile_migrates_idempotent_and_neutral` (а без workspace, б,
  в; сверка transition_triggers с двумя намеренными расхождениями), `test_spcx_profile_validator_pass` (а: валидатор в процессе,
  до — fail, после — pass, 0/0), `test_spcx_profile_refuses_without_evidence_and_scope` (биржа не выдумывается — отказ без
  записи; г: профиль только для spacex, spacex больше не пропускается), `test_spcx_source_class_rules`. Существующие тесты не менялись.

### Применение к ai_investment_system (portfolio/spacex)

Сухой прогон: `spacex full_model изменено: states.yaml, kpis.yaml, triggers.yaml, mpc_inputs.yaml, state.json | _legacy: 5 файлов`,
сверка transition_triggers — расхождений нет. `--apply --only spacex` → повторный сухой прогон: `изменено: — | без изменений: 5`
(идемпотентность). Диф: kpis +157/−, mpc_inputs 31, state.json 108, states.yaml 225, triggers.yaml 161 строк (288+/394−), плюс
`portfolio/spacex/_legacy/{states_legacy_notes.yaml, kpis_legacy.yaml, triggers_legacy.yaml, mpc_inputs_legacy.yaml, state_legacy.json}`.
Валидатор папки (artifact_validator 1.8.1, schema 1.0.5), до: `pass: False`, 248 ошибок схемы, 35 целостности (в постановке 250 —
у меня 248 при той же раскладке); после:
`{"summary": {"folders": 1, "pass": 1, "fail": 0}, "folder": {"profile": "full_model", "schema_errors": 0, "integrity_errors": 0,
"integrity_warnings": 0, "pass": true}, "integrity": []}` — по файлам 0/0/0/0/0.
Нейтральность на реальных данных (против HEAD): оси и множества состояний, тексты критериев (= прежние definition), текущие
состояния, KPI (last_value, last_date, formula), триггеры (condition, transition, axis, status, action, window), scenario_state
(state, since, evidence), наблюдения (kpi_id, period_end, value, verified) — совпадают.

### Принятые трактовки

1. **condition_provenance**: в постановке — `owner_judgment` для порогов стратегии владельца, но enum схемы v1.0.5 для
   `triggers[].condition_provenance` — только `model_assumption | normative_rule | null` (`owner_judgment` не пройдёт валидатор).
   Поле обязательно только у триггеров с `transition` (24 шт., SPCX-E-10…E-33) — проставлено общим правилом `model_assumption`,
   как во всех папках. Ценовые/календарные пороги стратегии (P-, C-) переходов не имеют — поле им не требуется и не добавлялось.
2. **value_type** всех 10 KPI — `actual` (прошлые даты, раскрытые/расчётные факты); прогнозов компании среди KPI нет,
   неоднозначных по правилу (guidance/прогноз/outlook в name/formula) — 0.
3. **source_class** по Source Policy v1.0 (по идентичности документа): SEC-хостинговый релиз `earningsreleaseq22608042.htm` →
   `issuer_ir_release` (KPI-01…03, 05…09; общий `source_class()` отнёс бы его к `regulatory_filing` — поэтому отдельная функция
   профиля, другие папки не затронуты); 10-Q `spcx-20260630.htm` → `regulatory_filing` (KPI-04); KPI-10 (мультипликатор
   invest-calc, source_url Yahoo + StockAnalysis) → `market_data_provider`; источники осей: релиз → `issuer_ir_release`,
   Yahoo и StockAnalysis → `market_data_provider`.
4. **provenance KPI**: `derived_fact` при арифметической формуле с делением (KPI-01 YoY, KPI-07 маржа, KPI-10 мультипликатор),
   остальные — `verified_fact` (формула описывает раскрытую строку отчёта); `verified: null` у всех KPI (дозор не проверял).
5. **provenance наблюдений** state.json — как у KPI с тем же kpi_id; существующий `verified: true` не менялся (И1: значения не
   переписываются; «null там, где нет verification_run_id» применено только к отсутствующим полям). У наблюдения KPI-10 `run_id`
   — прогон invest-calc, не дозора: в `verification_run_id` его превращать нельзя (ART-REF-026 требует отчёт `_verify/`) — → `note`.
6. **scenario_state[ось].verified** — схема требует boolean (null недопустим) → `false` + `verified_note` (протокольной
   проверки не было; `true` без run_id — legacy_unlinked по ART-REF-027).
7. **info_log** старой формы: `summary` = `text` дословно, `kind` — прежний, где был, иначе `legacy_trigger_log` (3 записи);
   в форме схемы (`timestamp, kind, summary`, additionalProperties: false) места для `trigger_id`/`level` нет → `_legacy`.
8. **triggers.meta**: `yahoo_symbol: SPCX` — из `meta.price_source` (`…/chart/SPCX`); `exchange: NASDAQ` — из state.json
   `events_reported` (включение в Nasdaq-100, источник ir.nasdaq.com; включение требует листинга на Nasdaq). Без такого факта
   профиль отказывает. `automations.spacex-report-check.covers` — строка «E-10..E-19, E-25..E-29 (…)» раскрыта в явный список
   15 ID, исходная строка — в `note` записи.
9. **SPCX-E-34…E-38**: у них есть `axis: Capital_Intensity` (в постановке — «проверить, что нет axis/from/to»), но нет from/to,
   и в notes прямо «Не переход состояния»: удалён только ключ `transition: null`, `axis` сохранён (И1).
10. **mpc_inputs**: `semantics` → `driver_exposure_semantics` чистым переименованием (driver_scale → scale, rule → direction_rule,
    provenance); `driver_vector_provenance: model_assumption` с комментарием о переносе экспертной оценки v1.0 — примечание
    комментарием, т. к. поле — const без соседнего note; дата в комментарии не указана (в постановке 20.09, в source_artifact файла 21.09).
11. `current_evidence` осей — дословно `current_snapshot.evidence`; `source_refs` — только URL из `current_snapshot.source`
    (у Starship источник — текст «SEC earnings release; FAA ATCSCC operational plan» без URL → `source_refs: []`, не выдумано).
    Новые ключи `sources`: `SPCX_EARNINGS_RELEASE`, `SPCX_YAHOO_QUOTE`, `SPCX_STOCKANALYSIS`, `as_of` = states.as_of (как MIG-102).

### Перенесено в portfolio/spacex/_legacy/ (дословно, с комментариями исходника)

- `states_legacy_notes.yaml`: `source_policy`, `transition_semantics`, `evaluation_rule`, `legacy_compatibility`; по осям —
  `current_snapshot` (state, date, evidence, source) и `transition_triggers`.
- `kpis_legacy.yaml`: `derived_checks`, `data_quality`, `kpi_observation_rule`, `supporting_metrics`, `calculated_metrics`;
  KPI-05 `last_yoy_growth`, KPI-06 `last_yoy_change`, KPI-10 `last_value_raw` и `inputs` (у KPI-10 `notes` → `note`, а у
  KPI-01…09 `last_value_raw` → `note: 'last_value_raw: …'`).
- `triggers_legacy.yaml`: meta `reference_price_in_strategy` (с комментарием), `target_average_price`, `position_plan`;
  `pilot` трёх автоматизаций; по триггерам `strategy_ref`, `probability_in_strategy`, `notes_kpi`, `supporting_metrics`,
  `calculated_metrics`.
- `mpc_inputs_legacy.yaml`: `methodology_refs`, `status`, `model_notes`.
- `state_legacy.json`: `calc_inputs`, `gaap_profit_quarters`, `trigger_id`/`level` пяти записей info_log.

### Сверка transition_triggers ↔ triggers.yaml

Расхождений нет: для всех пяти осей перечисленные ID (AI E-10…E-14, Starlink E-15…E-19, Starship E-20…E-24, Capital_Intensity
E-25…E-29, Valuation E-30…E-33) есть в triggers.yaml как переходы той же оси, и других переходов по этим осям нет.

### Открытые вопросы интегратору

1. `condition_provenance: owner_judgment` не допускается схемой v1.0.5 (см. трактовку 1) — если пороги стратегии владельца
   нужно маркировать отдельно, нужен патч схемы (enum) или отдельное поле.
2. KPI-10: класс `market_data_provider` по source_url, хотя значение — производное (цена × акции из 10-Q / выручка из
   отчётов); Source Policy для производных метрик класса не определяет. StockAnalysis политикой не назван — отнесён к
   поставщикам рыночных данных.
3. `scenario_state.verified = false` у всех пяти осей — после первого прогона дозора по осям заменить на связанный
   `verification_run_id`.
4. `kind: legacy_trigger_log` — новое значение словаря kind (схема словарь не ограничивает); при желании переклассифицировать
   три записи (две — расчёты, одна — проверка события E-21) вручную.
5. `exchange: NASDAQ` выведен из факта включения в Nasdaq-100 — подтвердить.
