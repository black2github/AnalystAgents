"""Тесты миграции артефактов к Company Artifact Schema v1.0.1 (calc/tools/migrate_artifacts_v1_0_1.py).
Синтетическая часть не зависит от workspace; живая часть берёт папки из workspace (INVEST_WORKSPACE или путь по умолчанию)
и пропускается, если workspace недоступен."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import migrate_artifacts_v1_0_1 as mig  # noqa: E402

WS = Path(os.environ.get("INVEST_WORKSPACE", "C:/openclaw-lab/data/workspace-invest"))
SCHEMA = WS / "methodology" / "Company_Artifact_Schema_v1.0.5.yaml"
S0 = "S0"  # git-тег снимка ДО миграции (workspace-invest df6029d); живые тесты читают исходные файлы из него


def _git_show(rel: str) -> bytes | None:
    import subprocess
    r = subprocess.run(["git", "-C", str(WS), "-c", "safe.directory=*", "show", f"{S0}:{rel}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


needs_ws = pytest.mark.skipif(not SCHEMA.exists() or _git_show("portfolio/nbis/kpis.yaml") is None, reason="workspace или тег S0 недоступны")


# ------------------------------------------------------------------ синтетика
def test_split_value_forms():
    assert mig.split_value(">40") == (40, {"observation_qualifier": "lower_bound"})
    assert mig.split_value("<0.01") == (0.01, {"observation_qualifier": "upper_bound"})
    assert mig.split_value([0.5, 0.6]) == (None, {"observation_qualifier": "range", "value_range": {"min": 0.5, "max": 0.6}})
    assert mig.split_value(5.14) == (5.14, {})
    assert mig.split_value(None) == (None, {})
    assert mig.split_value("текст") == ("текст", {})     # НЕсрабатывание: произвольная строка не трогается


def test_source_class_rules():
    assert mig.source_class("https://www.sec.gov/Archives/edgar/data/1/2/x-20260630.htm", None) == "regulatory_filing"
    assert mig.source_class("https://www.sec.gov/Archives/edgar/data/1/2/tm_ex99-1.htm", None) == "issuer_ir_release"
    assert mig.source_class("https://www.sec.gov/.../presentationinvestor.htm", "SEC 6-K") == "issuer_investor_presentation"
    assert mig.source_class("https://query1.finance.yahoo.com/v8/finance/chart/NBIS", None) == "market_data_provider"
    assert mig.source_class(None, "SEC") == "regulatory_filing"
    assert mig.source_class(None, "IR") == "issuer_ir_release"
    assert mig.source_class(None, None) == "other_primary"


def _docs():
    return {
        "states.yaml": {"version": "1.0", "as_of": "2026-09-21", "ticker": "TST", "semantics": {"thresholds_provenance": "model_assumption", "primary_only": True},
                        "sources": {"A": "https://www.sec.gov/x-20260630.htm", "B": {"url": "https://ir.test.com/q2", "type": "IR release"}},
                        "axes": {"Ax": {"states": {"S1": {}, "S2": {}}, "current": "S1"}}},
        "kpis.yaml": {"ticker": "TST", "source_artifact": "from_imma/TST.yaml", "critical_kpis": [
            {"id": "TST-KPI-01", "source": "SEC", "last_value": ">40", "thresholds": {"green": ">=50", "yellow": ">=40", "red": "<40"}},
            {"id": "TST-KPI-02", "source": "IR", "last_value": 1, "value_type": "lower_bound", "thresholds": {"green": "=1", "red": "=0"}},
            {"id": "TST-KPI-03", "source": "IR", "last_value": [1, 2], "thresholds": {"green": "x", "red": "y"}}]},
        "triggers.yaml": {"meta": {"ticker": "TST", "horizon": 2030}, "automations": {"_note": "нет"},
                          "triggers": [{"id": "TST-E-01", "transition": {"from": "S1", "to": "S2"}, "axis": "Ax"}, {"id": "TST-P-01", "class": "price"}]},
        "mpc_inputs.yaml": {"ticker": "TST", "driver_exposure_vector": {}},
        "state.json": {"notes": "n", "price": {"last": 10.0}, "kpi_observations": [{"kpi_id": "TST-KPI-01", "value": ">40"}], "conviction": {"tag": True}},
    }


def test_migrate_docs_semantics_and_idempotence():
    d0 = _docs()
    d1 = mig.migrate_docs(d0)
    assert d0["kpis.yaml"]["critical_kpis"][0]["last_value"] == ">40"          # вход не изменён
    k = d1["kpis.yaml"]["critical_kpis"]
    assert k[0]["last_value"] == 40 and k[0]["observation_qualifier"] == "lower_bound" and k[0]["value_type"] == "actual" and k[0]["source_class"] == "regulatory_filing"
    assert k[1]["value_type"] == "actual" and k[1]["observation_qualifier"] == "lower_bound" and k[1]["thresholds"]["binary"] is True
    assert k[2]["last_value"] is None and k[2]["value_range"] == {"min": 1, "max": 2} and "binary" not in k[2]["thresholds"]   # зоны «x/y» не бинарны — НЕсрабатывание MIG-106
    sem = d1["states.yaml"]["semantics"]
    assert sem["numeric_thresholds_provenance"] == "model_assumption" and "thresholds_provenance" not in sem and sem["evidence_required"] is True and sem["primary_only"] is True
    assert d1["states.yaml"]["sources"]["A"] == {"url": "https://www.sec.gov/x-20260630.htm", "source_class": "regulatory_filing", "as_of": "2026-09-21"}
    assert d1["states.yaml"]["sources"]["B"]["source_class"] == "issuer_ir_release" and d1["states.yaml"]["sources"]["B"]["type"] == "IR release"
    tr = d1["triggers.yaml"]
    assert tr["profile"] == "full_model" and tr["automations"] == {} and tr["automations_note"] == "нет" and tr["meta"]["horizon"] == "2030"
    assert tr["triggers"][0]["condition_provenance"] == "model_assumption" and tr["triggers"][0]["fired"] == [] and "condition_provenance" not in tr["triggers"][1]
    assert tr["rules"] == {"evidence_required": True, "pending_verification_blocks_transition": True, "trigger_not_decision": True}
    assert tr["meta"]["price_at_registry"] == 10.0 and tr["meta"]["source_artifact"] == "from_imma/TST.yaml" and tr["meta"]["position"] is None
    sj = d1["state.json"]
    assert sj["notes"] == ["n"] and sj["kpi_observations"][0]["value"] == 40 and sj["conviction"]["provenance"] == "owner_judgment" and sj["scenario_state"] == {}
    assert all(d["schema_version"] == mig.SCHEMA_VERSION for d in d1.values())
    assert mig.migrate_docs(d1) == d1                                          # идемпотентность эталона


def test_registry_only_profile():
    d = {"triggers.yaml": {"meta": {"ticker": "X"}, "triggers": [{"id": "X-E-01", "transition": {"from": "a", "to": "b"}}]}, "state.json": {}}
    out = mig.migrate_docs(d)
    assert out["triggers.yaml"]["profile"] == "registry_only" and "fired" not in out["triggers.yaml"]["triggers"][0] and "rules" not in out["triggers.yaml"]
    assert out["state.json"]["notes"] == [] and out["state.json"]["kpi_observations"] == []


# ------------------------------------------------------------------ живой прогон на копии workspace
def _copy(tmp_path, names):
    """Папки компаний из снимка S0 (до миграции) — тесты не зависят от текущего состояния workspace."""
    for n in names:
        for fn in mig.FILES:
            data = _git_show(f"portfolio/{n}/{fn}")
            if data is not None:
                (tmp_path / "portfolio" / n).mkdir(parents=True, exist_ok=True)
                (tmp_path / "portfolio" / n / fn).write_bytes(data)
    return tmp_path


@needs_ws
def test_live_patch_equals_reference_and_is_idempotent(tmp_path):
    from jsonschema import Draft202012Validator as V
    ws = _copy(tmp_path, ["nbis", "asts", "net", "6506"])
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    before = {n: {fn: (ws / "portfolio" / n / fn).read_bytes() for fn in mig.FILES if (ws / "portfolio" / n / fn).exists()} for n in ["nbis", "asts", "net", "6506"]}
    reports = {r["folder"]: r for r in (mig.migrate_folder(f, apply=True) for f in mig.iter_folders(ws, None))}
    assert all(not r["errors"] for r in reports.values()), reports
    assert reports["nbis"]["profile"] == "full_model" and reports["6506"]["profile"] == "registry_only"
    for n in ["nbis", "asts", "net", "6506"]:
        for fn, s in schema["files"].items():
            if (ws / "portfolio" / n / fn).exists():
                errs = [e.message for e in V(s).iter_errors(mig.load_plain(ws / "portfolio" / n / fn))]
                assert errs == [], (n, fn, errs[:3])
    # байты: переводы строк и BOM сохранены; комментарии на месте
    for n, files in before.items():
        for fn, old in files.items():
            new = (ws / "portfolio" / n / fn).read_bytes()
            assert (b"\r\n" in old) == (b"\r\n" in new) and not new.startswith(b"\xef\xbb\xbf")
            assert old.count(b"#") <= new.count(b"#")
    # И1: ID, состояния, условия
    for n in ["nbis", "asts", "net"]:
        old = yaml.safe_load(before[n]["triggers.yaml"].decode("utf-8")); new = yaml.safe_load((ws / "portfolio" / n / "triggers.yaml").read_text(encoding="utf-8"))
        assert [(t["id"], t.get("condition")) for t in old["triggers"]] == [(t["id"], t.get("condition")) for t in new["triggers"]]
    # И3: второй прогон ничего не меняет
    again = [mig.migrate_folder(f, apply=False) for f in mig.iter_folders(ws, None)]
    assert all(not r["changed"] and not r["errors"] for r in again)


@needs_ws
def test_live_no_change_without_apply(tmp_path):
    ws = _copy(tmp_path, ["nvda"])
    old = (ws / "portfolio" / "nvda" / "kpis.yaml").read_bytes()
    r = mig.migrate_folder(ws / "portfolio" / "nvda", apply=False)
    assert "kpis.yaml" in r["changed"] and (ws / "portfolio" / "nvda" / "kpis.yaml").read_bytes() == old


# ------------------------------------------------------------------ MIG-122 (Artifact Schema v1.0.5): история прогонов дозора
def _rep(run_id, kpi_id, last_value, value_range=None, verified=True):
    return {"run_id": run_id, "items": [{"kpi_id": kpi_id, "runtime_verified": verified, "candidate": {"last_value": last_value, "value_range": value_range}}]}


def test_mig122_collapse_seed_backfill_and_order():
    obs = [
        {"kpi_id": "K1", "period_end": "2026-06-30", "value": 3, "value_raw": "three", "verified": True},                      # legacy-строка run1 (без run_id)
        {"kpi_id": "K1", "period_end": "2026-06-30", "value": 3.0, "observation_qualifier": "exact", "verification_run_id": "verify-T-20260922T210122Z"},
        {"kpi_id": "K2", "period_end": "2026-06-30", "value": None, "value_range": {"min": 50, "max": 60}, "verification_run_id": "verify-T-20260922T210122Z"},
        {"kpi_id": "K1", "period_end": "2026-03-31", "value": 2.0, "verified": True},                                           # другой период — не дубликат
        {"kpi_id": "K3", "period_end": "2026-06-30", "value": 7.0, "verified": True},                                           # без прогона — история не выдумывается
    ]
    reports = [_rep("verify-T-20260922T201443Z", "K1", 3.0), _rep("verify-T-20260922T201443Z", "K3", 8.0),                     # K3: значение не совпало → не привязывать
               _rep("verify-T-20260923T000000Z", "K2", None, {"min": 50, "max": 60}), _rep("verify-T-20260920T000000Z", "K1", 3.0, verified=False)]
    out = mig.migrate_observations(obs, reports)
    assert [o["kpi_id"] for o in out] == ["K1", "K2", "K1", "K3"]                                                               # 3 и 3.0 — одно наблюдение
    k1 = out[0]
    assert k1["value"] == 3.0 and k1["observation_qualifier"] == "exact" and k1["value_raw"] == "three"                       # победила строка с прогоном, поля добраны
    assert k1["verification_run_ids"] == ["verify-T-20260922T201443Z", "verify-T-20260922T210122Z"] and k1["verification_run_id"] == "verify-T-20260922T210122Z"
    assert out[1]["verification_run_ids"] == ["verify-T-20260922T210122Z", "verify-T-20260923T000000Z"] and out[1]["verification_run_id"] == "verify-T-20260923T000000Z"
    assert "verification_run_ids" not in out[2] and "verification_run_ids" not in out[3]                                       # НЕсрабатывание: без связи — без истории
    assert mig.migrate_observations(out, reports) == out                                                                       # идемпотентность


@needs_ws
def test_mig122_live_nbis_history_from_immutable_reports():
    folder = WS / "portfolio" / "nbis"
    docs = {fn: mig.load_plain(folder / fn) for fn in mig.FILES if (folder / fn).exists()}
    out = mig.migrate_docs(docs, mig.load_verify_reports(folder))["state.json"]["kpi_observations"]
    assert len(out) == 11 and len({o["kpi_id"] for o in out}) == 11
    k1 = next(o for o in out if o["kpi_id"] == "NBIS-KPI-01")
    assert k1["verification_run_ids"] == ["verify-NBIS-20260922T201443Z", "verify-NBIS-20260922T210122Z"] and k1["verification_run_id"] == "verify-NBIS-20260922T210122Z"
    k11 = next(o for o in out if o["kpi_id"] == "NBIS-KPI-11")
    assert k11["verification_run_ids"] == ["verify-NBIS-20260922T210122Z"]                                                   # not_found в run1 → run1 не привязан


# ------------------------------------------------------------------ профиль legacy spacex (MIG-SPCX, инструмент 1.1.0)
# Синтетическая копия старого формата spacex: каждый класс ошибок валидатора из постановки 30.09.2026 воспроизведён
# (definition, current_snapshot/transition_triggers, корневые ключи, KPI без value_type/source_class/verified/provenance,
# last_value_raw, триггеры без condition_provenance, strategy_ref…, transition: null, pilot, covers-строка, mpc semantics,
# info_log старой формы, scenario_state без verified, calc_inputs). Сверка transition_triggers ↔ triggers.yaml содержит два
# намеренных расхождения (T-E-99 нет в реестре; T-E-12 — переход оси AI, не перечисленный в transition_triggers).
TAXONOMY_1_1 = ["AI_COMPUTE_DEMAND", "HYPERSCALER_CAPEX", "SEMICONDUCTOR_WFE", "ADVANCED_PACKAGING", "HBM_MEMORY", "EDA_DESIGN_COMPLEXITY",
                "CLOUD_SOFTWARE_DEMAND", "DATA_CENTER_POWER", "LAUNCH_ECONOMICS", "SATELLITE_CONNECTIVITY", "GOVERNMENT_DEFENSE", "INTEREST_RATES",
                "CAPITAL_MARKETS", "CHINA_REVENUE", "TAIWAN_SUPPLY", "ACQUISITION_INTEGRATION", "AI_CLOUD_PRICING", "HEALTHCARE_DEMAND",
                "DRUG_PIPELINE", "REIMBURSEMENT_PRICING", "BIOPHARMA_MANUFACTURING_CAPACITY", "PHARMA_REGULATION", "PATENT_EXCLUSIVITY",
                "ELECTRIFICATION_GRID", "UTILITY_CAPEX", "INDUSTRIAL_RESHORING", "AEROSPACE_CYCLE", "CONSUMER_CREDIT", "CRYPTO_CYCLE",
                "FINTECH_REGULATION", "DIGITAL_AD_DEMAND", "SPACE_REGULATION"]
SEC_ER = "https://www.sec.gov/Archives/edgar/data/1/2/earningsreleaseq22608042.htm"
SEC_10Q = "https://www.sec.gov/Archives/edgar/data/1/3/tst-20260630.htm"

SPCX_STATES = f"""# Вектор состояний TST (старый формат)
version: '1.1'
artifact: TST State Vector
as_of: '2026-09-20'
ticker: TST
purpose: Оси и состояния.
source_policy:
  primary:
  - SEC
  rule: 'Числовые условия проверяются по первичному источнику.

    '
