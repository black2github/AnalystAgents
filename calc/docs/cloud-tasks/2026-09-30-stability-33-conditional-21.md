# Задание для облачной сессии Claude Code — репозиторий black2github/AnalystAgents (лаборатория invest-calc)

Дата постановки: 30.09.2026. Автор постановки: интегратор (Claude Code, локальная сессия). Заказчик: владелец.
Результат: один pull request в `main` с двумя независимыми частями (можно двумя коммитами). Ничего сверх описанного.

## 0. Контекст, которого в репозитории нет (читать первым)

Движок `calc/engine/*` — детерминированные расчёты инвестиционного дозора (Монте-Карло компаний по совместным путям
общих драйверов, портфель, оптимизатор, тест устойчивости). Он исполняется в сайдкаре Docker (`calc/app.py`, реестр моделей
`calc/engine/registry.py` перезагружает модули при импорте). В облаке сайдкара и данных нет: единственная проверка — тесты
`python -m pytest calc/tests -q` (сейчас 123 passed, 2 skipped; синтетические калибровки и пути строятся фикстурами в
`calc/tests/test_company_mc.py`, `test_portfolio_paths.py`, `test_portfolio_optimizer.py`). Нормативные документы (спецификации
IMMA) живут в другом репозитории (workspace агента); нужные выдержки приведены ниже дословно, других источников не требуется.

Правила репозитория (обязательны):
- Язык комментариев, docstring, сообщений об ошибках и тестов — русский, стиль как в соседнем коде (см. docstring модулей).
- Для поля `provenance` в русских текстах пишется «происхождение», не калька с английского (имя поля не меняется).
- Новые зависимости не добавлять (`calc/requirements.txt` без изменений). Только numpy/scipy, что уже есть.
- Существующие выходы движка при отсутствии новых входов должны совпадать побитно (нормативные прогоны не пересчитываются):
  ни один существующий тест не меняется по смыслу; допускается только добавление тестов.
- Версия модуля (`VERSION` и первая строка docstring) поднимается на MINOR при новой возможности: portfolio_paths 1.3.0 → 1.4.0,
  portfolio_stability 1.2.1 → 1.3.0, joint_layer 1.3.0 → 1.4.0, company_mc 2.4.2 → 2.5.0. В docstring модуля — краткое
  описание новых входов/выходов, как сделано для прежних версий.
- Не трогать `calc/tools/**`, `calc/docs/**` (кроме этого файла — можно дописать раздел «Отчёт исполнителя»), `docker-compose.yml`.
- Коммиты — только своих файлов (явный `git add -- <файлы>`), без коммита артефактов тестов и `__pycache__`.
- Числа не выдумывать: где нет данных — статус `not_testable_*` в выходе, а не значение по умолчанию.

## Часть 1. Stability Test §3.3 — чувствительность к вероятностям сценариев (portfolio_stability 1.3.0, portfolio_paths 1.4.0)

### 1.1 Норматив (Scenario_Engine_Specification v1.1, раздел 8 «Stability Test §3.3», дословно)

> При заданных owner probabilities:
> 1. Для каждого non-BASE scenario: `p_s * 0.75` и `p_s * 1.25`, затем renormalize всех сценариев включая BASE.
> 2. `one-scenario-up`: scenario с максимальным `B_s` получает `+0.10` absolute probability; 10 п.п. пропорционально забираются
>    у всех остальных сценариев по их текущей probability. Если donor mass <0.10, perturbation invalid, silent clipping запрещён.
> 3. После каждого perturbation пересчитываются weighted mixture, ScenarioConcentration и Optimizer.
>
> Если probability pending, эти тесты возвращают `not_testable_pending_owner_probability`.

Определения из того же норматива, уже реализованные в `calc/engine/portfolio_paths.py`:
- смесь сценариев (§6): scenario-specific пути с ОБЩИМИ `path_id` объединяются как взвешенная эмпирическая распределённость,
  BASE = остаток `1 − Σ p_s` (`_run_mixture`);
- бремя сценария `B_s = p_s · max(0, ES5_BASE − ES5_s)` на горизонте Y5 (`_run_mixture` → `scenario_impacts[sid]["adverse_ES_burden_B"]`),
  ScenarioConcentration по варианту «а» — функция `scenario_concentration(burdens)`;
- разбиение путей под оптимизатор (`mixture_export`): `mixture_ranges(n, probs, order)` даёт отрезки `path_id` по сценариям
  (k_s = round(p_s·N), округление вниз до чётного, BASE — остаток), `_export_mixture` собирает файл-смесь на компанию: r3/r5/r8/
  maxdd5 = конкатенация отрезков из файлов сценариев в порядке BASE, затем сценарии по списку. Именно на таких файлах-смеси
  работает `portfolio_optimizer` (он принимает `data=` — уже загруженные пути `{ticker: load_paths(...)}`).

