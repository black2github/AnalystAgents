# company_mc v2 — обобщённый условный Монте-Карло компании: запись решения

Дата: 2026-09-22. Статус: принят к реализации (владелец: «начинай обобщённый движок MC»).
Нормативные источники (workspace `methodology/`): MC_Calibration_Archetypes v1.0 + Rules v1.1 + Schema patch v1.1,
Joint_Simulation_Layer v1.0 (+ Mapping Examples), SPCX_Conditional_Monte_Carlo_Specification v1.0, ответ LLM по MC-run 1
(gap-метрики, I1–I5, bridge_dependent, robustness).

## 1. Зачем и что меняется

`conditional_mc` 1.0.x привязан к трём сегментам SPCX (AI / Connectivity / Space), к ключам фактов Q2 2026, к одной форме
маржи (узлы D3) и использует один ранг для «старт → долгосрочный рост», для мультипликаторов Y3/Y5/Y8 и для узлов маржи
(интерпретации I1–I3), что искусственно создаёт «вечного победителя». Нужен движок, который:
- читает сегменты, форму маржи и правила оценки из калибровочного YAML (любая компания, три архетипа);
- заменяет общий ранг структурой «латентный фактор + идиосинкратический шок» с загрузками (Archetypes §2.1);
- умеет кусочную оценку с сохранением `valuation_basis` на путь и пометкой `bridge_dependent`;
- считает `RV_Growth_Gap` и `Price_Expectation_Gap` (диагностика, без авто-переходов);
- принимает внешние пути драйверов (Joint Simulation Layer) через `driver_parameter_mapping`, а без них работает standalone
  в базовом сценарии BASE (probability 1.0), генерируя root-факторы сам по той же спецификации;
- сохраняет обратную совместимость: калибровка SPCX v1.0 запускается через адаптер без правок файла.

Legacy `conditional_mc` не трогаем (правило «новое поведение — рядом, по умолчанию выключено»); `company_mc` — новая модель
реестра. Нормативный прогон SPCX …-861006 остаётся историческим фактом; переход SPCX на v2 — отдельное решение после
сверки паритета.

## 2. Сценарии жизненного цикла (Д-26)

1. **Калибровка от LLM** (после MC v1.1): YAML v2 с `archetype`, `revenue_model.segments`, `margin_model.method`,
   `valuation`, `dependencies`, `joint_simulation`, `driver_parameter_mapping` → `POST /run company_mc` → run-файл в
   `portfolio/_runs/`, сводка в `state.json → calc_runs`, уведомление владельцу.
2. **SPCX v1.0** (историческая калибровка) → адаптер `from_spcx_v1` → тот же движок; паритет с 1.0.1 по медиане CAGR 5Y в
   допуске ±3 п.п. (структура зависимостей другая — точного совпадения не ожидается; расхождение документируется).
3. **Совместный прогон** (Optimizer/MPC): внешний генератор даёт `driver_paths` (n × drivers × quarters) с общим `path_id`;
   движок применяет mapping и возвращает `RelativeValue_h` по путям (не только сводку).
4. **Stability Test**: вызов с `knockout: [driver_id]` (снятие structural_support) или `adverse_driver_stress` — детерминированный
   сдвиг параметров калибровки перед прогоном; сам тест — отдельная модель позже.
5. **Robustness v1.1**: возмущения из калибровки; pass = знак медианы CAGR 5Y сохранён ≥75% И |ΔP(2x,5Y)|, |ΔP(loss>30%,5Y)|
   ≤ допуска (по умолчанию 0.10) в ≥75% прогонов.

## 3. Инварианты

- Один `seed` + одна калибровка + одна версия = один результат (детерминизм; антитетические пары).
- Текущая цена используется только для доходности и gap-метрик, не для выбора распределений (anti-circularity §10).
- Каждое прогнозное число берётся из калибровки; движок не имеет встроенных чисел, кроме технических (chunk, допуски).
- Ни один параметр не использует ранг другого параметра напрямую: только через латентный фактор с загрузкой < 1.
- `valuation_basis` сохраняется на путь; доля путей с `revenue_bridge`/`fallback` на горизонте → `bridge_dependent`.
- Отрицательный FCF на горизонте никогда не умножается на мультипликатор: срабатывает `negative_fcf_fallback`.
- Матрица корреляций факторов проверяется на PSD; починка логируется.

## 4. Схема калибровки v2 (то, что читает движок)

```
archetype: mature_positive_margin | capital_intensive_transition | pre_service_or_milestone_driven
simulation: {paths, seed, antithetic_variates, store_summary_quantiles, horizons_years: [3,5,8]}
revenue_model:
  segments:
    <Имя>: {base_revenue_quarterly: <$>, initial_growth: <dist>, long_run_growth_y8: <dist>,
            growth_half_life_years: <float>, latent_loading: {growth: 0.7}}
margin_model:
  method: mean_reverting_positive_margin      # архетип A
    current_margin, terminal_margin_Y5: <dist>, terminal_margin_Y8: <dist> | {rule: y5_plus_normal, sigma}, half_life_years,
    shock_sigma, shock_persistence, lower_bound, upper_bound
  method: direct_fcf_nodes                    # архетип B
    nodes: {Y1, Y2, Y3: <dist>; Y4_terminal_fraction: <dist>; Y5_terminal_margin: <dist>; Y8_terminal_margin: <dist>|{rule}}
    monotonic: true
  method: ocf_capex_decomposition             # архетип B (предпочтительный при данных)
    ocf_margin_nodes: {Y1..Y5: <dist>, Y8: <dist>|rule}, capex_revenue_nodes: {Y1..Y5: <dist>, Y8: <dist>|rule}
valuation:
  Y3: {basis: FCF_multiple | revenue_bridge | EBITDA_multiple, multiple: <dist>}
  Y5: {basis: ..., multiple: <dist>}
  Y8: {basis: ..., multiple: <dist>}
  negative_fcf_fallback: {basis: revenue_bridge, multiple: <dist>}
  ebitda_margin_over_fcf: <float>   # только для EBITDA_multiple: EBITDA ≈ FCF-маржа + добавка (модельное допущение)
dependencies:
  latent_factors: [growth, margin, valuation]
  factor_correlations: {growth__margin: rho, growth__valuation: rho, margin__valuation: rho}
  default_loading: 0.7   # доля дисперсии параметра от общего фактора = loading²
market_path_model: {quarterly_log_price_noise: {annualized_sigma}, valuation_mean_reversion_half_life_years}
reverse_valuation_ref: {implied_revenue_cagr_5y, discount_rate}   # для RV_Growth_Gap / Price_Expectation_Gap
robustness_tests: {Scenario_Robustness: {perturbations: {...}, delta_tolerance: 0.10}}
joint_simulation / driver_parameter_mapping   # срез 2
milestone_model                                # срез 3
<dist> = {distribution: triangular|pert|truncated_normal|lognormal|deterministic, ...параметры...}
```