axes:
  AI:
    name: AI compute
    states:
      A0:
        name: optionality
        definition: AI-направление существует, спрос не подтверждён.
      A1:
        name: validation
        definition: Есть подтверждённый спрос и растущая
          выручка.
    current_snapshot:
      state: A1
      date: '2026-09-20'
      evidence:
      - 'AI revenue Q2 = $2.5B, +247% YoY.'
      source: {SEC_ER}
    transition_triggers:
    - T-E-10
    - T-E-99
  Valuation:
    name: Valuation
    states:
      V0:
        name: Not assessed
        definition: Не рассчитана.
      V1:
        name: Demanding
        definition: Цена требует высокой устойчивости.
    current_snapshot:
      state: V1
      evidence:
      - Close = $150.
      source: https://finance.yahoo.com/quote/TST/; https://stockanalysis.com/stocks/tst/market-cap/
    transition_triggers:
    - T-E-20
    note: V1 — предварительно.
  Starship:
    name: Starship
    states:
      C0:
        name: Development
        definition: Разработка.
      C1:
        name: Suborbital validation
        definition: Успешная суборбитальная миссия.
    current_snapshot:
      state: C0
      evidence:
      - 'Flight 12: успех.'
      source: SEC earnings release; FAA operational plan
transition_semantics:
  trigger: Наблюдаемый факт.
  evidence_required: true