Сейчас в `portfolio_stability.run` блок §3.3 — заглушка:
`scen_sens = {"status": "not_applicable", "reason": "единственный сценарий BASE — вероятности сценариев не определены"}`.

### 1.2 Что сделать

1. `portfolio_paths`: вынести сборку смеси в память в функцию `build_mixture_data(loaded: dict[str, dict[str, dict]], probs: dict,
   order: list, n: int) -> dict[str, dict]` (loaded = `{scenario_id: {ticker: load_paths(...)}}`, результат — `{ticker: data}` того
   же вида, что `load_paths`, с `meta` от BASE и `meta["mixture"] = {ranges, probabilities}`) и использовать её в `_export_mixture`
   (побитно тот же результат, что раньше — проверить тестом на существующей фикстуре `test_mixture_export_partition`).
2. `portfolio_stability`: новый необязательный вход
   ```
   "stability": {..., "scenario_probabilities": {
        "scenarios": [{"id": "S1", "probability": 0.10 | null, "paths_files": {tk: .npz}}, ...],   # non-BASE, общие path_id с BASE
        "base_paths_files": {tk: .npz},                                                            # BASE-пути (без сценария)
        "order": ["S1", ...] | null                                                                # порядок отрезков, по умолчанию как в списке
   }}
   ```
   Семантика: `paths_files` теста при этом — файлы-смеси на центральных вероятностях (как сейчас в нормативных заходах), центральный
   прогон не меняется. Семейство прогонов `"scenario"` (добавить в `FAMILIES`; частичный перепрогон `families: ["scenario"]` должен
   работать). Возмущения по §3.3 ровно в этом порядке и с этими метками:
   - `p:<sid>:x0.75`, `p:<sid>:x1.25` для каждого non-BASE сценария: p'_s = f·p_s, затем ВСЕ вероятности (включая BASE = 1 − Σ)
     делятся на сумму (renormalize);
   - `p:up10:<sid*>`: sid* — сценарий с максимальным B_s на ЦЕНТРАЛЬНЫХ весах (B_s считать по центральным весам на
     scenario-specific путях: ES5 портфеля на BASE-путях и на путях сценария, `B_s = p_s·max(0, ES5_BASE − ES5_s)`); p'_{sid*} =
     p + 0.10; у всех остальных сценариев, включая BASE, пропорционально их текущим вероятностям забирается 0.10 суммарно; если
     суммарная масса доноров < 0.10 — возмущение `valid: false, reason: "donor_mass_below_0.10"`, оптимизатор не запускается,
     никакого усечения. При равенстве максимумов B_s — первый по `order`. Если все B_s = 0 — `p:up10` не строится
     (`status: "no_adverse_scenario"` в отчёте).
   Для каждого валидного возмущения: собрать смесь в памяти (`build_mixture_data` на первых `max_paths` путях, как остальные
   семейства), посчитать взвешенную смесь §6 на центральных весах (median CAGR 5Y, ES5, P(loss>30 %)), `scenario_concentration`
   по бременам на центральных весах при новых вероятностях, затем оптимизатор на смеси (`_opt`, тёплый старт от центра, как у
   других семейств). Если во входах теста есть `scenario_constraints` (portfolio_optimizer 1.1.0), в возмущённом прогоне
   передать те же ограничения, но с возмущёнными `probability` у сценариев (они влияют на применимость p_min и на бремя).
   Исполнение — через существующий механизм задач (`add(...)`, `_apply_ops`, пул процессов): новая операция
   `("mixture", probs)`; рабочий процесс загружает файлы BASE и сценариев один раз (`_worker_init`), результат не должен
   зависеть от числа процессов (`workers`).
   Выход `scenario_sensitivity`:
   ```
   {"status": "evaluated" | "not_testable_pending_owner_probability" | "not_applicable",
    "central_probabilities": {sid: p, "BASE": p_base}, "burdens_at_central": {sid: B_s}, "max_burden_scenario": sid | null,
    "perturbations": [{"label", "probabilities": {...}, "valid": bool, "reason": str | null,
                       "mixture_Y5": {"median_CAGR", "expected_shortfall_5pct", "P_loss_gt_30pct"} | null,
                       "scenario_concentration": {...} | null,
                       "optimizer": {"weights", "dry_powder", "feasible", "median_CAGR_5Y", "ES5"} | null,
                       "max_abs_weight_shift_vs_central": float | null}],
    "max_abs_weight_shift_vs_central": float | null,
    "rule": "<одной строкой §3.3>"}
   ```
   Если хотя бы одна `probability` = null → `status: "not_testable_pending_owner_probability"`, прогонов нет. Если вход
   `scenario_probabilities` не задан → прежний `not_applicable` с прежним текстом (обратная совместимость).
   Валидные прогоны семейства `scenario` входят в популяцию §5–6 (частота включения, разброс весов) наравне с однофакторными
   (проверить, что `feasibility_rate`, `inclusion_frequency_by_asset`, `binding_constraint_frequency` их учитывают);
   `perturbation` (конфигурация в выходе) и `assumptions_hash` должны отражать новые параметры.
