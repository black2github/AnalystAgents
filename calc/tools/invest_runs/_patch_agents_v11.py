"""AGENTS.md дозора: раздел сверки → Dozor Verification Protocol v1.1 (оси, события, квалификатор, N кварталов, label_ru)."""
from pathlib import Path

p = Path("C:/openclaw-lab/data/workspace-invest/AGENTS.md")
raw = p.read_bytes(); crlf = b"\r\n" in raw; s = raw.decode("utf-8").replace("\r\n", "\n")
a = s.index("## Сверка по первоисточникам"); b = s.index("## Расчётный движок")
new = """## Сверка по первоисточникам (Dozor Verification Protocol v1.1, гейт G8)

Норматив: `methodology/Dozor_Verification_Protocol_v1.1.yaml` (реестр статусов с label_ru, правила KPI/осей/событий,
схема отчёта `output_report_schema`) и `methodology/Source_Policy_v1.0.yaml` (классы источников, guidance ≠ actual,
период дословно, технический доступ). v1.1 принят 22.09.2026 после первого живого прогона по NBIS
(run verify-NBIS-20260922T201443Z). Ниже — как это исполняется в этом workspace.

1. **Роль.** Дозор не второй аналитик: он независимо открывает источник и воспроизводит число. `source_url` и
   EvidencePack от LLM — подсказка, где искать, а не доказательство. Один отчёт, один run_id, один гейт: KPI
   (`items[]`), текущие состояния осей (`axis_items[]`) и факты событий E-/X-триггеров (`event_items[]`).
2. **Статус на KPI** (ровно один): `verified_match`, `verified_match_with_normalization`, `mismatch_value`,
   `mismatch_period`, `mismatch_semantics` (прогноз записан как факт и т.п.), `formula_mismatch`,
   `source_not_allowed`, `source_unavailable_technical`, `source_conflict`, `not_disclosed`, `not_found`.
   Три разных вещи: `not_found` (полный набор доступных документов просмотрен, значения нет) ≠ `not_disclosed`
   (установлено, что компания не раскрывает отдельно) ≠ `source_unavailable_technical` (403/усечённый fetch/сеть
   после повторов). Явный пример протокола: «есть цель 5 GW на конец года, факта законтрактованной мощности на дату
   отчёта нет» → `not_found` (прогноз не доказывает ни факт, ни нераскрытие).
3. **Сверка числа.** Разрешены только детерминированные преобразования: % ↔ доля, тыс./млн/млрд, б.п. ↔ п.п.,
   заявленные единицы. Совпадение — если после нормализации кандидат попадает в интервал округления
   опубликованного числа (± половина последнего знака). Для `derived_fact` — пересчёт формулы из независимо
   подтверждённых слагаемых, допуск 0.1%. Границы (`lower_bound`/`upper_bound`) сравниваются как границы;
   диапазон «50–60%» из одной фразы — достаточная цитата, нужны оба конца. Период — часть факта: «within 50 days»
   не подтверждает «trailing 90 days» (`mismatch_period` даже при совпавшем числе).
   **Расходится только квалификатор** (источник «approximately», кандидат `exact`) при совпавших числе, типе,
   единице и периоде → `verified_match_with_normalization`, в `normalization.steps` строка
   `qualifier: source=approximate, candidate=exact`, `qualifier_patch_suggested: true`, `patch_required: false`
   (форму наблюдения потом правит интегратор, не дозор).
4. **«N кварталов подряд» дозор не считает.** Он подтверждает наблюдение и его `period_end`; последовательность
   вычисляет детерминированная проверка перехода по истории `kpi_observations`. Если критерий состояния сам требует
   N периодов, `state_supported` возможен только со ссылкой `history_evaluation_ref`, иначе
   `state_pending_verification`.
5. **Технический отказ — не отсутствие факта.** SEC: только с User-Agent (см. выше), при 403 — повтор и
   альтернативный официальный URL архива; усечённый fetch — взять полный документ через `exec`/curl. Если всё равно
   недоступно — `source_unavailable_technical`, KPI/ось не правятся, итог `BLOCKED_TECHNICAL`.
6. **Оси (`axis_items[]`).** Подтверждается именно записанное текущее состояние `scenario_state[axis]` по критерию
   из states.yaml: ссылки на подтверждённые KPI этого же отчёта (`kpi_item_refs`), `criterion_checks` по каждому
   условию критерия, для качественных осей (`evidence_type: qualitative_primary_source`) — прямая цитата
   первоисточника. Статусы: `state_supported` → `verified: true` + `verification_run_id`; `state_not_supported` →
   `verified: false` + run_id + PATCH_REQUIRED; `state_pending_verification` → `verified: false` + run_id (без
   правки, только если каноническое состояние уже `pending_verification`); `evidence_unavailable_technical` /
   `evidence_conflict` → флаг не трогать, run_id не писать, итог BLOCKED. Старый `verified: true` без
   `verification_run_id` — `legacy_unlinked`: сохраняется, но подтверждением по протоколу не считается.
7. **События (`event_items[]`).** Факт для -E-/-X-триггера: `event_confirmed_primary` (разрешённый первичный
   источник) или `event_confirmed_two_media` (нет первичного — два НЕЗАВИСИМЫХ СМИ первого ряда; перепечатки одной
   новости — один источник), `event_unconfirmed`, `event_contradicted` (PATCH_REQUIRED), `source_unavailable_technical`.
   Событие подтверждает ФАКТ, не переход и не действие (`fact_only: true`): дозор может создать/связать запись в
   `events_reported[]` с `verification_run_id`, но НИКОГДА не создаёт `fired` и не исполняет действие.
8. **Отчёт прогона** — иммутабельный файл `portfolio/<ticker>/_verify/<run_id>.json` по `output_report_schema`
   (`protocol_version` "1.1.0", run_id `verify-<ticker>-<YYYYMMDDTHHMMSSZ>`, `as_of` — момент прогона в date-time;
   это НЕ as_of документа-источника, а `recorded_at` у источника — момент фиксации ссылки в реестре). Перед записью
   отчёт проверяется валидатором сайдкара: `POST /run {"model": "artifact_validator", "inputs": {"mode":
   "dozor_report", "report": <json>, "folders": ["<папка>"]}}` — правила DZR-001..010 (тикер, kpi_id, оси и состояния,
   trigger_id, fact_only, runtime_verified/patch_required по реестру статусов, согласованность summary и итога).
9. **Что пишется в state.json** (и только это): `kpi_observations[]` — новое наблюдение (`value` число|null,
   `value_type`, `observation_qualifier`, `unit`, `period_end`, `source_url`, `provenance`, `verified` по реестру
   статусов: `true` для verified_match*, `false` для mismatch*/source_not_allowed, `null` для технического отказа,
   конфликта и not_found, `verification_run_id`); `scenario_state[axis].verified` + `verification_run_id` по п. 6;
   `events_reported[]` с `verification_run_id` по п. 7; поле `verification` = {run_id, as_of, overall_status};
   строка в `info_log`. Канонические KPI в kpis.yaml, критерии состояний, условия триггеров и ID дозор НЕ
   переписывает: расхождение → Decision Request владельцу с текстом «PATCH_REQUIRED: <id>: <статус>, найдено
   <значение> (<период>, <url>)».
10. **Итог прогона** по старшинству: `BLOCKED_SOURCE_CONFLICT` > `BLOCKED_TECHNICAL` > `PATCH_REQUIRED` >
    `PASS_WITH_DECLARED_PENDING` (нерешённые KPI/оси/события уже заявлены как pending) > `PASS`.
11. **Русские названия статусов в сообщениях владельцу** (замечание владельца 22.09): в Telegram статус пишется
    по-русски, оригинал протокола — в скобках, например `подтверждено (verified_match)`. Нормативный словарь — поле
    `label_ru` в `status_registry` протокола (KPI, оси, события, итоги): «подтверждено», «подтверждено с
    нормализацией», «расхождение значения», «расхождение периода», «расхождение смысла (прогноз ≠ факт)», «формула
    не сходится», «источник не допускается», «источник недоступен технически», «источники противоречат», «компания
    не раскрывает», «в источнике не найдено»; оси — «текущее состояние подтверждено / не подтверждается / ожидает
    подтверждения», «свидетельство недоступно технически», «свидетельства по состоянию противоречат»; события —
    «событие подтверждено первоисточником / двумя СМИ первого ряда», «событие не подтверждено», «событие
    опровергнуто»; итоги — «пройдено», «пройдено, есть заявленные ожидания», «нужна правка», «заблокировано
    технически», «заблокировано: источники противоречат». В файлах отчёта и state.json — только оригинальные коды.

"""
s = s[:a] + new + s[b:]
p.write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))
print("AGENTS.md: раздел сверки → v1.1", "crlf" if crlf else "lf")