evaluation_rule: Оцениваются только переходы с from = текущему
  состоянию оси.
legacy_compatibility:
  unchanged_ids:
  - T-E-01
"""

SPCX_KPIS = f"""# KPI TST (старый формат)
version: '1.3'
artifact: TST KPI Dashboard
as_of: '2026-09-20'
ticker: TST
max_critical_kpis: 10
source_policy:
  primary:
  - SEC
  rule: Last value без источника не используется.
critical_kpis:
- id: T-KPI-01
  name: AI revenue YoY
  unit: '%'
  period: quarter
  source: SEC
  formula: (AI revenue_t / AI revenue_t-4 - 1) * 100
  thresholds:
    green: '>= 50%'
    yellow: 20% to <50%
    red: <20%
  last_value: 247
  last_date: '2026-06-30'
  last_value_raw: $2.5B
  source_url: {SEC_ER}
- id: T-KPI-02
  name: AI nameplate compute
  unit: GW
  period: quarter-end
  source: SEC
  formula: Nameplate compute draw at period end
  thresholds:
    green: '>= 2.0 GW'
    yellow: 1.0 to <2.0 GW
    red: <1.0 GW
  last_value: 1.4
  last_date: '2026-06-30'
  last_value_raw: 1.4 GW
  last_yoy_growth: 100
  source_url: {SEC_10Q}