3. Тесты (`calc/tests/test_portfolio_stability.py`, при необходимости `test_portfolio_paths.py`): синтетические сценарные пути —
   копии BASE-файлов фикстуры с масштабированием r3/r5/r8 (пример `_shocked` в `test_portfolio_optimizer.py`; масштабировать все
   горизонты, `path_id`/`meta` сохранить). Проверить: (а) `build_mixture_data` побитно равна файлам `_export_mixture`;
   (б) метки и число возмущений (2 на сценарий + одно up10), renormalize даёт Σ = 1 с точностью 1e-12; (в) `up10` выбирает
   сценарий с максимальным B_s и при p_BASE+Σ прочих < 0.10 (например, один сценарий с p = 0.95) даёт `valid: false` без
   усечения; (г) при `probability: null` — статус pending и ни одного прогона; (д) частичный перепрогон `families: ["scenario"]`;
   (е) результат совпадает при `workers: 1` и `workers: 2`; (ж) без входа — прежний `not_applicable`; (з) все существующие тесты
   проходят без изменений.

## Часть 2. §21 Confirmed-phase conditional run (joint_layer 1.4.0, company_mc 2.5.0)

### 2.1 Норматив (Scenario_Engine_Specification v1.1, разделы 3.1, 20, 21, дословно)

> ### 3.1 effective_from
> Поддерживаются: `fixed_quarter`: один квартал от `t0`; `triangular_quarter`: целочисленный draw `min/mode/max`; anchor `t0`
> или `phase:<phase_id>`; при phase-anchor draw является offset от фактического старта указанной фазы. Timing draw выполняется
> один раз на `(scenario_id, path_id, phase_id)` и общий для всех компаний данного path.
>
> ## 20. Runtime `scenario_state` … `scenario_state` is a runtime artifact. It does not mutate the calibration YAML.
>
> ## 21. Confirmed-phase conditional run
> A confirmed phase has priority over its calibration timing distribution **only in a conditional scenario run**.
> If phase `P` is confirmed at observed date/quarter:
> 1. define conditional-run `t0` as the quarter containing `P.confirmed_at`;
> 2. materialize `P.effective_from` as `fixed_quarter: 0` for that conditional run;
> 3. phases before `P` are historical and excluded from the forward horizon;
> 4. later phases retain their accepted timing distributions, re-anchored to the observed start of `P` where their anchor
>    references `P` or a later phase;
> 5. compute the conditional scenario-specific portfolio picture with scenario probability `1.0`;
> 6. do **not** overwrite owner probabilities or the normal mixture; mixture update is a separate owner decision/review.
> Unconditional normative runs remain bitwise governed by the original calibration timing distributions.

Как это устроено в движке сейчас: `joint_layer.phase_starts(scenario, n, quarters, seed)` разыгрывает старт каждой фазы на путь
(fixed/triangular, anchor t0 или phase:<id>, старт ≥ quarters = фаза вне горизонта), `scenario_schedule` строит расписание
(ramp от предыдущего активного состояния к целевому состоянию фазы, plateau по `duration_quarters`, decay к BASE) и требует
монотонность стартов фаз по путям (нестрогую: равные старты допустимы). Сценарий подаётся в `company_mc.run` через
`inputs["scenario"]` (dict калибровки сценария с `phases`), диагностика — `outputs["scenario_phases"]`, `outputs["scenario_mode"]`
(`phased` | `constant_legacy_non_normative` | `BASE`), в meta файла путей — `scenario` (id). Пункт 5 норматива (картина портфеля
при probability 1.0) уже обеспечен: `portfolio_paths` и `portfolio_optimizer 1.1.0` считают метрики на scenario-specific путях;
вероятности и смесь (п. 6) движок не трогает. Требуется только п. 1–4: преобразование сценария для условного прогона.

### 2.2 Что сделать