## 5. Нарезка

| Срез | Содержание | Тесты |
|---|---|---|
| 1 | ядро: распределения, сегменты из калибровки, архетипы A и B (обе формы), латентные факторы, кусочная оценка + fallback, gap-метрики, robustness v1.1, адаптер SPCX v1.0 | ppf-распределения; A: маржа стремится к терминальной; B: монотонность узлов; fallback при FCF<0; детерминизм; паритет SPCX ±3 п.п.; gap-метрики на синтетике |
| 2 | Joint Simulation Layer: root AR(1) + корреляции + драйверы (стандартизация) + `driver_parameter_mapping` (transforms additive_pp, multiplicative_pct, log_multiplier) + structural_support/knockout + внешние `driver_paths` с общим path_id | дисперсия драйверов ≈ 1; same path → same shocks у двух компаний; knockout ≠ 1σ-сдвиг |
| 3 | архетип C: вехи с условными вероятностями, окна, зависимости, ветви; cash burn до сервиса; кусочная оценка с `milestone_state` на путь | вероятности вех воспроизводятся; basis per path; ASTS-подобная синтетика |
| 4 | выход `RelativeValue_h` по путям для Optimizer/MPC; convergence; документация; SPCX переводится на v2 отдельным решением | сходимость; сравнение сводки с путями |

Срез 1 реализуется сейчас; 2–4 — по одному, каждый с тестами и отдельным коммитом (по запросу владельца).

## 6. Журнал реализации

- **Срез 1 — 22.09.2026, company_mc 2.0.0.** Паритет на калибровке SPCX v1.0 (адаптер, 20k путей, seed 20260920):
  медианный CAGR 3/5/8Y v1 −22.67 / −14.86 / −3.76% против v2 −22.71 / −14.92 / −3.87%; P(loss>30%) 0.966 / 0.964;
  P(loss>50%) 0.671 / 0.671; ES5 −0.731 / −0.737; медианная стоимость Y5 $900.6 / $897.5 млрд. Расхождения в пределах
  0.1–0.6 п.п. при другой структуре зависимостей (латентные факторы вместо общего ранга): медианы определяются модами
  распределений. Gap-метрики SPCX: RV_Growth_Gap +49.2 п.п. (76.3% требуемого vs 27.1% медианного роста выручки),
  Price_Expectation_Gap 3.78× (текущая стоимость к дисконтированной медиане Y5 при r = 11%). Тесты 6 (всего 40/40).
- **Срез 2 — 22.09.2026, company_mc 2.1.0 + joint_layer 1.0.0.** Root-факторы: стационарные AR(1) N(0,1) с MVN(0,R_root)
  (Cholesky; PSD-починка логируется), драйверы = Σ λ·F + σ_idio·ε со стандартизацией к unit variance (теоретическая
  дисперсия λᵀRλ + σ²), драйвер без mapping — идиосинкратический. Общий путь без передачи массивов: шоки чанка k
  генерируются SeedSequence([global_seed, k]) — одинаковы у всех компаний при одинаковом chunk (path_id = k·chunk + i).
  Сценарий: driver_overrides mean_shift_sigma / volatility_multiplier (BASE по умолчанию). driver_parameter_mapping:
  stochastic_targets с effective_shock (lag + EMA half-life, нормировка к σ=1) — рост сегмента по кварталам (additive_pp /
  multiplicative_pct / log_multiplier), узлы маржи (additive_pp, шок в квартале горизонта), мультипликаторы Y3/Y5/Y8
  (multiplicative_pct / log_multiplier); неизвестные цели (capacity_model.*) → mapping_warnings, не применяются.
  Knockout = сдвиг целевых распределений на shifts из stability.knockout (или −contribution); not_applicable — без
  изменений; adverse_driver_stress = константный шок driver_sigma. Интерпретация движка: эффект на скалярные узлы берётся
  в квартале горизонта (Y3→q12, Y5→q20, Y8→q32). Тесты 5 (стационарность и корреляция корней, unit variance и
  воспроизводимость шоков, lag/decay, сценарий/knockout/adverse, требование joint_layer_spec + детерминизм); всего 45/45.
  Паритет SPCX без mapping не изменился (−14.92% / 0.964 / −0.737 / $897.5 млрд).
- Очередь: срез 3 (архетип C — вехи, кусочная оценка с milestone_state), срез 4 (RelativeValue по путям для MPC/Optimizer,
  сходимость, перевод SPCX на v2 отдельным решением).