- id: T-KPI-03
  name: 'TST valuation multiple: market cap / TTM revenue'
  unit: x
  period: daily
  source: 'invest-calc: model valuation_multiple'
  formula: Market capitalization / trailing twelve-month revenue
  thresholds:
    green: < 30x
    yellow: 30x to <60x
    red: '>= 60x'
  last_value: 87.35
  last_date: '2026-09-18'
  last_value_raw: $152.71 × 13.18 млрд / $23.04 млрд
  source_url: https://finance.yahoo.com/quote/TST/; https://stockanalysis.com/stocks/tst/statistics/
  notes: Считается сайдкаром.
  inputs:
    ttm_revenue_usd_b:
      value: 23.044
      verified: true
derived_checks:
  revenue_q2_2026:
    value: 7.814
    unit: USD B
data_quality:
  rule: До публикации Q3 финансовые KPI остаются на Q2.
source_artifact: from_imma/TST_kpis_v1.0.yaml
kpi_observation_rule: Каждое новое значение записывается в state.json →
  kpi_observations.
supporting_metrics:
- id: T-METRIC-01
  last_value: 14.1
calculated_metrics:
  metrics:
  - implied_revenue_cagr_5y
"""

SPCX_TRIGGERS_RAW = """# Реестр триггеров: TST (старый формат; при записи — CRLF, как у реального spacex/triggers.yaml)
# Классы: price | event

meta:
  ticker: TST
  company: Test Co
  registry_updated: 2026-09-20  # комментарий сохраняется
  price_source: "https://query1.finance.yahoo.com/v8/finance/chart/TST?range=1d&interval=1d"
  reference_price_in_strategy: 124        # «не входить на $124»
  price_at_registry: 150.88               # закрытие
  position_plan:
    opening_2026: "5–8% портфеля"