1. `joint_layer.conditional_scenario(scenario: dict, confirmed_phase_id: str) -> tuple[dict, dict]` — чистая функция, возвращает
   преобразованную копию сценария и отчёт преобразования. Семантика (принятая интегратором трактовка §21, зафиксировать в docstring):
   - `t0` условного прогона = квартал подтверждения; в движке это просто квартал 0 горизонта (дата не нужна);
   - фаза P: `effective_from = {kind: fixed_quarter, quarter: 0, anchor: t0}`; `ramp_quarters`, `duration_quarters`,
     `decay_quarters`, `driver_overrides`, корреляции — без изменений;
   - фазы ДО P (исторические): не удаляются из списка (иначе ramp P пойдёт от BASE, а не от достигнутого состояния), а
     «схлопываются» в квартал 0: `effective_from = fixed_quarter 0 / t0`, `ramp_quarters = 0`, `duration_quarters = until_next_phase`,
     `decay_quarters = 0`. Тогда на квартале 0 активно целевое состояние последней исторической фазы, и P ramp'ится от него, как
     если бы история уже произошла. В отчёте — `historical_phases: [ids]`, `state_at_t0: <phase_id последней исторической | "BASE">`;
   - фазы ПОСЛЕ P: распределения `effective_from` сохраняются как есть; anchor `phase:<id>`, где id — P или более поздняя фаза,
     работает автоматически (старт P теперь 0 на всех путях); anchor `t0` или `phase:<историческая>` — распределение сохраняется,
     но отсчитывается от нового t0 (то есть от квартала 0, `anchor: t0`); при этом если на пути старт такой фазы получается
     раньше старта P (то есть < 0 невозможно, но равен 0 — возможно), оставить как есть (нестрогая монотонность допустима);
   - `scenario_id` не менять; добавить в копию поле `conditional_run = {confirmed_phase: P, historical_phases: [...],
     rule: "Scenario_Engine_Specification v1.1 §21"}`; если `confirmed_phase_id` нет среди фаз — `ValueError` с понятным текстом.
2. `company_mc.run`: новый необязательный вход `inputs["conditional_run"] = {"confirmed_phase": "<phase_id>"}` (действует только
   вместе с `inputs["scenario"]` фазового вида, иначе `ValueError`). Перед построением совместных шоков сценарий заменяется на
   `conditional_scenario(...)`; в выходах: `scenario_mode = "conditional_confirmed_phase"`, новый блок
   `outputs["conditional_run"] = {confirmed_phase, historical_phases, state_at_t0, materialized_effective_from: {P: fixed_quarter 0},
   rule}`, `scenario_phases` — по преобразованному сценарию; в meta файла путей (`store_paths`) и в сводке — `scenario`
   остаётся id сценария, добавляется `conditional_run: "<P>"` (чтобы файлы условного прогона не путались с нормативными;
   `portfolio_paths` и оптимизатор проверяют выравнивание по `global_seed`/`chunk`/`path_id`, условные пути выровнены с BASE, это
   должно остаться так — проверить тестом, что `path_id` и meta.global_seed совпадают с BASE-прогоном тех же входов).
   Розыгрыши timing по (seed, scenario_id, phase_id) не менять — нормативные прогоны побитно прежние.
3. Тесты (`calc/tests/test_joint_layer.py`, `test_company_mc.py`, при необходимости `test_conditional_mc.py` не трогать — это другой
   модуль): (а) `conditional_scenario`: P = вторая из трёх фаз → первая схлопнута в 0 с ramp 0, P fixed 0, третья сохранила
   распределение и anchor; `phase_starts` на преобразованном сценарии даёт старт P = 0 на всех путях и старт третьей ≥ 0 с тем же
   распределением смещений, что у исходного anchor phase:P; (б) инвариант: если P — первая фаза и у неё уже `fixed_quarter 0`,
   условный прогон `company_mc` побитно равен безусловному (те же r3/r5/r8, `np.array_equal`); (в) при P = более поздней фазе
   условная медиана Y5 отличается от безусловной, а `path_id`/`global_seed` совпадают с BASE; (г) отсутствие P среди фаз и
   `conditional_run` без фазового сценария → `ValueError`; (д) безусловные прогоны существующих тестов не изменились.

## 3. Критерии приёмки PR

- `python -m pytest calc/tests -q` — всё зелёное (ожидается ≥ 123 passed + новые), без предупреждений о новых зависимостях.
- Версии и docstring модулей обновлены; в docstring `portfolio_stability` строка про §3.3 заменена на описание реализации.
- Описание PR: что сделано по частям 1 и 2, принятые трактовки (особенно схлопывание исторических фаз и anchor t0 у поздних
  фаз), список новых входов/выходов, как проверено. Русский язык. В конце этого файла — раздел «## Отчёт исполнителя» с теми же
  пунктами и открытыми вопросами интегратору, если трактовка норматива вызывала сомнения.
- Никаких изменений вне `calc/engine/{portfolio_paths,portfolio_stability,joint_layer,company_mc}.py`, `calc/tests/*` и этого файла.