automations:
  tst-report-check:  { covers: "E-10..E-12, E-20..E-20 (переходы по отчётам)", cadence: "после отчёта" }
  tst-price-watch:   { pilot: true, covers: [T-P-01], cadence: "каждые 30 мин" }

route:
  steps:
    - { id: opening, kind: stage, name: "Фаза 1" }
    - { id: vector, kind: axis, name: "Вектор состояний" }

triggers:

  - id: T-P-01
    class: price
    step: opening
    condition: "цена < $100"
    action: "Удвоить транш"
    strategy_ref: "Фаза 1, ход 1.3"
    probability_in_strategy: "40%"
    window: { from: 2026-08-01, to: 2027-03-31 }
    automation: tst-price-watch
    status: active
    fired: []

  - id: T-E-10
    class: event
    step: vector
    axis: AI
    transition: { from: A0, to: A1 }
    level: E2
    kpis: [T-KPI-01]
    supporting_metrics: [T-METRIC-01]
    notes_kpi: "Вторая ветвь OR не представлена отдельным\\
  \\ KPI в kpis.yaml."
    condition: "AI revenue >= $0.5B за квартал"
    source: "SEC 10-Q"
    action: "Сообщить владельцу"
    automation: tst-report-check
    status: active

  - id: T-E-12
    class: event
    step: vector
    axis: AI
    transition: { from: A1, to: A0 }
    level: E2
    kpis: [T-KPI-01]
    condition: "AI revenue < $0.3B"
    action: "Сообщить владельцу"
    automation: tst-report-check
    status: active

  - id: T-E-20
    class: event
    step: vector
    axis: Valuation
    transition: { from: V0, to: V1 }
    level: E2
    kpis: [T-KPI-03]
    calculated_metrics: [implied_revenue_cagr_5y]
    condition: "valuation multiple >= 60x"
    action: "Сообщить владельцу"
    automation: tst-report-check
    status: planned

  - id: T-E-34
    class: event
    step: vector
    axis: AI
    transition: null
    level: E2
    kpis: [T-KPI-02]
    condition: "nameplate compute >= 2.0 GW"
    action: "Подтвердить узел траектории"
    automation: tst-report-check
    status: planned
    notes: "Не переход состояния."
"""

SPCX_MPC_HEAD = """# MPC inputs TST (старый формат)
version: '1.0'
ticker: TST
artifact: mpc_inputs
as_of: '2026-09-21'
driver_taxonomy_version: '1.1'
source_artifact: from_imma/TST_mpc_inputs_v1.0.yaml
status: complete
methodology_refs:
  mpc_schema: Marginal_Portfolio_Contribution_Schema_v1.0
semantics:
  driver_scale:
    '-2': strong_negative
    '2': strong_positive
  provenance: model_assumption
  rule: 'Знак показывает влияние усиления драйвера.

    '
driver_exposure_vector:
"""
SPCX_MPC_TAIL = """driver_interpretation:
  AI_COMPUTE_DEMAND:
    vector_score: 2
failure_modes:
- failure_id: T-FM-01
  name: AI overbuild
  common_cause_id: AI_OVERBUILD
  severity: high
  axis_refs:
  - AI
model_notes:
- 'HYPERSCALER_CAPEX is intentionally only +1.

  '
"""


def _spcx_state() -> dict:
    return {
        "updated": "2026-09-25T08:15:26Z",
        "price": {"last": 150.88, "last_at": "2026-09-16", "zone": None, "note": "копия после срабатываний"},
        "fired": [], "pending_verification": [],
        "events_reported": [{"trigger_id": "T-E-06", "at": "2026-07-07", "source": "https://ir.nasdaq.com/news-releases/tst-join-nasdaq-100",
                             "summary": "TST включена в Nasdaq-100 с 7 июля 2026"}],
        "gaap_profit_quarters": [],
        "notes": ["2026-09-17: заметка"],
        "calc_inputs": {"reverse_valuation": {"cash_usd": 93522000000, "verified": True}},
        "route": {"current": "opening", "done_steps": [], "changed_at": "2026-09-17", "note": "маршрут"},
        "info_log": [
            {"timestamp": "2026-09-25T08:15:26Z", "trigger_id": "TST-WATCH", "kind": "price_source_unavailable", "text": "Источник котировок недоступен.", "level": "E1"},
            {"timestamp": "2026-09-20T18:39:13Z", "trigger_id": "T-E-20", "text": "Обратная оценка: V1 сохраняется.", "level": "E1"},
            {"timestamp": "2026-09-22T06:25:00Z", "kind": "calc", "summary": "Сравнительный прогон."},
        ],
        "scenario_state": {
            "AI": {"state": "A1", "since": "2026-09-20", "evidence": ["AI revenue Q2 = $2.5B."], "source": SEC_ER},
            "Valuation": {"state": "V1", "since": "2026-09-20", "evidence": ["Close = $150."], "source": "https://finance.yahoo.com/quote/TST/"},
            "Starship": {"state": "C0", "since": "2026-09-20", "evidence": ["Flight 12: успех."], "source": "SEC earnings release; FAA operational plan"},
        },
        "state_transitions": [],
        "kpi_observations": [
            {"kpi_id": "T-KPI-01", "name": "AI revenue YoY", "period_end": "2026-06-30", "value": 247, "value_raw": "$2.5B", "unit": "%", "source_url": SEC_ER, "verified": True},
            {"kpi_id": "T-KPI-02", "name": "AI nameplate compute", "period_end": "2026-06-30", "value": 1.4, "unit": "GW", "source_url": SEC_10Q, "verified": True},
            {"kpi_id": "T-KPI-03", "name": "TST valuation multiple", "period_end": "2026-09-18", "value": 87.35, "unit": "x",
             "source_url": "SEC 10-Q (акции), Yahoo chart (цена)", "verified": True, "run_id": "20260920T150722Z-valuation_multiple-b55b3b"},
        ],
        "calc_runs": [],
    }


def _spcx_ws(tmp_path, folder="spacex", state=None) -> Path:
    d = tmp_path / "portfolio" / folder
    d.mkdir(parents=True)
    (d / "states.yaml").write_text(SPCX_STATES, encoding="utf-8")
    (d / "kpis.yaml").write_text(SPCX_KPIS, encoding="utf-8")
    (d / "triggers.yaml").write_bytes(SPCX_TRIGGERS_RAW.replace("\n", "\r\n").encode("utf-8"))
    vec = "".join(f"  {k}: {2 if k == 'AI_COMPUTE_DEMAND' else 0}\n" for k in TAXONOMY_1_1)
    (d / "mpc_inputs.yaml").write_bytes((SPCX_MPC_HEAD + vec + SPCX_MPC_TAIL).replace("\n", "\r\n").encode("utf-8"))
    (d / "state.json").write_text(json.dumps(state if state is not None else _spcx_state(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "thesis.md").write_text("# тезис — не мигрируется\n", encoding="utf-8")
    return d


def _neutral_view(folder: Path) -> dict:
    """И1: канонические ID, состояния осей, значения/даты KPI и наблюдений, условия и переходы триггеров."""
    st, kp, tr, sj = (mig.load_plain(folder / fn) for fn in ("states.yaml", "kpis.yaml", "triggers.yaml", "state.json"))
    return {"axes": {ax: sorted(a["states"]) for ax, a in st["axes"].items()},
            "kpis": {k["id"]: (k["last_value"], k.get("last_date")) for k in kp["critical_kpis"]},
            "triggers": {t["id"]: (t.get("condition"), t.get("transition"), t.get("axis"), t.get("status")) for t in tr["triggers"]},
            "scenario": {ax: v["state"] for ax, v in sj["scenario_state"].items()},
            "observations": [(o["kpi_id"], o["period_end"], o["value"]) for o in sj["kpi_observations"]]}


def test_spcx_source_class_rules():
    """MIG-SPCX-07 по Source Policy v1.0: релиз SEC по идентичности документа, тело формы — regulatory_filing, рынок — провайдер."""
    assert mig.spcx_source_class(SEC_ER) == "issuer_ir_release"
    assert mig.spcx_source_class("https://www.sec.gov/Archives/edgar/data/1/2/tm_ex99-1.htm") == "issuer_ir_release"
    assert mig.spcx_source_class(SEC_10Q) == "regulatory_filing"
    assert mig.spcx_source_class("https://finance.yahoo.com/quote/TST/; https://stockanalysis.com/x") == "market_data_provider"
    assert mig.spcx_source_class("https://stockanalysis.com/stocks/tst/") == "market_data_provider"
    assert mig.spcx_source_class(None) == "other_primary"
    assert mig.source_class(SEC_ER, "SEC") == "regulatory_filing"                             # общее правило для других папок не менялось
    assert mig._covers_list("E-10..E-12, E-20..E-20 (x)", "T") == ["T-E-10", "T-E-11", "T-E-12", "T-E-20"]


def test_spcx_profile_migrates_idempotent_and_neutral(tmp_path):
    """(а) без workspace: профиль + общие правила проходят без ошибок, эталон = построчный патч, перенесённое — в _legacy дословно;
    (б) идемпотентность; (в) семантическая нейтральность; сверка transition_triggers ↔ triggers.yaml — в отчёте."""
    pytest.importorskip("ruamel.yaml")
    d = _spcx_ws(tmp_path)
    before = {fn: (d / fn).read_bytes() for fn in mig.FILES}
    view0 = _neutral_view(d)
    r = mig.migrate_folder(d, apply=True)
    assert r["errors"] == [] and r["profile"] == "full_model" and sorted(r["changed"]) == sorted(mig.FILES)
    assert sorted(r["legacy"]) == sorted(f"_legacy/{n}" for n in mig.SPCX_LEGACY_FILES.values())
    # (в) И1: ID, состояния, значения, даты, условия — те же; переходы E-34 (null) сняты, остальные — те же
    view1 = _neutral_view(d)
    for k in ("axes", "kpis", "scenario", "observations"):
        assert view1[k] == view0[k], k
    assert view1["triggers"]["T-E-34"] == ("nameplate compute >= 2.0 GW", None, "AI", "planned") and view0["triggers"]["T-E-34"][1] is None
    assert {k: v for k, v in view1["triggers"].items()} == view0["triggers"]
    st, kp, tr, mp, sj = (mig.load_plain(d / fn) for fn in mig.FILES)
    assert all(doc["schema_version"] == "1.0.5" for doc in (st, kp, tr, mp, sj))
    # states: criteria дословно; оси с current/current_evidence/source_refs; источники без выдумки (у Starship URL нет)
    assert st["axes"]["AI"]["states"]["A1"] == {"name": "validation", "criteria": "Есть подтверждённый спрос и растущая выручка."}
    assert st["axes"]["AI"]["current"] == "A1" and st["axes"]["AI"]["current_evidence"] == ["AI revenue Q2 = $2.5B, +247% YoY."] and st["axes"]["AI"]["source_refs"] == ["TST_EARNINGS_RELEASE"]
    assert st["axes"]["Valuation"]["source_refs"] == ["TST_YAHOO_QUOTE", "TST_STOCKANALYSIS"] and st["axes"]["Starship"]["source_refs"] == []
    assert st["sources"]["TST_EARNINGS_RELEASE"] == {"source_class": "issuer_ir_release", "url": SEC_ER, "as_of": "2026-09-20"}
    assert "transition_semantics" not in st and "current_snapshot" not in st["axes"]["AI"]
    # kpis: value_type/source_class/verified/provenance; last_value_raw → note; notes → note; перенесённое — в _legacy
    k1, k2, k3 = kp["critical_kpis"]
    assert (k1["value_type"], k1["source_class"], k1["verified"], k1["provenance"], k1["note"]) == ("actual", "issuer_ir_release", None, "derived_fact", "last_value_raw: $2.5B")
    assert (k2["source_class"], k2["provenance"]) == ("regulatory_filing", "verified_fact") and "last_yoy_growth" not in k2
    assert (k3["source_class"], k3["provenance"], k3["note"]) == ("market_data_provider", "derived_fact", "Считается сайдкаром.") and "inputs" not in k3
    assert kp["zone_semantics"] == {"thresholds_provenance": "model_assumption"} and "derived_checks" not in kp
    # triggers: condition_provenance у переходов, transition: null снят, meta/automations по схеме
    t = {x["id"]: x for x in tr["triggers"]}
    assert t["T-E-10"]["condition_provenance"] == "model_assumption" and "transition" not in t["T-E-34"] and "condition_provenance" not in t["T-E-34"]
    assert "strategy_ref" not in t["T-P-01"] and "notes_kpi" not in t["T-E-10"] and "calculated_metrics" not in t["T-E-20"]
    assert tr["meta"]["exchange"] == "NASDAQ" and tr["meta"]["yahoo_symbol"] == "TST" and "position_plan" not in tr["meta"]
    assert tr["automations"]["tst-report-check"] == {"covers": ["TST-E-10", "TST-E-11", "TST-E-12", "TST-E-20"], "cadence": "после отчёта", "note": "E-10..E-12, E-20..E-20 (переходы по отчётам)"}
    assert tr["automations"]["tst-price-watch"] == {"covers": ["T-P-01"], "cadence": "каждые 30 мин"}
    # mpc: driver_exposure_semantics — переименование; state.json — форма схемы
    assert mp["driver_exposure_semantics"] == {"scale": {"-2": "strong_negative", "2": "strong_positive"}, "provenance": "model_assumption", "direction_rule": "Знак показывает влияние усиления драйвера.\n"}
    assert mp["driver_vector_provenance"] == "model_assumption" and "model_notes" not in mp
    assert sj["info_log"][1] == {"timestamp": "2026-09-20T18:39:13Z", "kind": "legacy_trigger_log", "summary": "Обратная оценка: V1 сохраняется."}
    assert sj["info_log"][2] == {"timestamp": "2026-09-22T06:25:00Z", "kind": "calc", "summary": "Сравнительный прогон."}
    assert all(a["verified"] is False for a in sj["scenario_state"].values())
    obs = {o["kpi_id"]: o for o in sj["kpi_observations"]}
    assert (obs["T-KPI-01"]["provenance"], obs["T-KPI-02"]["provenance"], obs["T-KPI-03"]["provenance"]) == ("derived_fact", "verified_fact", "derived_fact")
    assert obs["T-KPI-03"]["note"] == "run_id: 20260920T150722Z-valuation_multiple-b55b3b" and "run_id" not in obs["T-KPI-03"] and obs["T-KPI-01"]["verified"] is True
    assert "calc_inputs" not in sj and "gaap_profit_quarters" not in sj
    # ничего не потеряно: _legacy содержит перенесённые значения дословно
    L = {n: (json.loads if n.endswith(".json") else yaml.safe_load)((d / "_legacy" / n).read_text(encoding="utf-8")) for n in mig.SPCX_LEGACY_FILES.values()}
    old = {fn: mig.norm_dates(yaml.safe_load(before[fn].decode("utf-8"))) for fn in ("states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml")}
    assert mig.norm_dates(L["states_legacy_notes.yaml"]["axes"]["AI"]) == {k: old["states.yaml"]["axes"]["AI"][k] for k in ("current_snapshot", "transition_triggers")}
    assert {k: L["states_legacy_notes.yaml"][k] for k in ("source_policy", "transition_semantics", "evaluation_rule", "legacy_compatibility")} == {k: old["states.yaml"][k] for k in ("source_policy", "transition_semantics", "evaluation_rule", "legacy_compatibility")}
    assert L["kpis_legacy.yaml"]["critical_kpis"]["T-KPI-03"] == {"last_value_raw": "$152.71 × 13.18 млрд / $23.04 млрд", "inputs": old["kpis.yaml"]["critical_kpis"][2]["inputs"]}
    assert L["triggers_legacy.yaml"]["triggers"]["T-E-10"]["notes_kpi"] == "Вторая ветвь OR не представлена отдельным KPI в kpis.yaml."
    assert L["triggers_legacy.yaml"]["meta"]["reference_price_in_strategy"] == 124 and L["triggers_legacy.yaml"]["automations"] == {"tst-price-watch": {"pilot": True}}
    assert "# «не входить на $124»" in (d / "_legacy" / "triggers_legacy.yaml").read_text(encoding="utf-8")                  # комментарий перенесён
    assert L["mpc_inputs_legacy.yaml"]["model_notes"] == old["mpc_inputs.yaml"]["model_notes"]
    assert L["state_legacy.json"]["calc_inputs"] == _spcx_state()["calc_inputs"] and L["state_legacy.json"]["info_log"][1] == {"timestamp": "2026-09-20T18:39:13Z", "trigger_id": "T-E-20", "level": "E1"}
    # сверка transition_triggers ↔ triggers.yaml — расхождения в отчёте, триггеры не созданы
    tt = r["spcx"]["transition_triggers"]["AI"]
    assert tt["missing_in_triggers"] == ["T-E-99"] and tt["transition_on_axis_not_listed"] == ["T-E-12"] and "T-E-99" not in t
    assert r["spcx"]["null_transitions_removed"] == ["T-E-34"]
    # байты: CRLF сохранён, комментарии на месте, не-артефакты не тронуты
    assert b"\r\n" in (d / "triggers.yaml").read_bytes() and b"\r\n" not in (d / "states.yaml").read_bytes()
    assert b"# \xd0\xba\xd0\xbe\xd0\xbc\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0\xd1\x80\xd0\xb8\xd0\xb9 \xd1\x81\xd0\xbe\xd1\x85\xd1\x80\xd0\xb0\xd0\xbd\xd1\x8f\xd0\xb5\xd1\x82\xd1\x81\xd1\x8f" in (d / "triggers.yaml").read_bytes()
    assert (d / "thesis.md").read_text(encoding="utf-8") == "# тезис — не мигрируется\n"
    # (б) И3: второй прогон ничего не меняет и не трогает _legacy
    after = {p.name: p.read_bytes() for p in list(d.iterdir()) + list((d / "_legacy").iterdir()) if p.is_file()}
    again = mig.migrate_folder(d, apply=True)
    assert again["changed"] == [] and again["legacy"] == [] and again["errors"] == [] and sorted(again["unchanged"]) == sorted(mig.FILES)
    assert after == {p.name: p.read_bytes() for p in list(d.iterdir()) + list((d / "_legacy").iterdir()) if p.is_file()}


def test_spcx_profile_validator_pass(tmp_path):
    """(а) валидатор папки в процессе: старый формат не проходит, после миграции — pass: True, 0 ошибок схемы и целостности.
    Схемы — из <workspace>/methodology (INVEST_WORKSPACE); без workspace — пропуск."""
    pytest.importorskip("ruamel.yaml")
    if not SCHEMA.exists():
        pytest.skip("workspace (methodology) недоступен")
    from engine import artifact_validator as av
    d = _spcx_ws(tmp_path)
    v0 = av.run({"folders": [str(d)], "workspace": str(WS)}, 0)["folders"][str(d)]
    assert v0["pass"] is False and v0["schema_errors"] > 0 and v0["integrity_errors"] > 0
    assert mig.migrate_folder(d, apply=True)["errors"] == []
    v1 = av.run({"folders": [str(d)], "workspace": str(WS)}, 0)["folders"][str(d)]
    assert v1["pass"] is True and v1["schema_errors"] == 0 and v1["integrity_errors"] == 0, (v1["files"], v1["integrity"])


def test_spcx_profile_refuses_without_evidence_and_scope(tmp_path):
    """Биржа не выдумывается: без записи о Nasdaq-100 профиль отказывает и не пишет ни одного файла папки. (г) профиль
    применяется только к spacex: та же форма в другой папке идёт общими правилами (как раньше), _legacy не создаётся."""
    pytest.importorskip("ruamel.yaml")
    state = _spcx_state(); state["events_reported"] = []
    d = _spcx_ws(tmp_path, state=state)
    before = {fn: (d / fn).read_bytes() for fn in mig.FILES}
    r = mig.migrate_folder(d, apply=True)
    assert r["errors"] and "exchange" in r["errors"][0] and not (d / "_legacy").exists()
    assert before == {fn: (d / fn).read_bytes() for fn in mig.FILES}
    o = _spcx_ws(tmp_path / "other", folder="tst")
    ro = mig.migrate_folder(o, apply=False)
    assert "spcx" not in ro and ro["legacy"] == [] and not (o / "_legacy").exists()
    assert [f.name for f in mig.iter_folders(tmp_path, None)] == ["spacex"]                     # spacex больше не пропускается
    assert mig.SKIP_FOLDERS == set() and mig.SPCX_FOLDERS == {"spacex"}
