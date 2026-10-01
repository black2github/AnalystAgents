"""Валидатор артефактов компаний — гейт G5 (Runtime_Quality_Gates: schema + ID + references) по Company Artifact
Schema v1.0.5, Company Candidate Schema v1.0.1, Dozor Verification Protocol v1.2.1 и Company MC Calibration Schema v1.0.1
(нормативный дом схем — workspace/methodology/; версии — константы ниже).
Нулевой LLM: JSON Schema Draft 2020-12 по каждому файлу + правила целостности ART-REF-* / CAND-REF-* кодом.
Даты YAML нормализуются к ISO-строкам до проверки (MIG-111 — правило валидатора, не схемы).

inputs:
  mode: "workspace" (по умолчанию) | "candidate" | "dozor_report" | "calibration" (calibration: dict по Company MC Calibration
        Schema; folders: ["<папка>"] для MC-G5-001 по mpc_inputs; правила MC-G5-001..013 кодом, MC-G5-013 — σ суммарного
        сдвига цели на путях Joint Layer (hard gate; strict_aggregate: false → warning), выводится в aggregate_shift;
        engine_dry_run: true — company_mc на малом числе путей: mapping_warnings, детерминизм; dispersion_check: true —
        intrinsic/full W = q95−q5 CAGR 5Y против ориентиров Rules v1.1 (MC-DISP-001..003, warning), вывод dispersion;
        требует equity_value_0 — стартовую рыночную стоимость, без неё диагностика пропускается с предупреждением)
        | "dozor_report" (report: dict по output_report_schema протокола дозора;
        "folders": ["<папка>"] для сверки с kpis/states/triggers папки; правила DZR-001..016: тикер, kpi_id, runtime_verified и
        patch_required по status_registry протокола (KPI/оси/события/transition_checks), согласованность summary,
        оси/состояния/kpi_item_refs, trigger_id, fact_only, ссылки transition_checks (DZR-011), для отчётов v1.2 — база
        derived_fact (DZR-012) и criteria:null у осей pending (DZR-014), not_met/condition_not_met без patch (DZR-015),
        итог по старшинству BLOCKED_SOURCE_CONFLICT > BLOCKED_TECHNICAL > PATCH_REQUIRED > PASS_WITH_DECLARED_PENDING > PASS (DZR-010))
  workspace: путь к workspace (по умолчанию env CALC_DATA или /data/workspace-invest)
  folders: ["nbis", ...] | "all" (все папки portfolio/ с triggers.yaml, кроме `_*` и skip_folders)
  skip_folders: ["spacex"] по умолчанию (старый формат до партий)
  schema_path / candidate_schema_path: переопределение путей к схемам
  candidate: dict — пакет кандидата LLM (mode=candidate); documents: {"states.yaml": {...}, ...} — проверка словарей
    без файлов (mode=workspace, вместо folders)
outputs: по папке — profile, ошибки схемы по файлам, находки правил целостности, pass; summary; список правил
  implemented / not_implemented (ART-REF-005/006/013/023 требуют Source Policy / Provenance-контекста / интегратора и
  проверяются частично или не проверяются — это заявлено явно, а не молча). Детерминированно, seed не используется.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
from pathlib import Path

import yaml

VERSION = "1.9.0"  # 1.6.0: схема калибровки по schema_version файла (1.0.1 закреплена, 1.0.2 текущая), Rules v1.1.2 (пороги вех нормативны,
#                    измерение в квартале применения — мода сроков вехи, как в движке), пример-фикстуры v1.0.2
SCHEMA_VERSION = "1.0.5"            # Company Artifact Schema (v1.0.5: kpi_observations[].verification_run_ids — история прогонов дозора)
CANDIDATE_SCHEMA_VERSION = "1.0.1"  # Company Candidate Schema (не менялась с партии 1)
DOZOR_PROTOCOL_VERSION = "1.2.1"    # Dozor Verification Protocol (сводная редакция v1.2.1 = v1.1 + дельта v1.2; схема отчёта 1.2.0, отчёты v1.0/v1.1 валидны)
VERIFIED_KPI_STATUSES = ("verified_match", "verified_match_with_normalization")
CALIBRATION_SCHEMA_VERSION = "1.0.2"  # Company MC Calibration Schema — текущая (привязка к company_mc 2.3.1)
CALIBRATION_SCHEMA_VERSIONS = ("1.0.1", "1.0.2")  # 1.0.1 — закреплённая версия принятых калибровок SPCX/NBIS/NVDA (движок 2.3.0, hard switch);
#                                                   схема выбирается по schema_version самой калибровки (решение 24.09.2026)
# MC-G5-013 (Joint_Simulation_Layer_Rules_v1.1, принято 23.09 — hard gate): σ суммарного сдвига цели от всех драйверов;
# рост — q20, узлы горизонтов — нативный квартал (Y3→q12, Y5→q20, Y8→q32); мультипликатор — ln(M_shocked/M_base) ≈ Σ e·x
AGG_SHIFT_LIMITS = {"growth": 0.15, "margin": 0.05, "multiple": 0.15, "milestone": 0.75, "other": 0.15,
                    # архетип C — кандидатные пороги IMMA (пакет HOOD_RKLB_Calibrations_v1, 23.09; до закрепления в Rules v1.1.2):
                    # вероятность вехи — σ суммарного сдвига в логит-пространстве; сроки — σ сдвига в кварталах
                    "milestone_probability": 0.35, "milestone_timing": 1.0}
ARTIFACT_FILES = ["states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml", "state.json"]
VALUE_TYPES = {"actual", "company_guidance", "analyst_estimate"}
INACTIVE_STATUSES = {"paused", "dropped", "done"}
TRADE_WORDS = re.compile(r"\b(купить|продать|докупить|продавать|покупать|buy|sell)\b", re.I)
NOT_IMPLEMENTED = {
    "ART-REF-005": "класс источника проверяется по enum схемы; иерархия/допустимость по типу факта — Source Policy v1.0 (партия 2)",
    "ART-REF-006": "provenance проверяется у KPI/наблюдений/вектора драйверов (обязательные поля схемы); «каждое материальное число» в свободных полях не трассируется",
    "ART-REF-013": "авторитет присвоения ID — свойство интегратора (процесс), статически не проверяется; проверяется только уникальность и шаблон <TK>-...",
    "ART-REF-023": "качественные оси: проверяется наличие source/evidence при evidence_type=qualitative_primary_source; декларация бинарной деривации — semantic review (IMA-08)",
    "CAND-REF-011": "как ART-REF-006",
}


# ----------------------------------------------------------------------------------------------- загрузка
def _norm(o):
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_norm(v) for v in o]
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return o


def _load(p: Path):
    text = p.read_text(encoding="utf-8")
    return _norm(json.loads(text) if p.suffix == ".json" else yaml.safe_load(text))


def _workspace(inputs: dict) -> Path:
    return Path(inputs.get("workspace") or os.environ.get("CALC_DATA", "/data/workspace-invest"))


def _schema(inputs: dict, key: str, default_name: str) -> dict:
    p = Path(inputs.get(key) or (_workspace(inputs) / "methodology" / default_name))
    if not p.exists():
        raise ValueError(f"схема не найдена: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _taxonomy_ids(ws: Path, version) -> set[str] | None:
    p = ws / "methodology" / f"MPC_Driver_Taxonomy_v{version}.yaml"
    if not p.exists():
        return None
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    drivers = d.get("drivers") or {}
    ids: set[str] = set()
    extra = [v for k, v in d.items() if str(k).startswith("added_v") and k not in drivers]   # v1.2: added_v1_2 на верхнем уровне (не под drivers)
    for v in (list(drivers.values()) if isinstance(drivers, dict) else [drivers]) + extra:
        if isinstance(v, list):
            ids |= {x if isinstance(x, str) else x.get("id") for x in v}
        elif isinstance(v, dict):
            ids |= set(v)
    return ids


def _schema_errors(schema: dict, doc) -> list[dict]:
    from jsonschema import Draft202012Validator as V

    out = []
    for e in sorted(V(schema).iter_errors(doc), key=lambda e: [str(x) for x in e.path]):
        out.append({"path": "/".join(str(x) for x in e.path) or "<root>", "message": e.message[:300]})
    return out


# ----------------------------------------------------------------------------------------------- правила целостности: workspace
def _f(rule, path, message, severity="error"):
    return {"rule": rule, "severity": severity, "path": path, "message": message}


def _numf(v):
    """Числа к float для тождества наблюдения (ART-REF-031): 3 и 3.0 — одно значение; bool не число."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return {k: _numf(x) for k, x in v.items()}
    return v


def integrity_workspace(docs: dict, taxonomy_ids: set[str] | None, source_classes: set[str]) -> list[dict]:
    F: list[dict] = []
    st, kp, tr, mp, sj = (docs.get(k) for k in ARTIFACT_FILES)
    profile = (tr or {}).get("profile") or ("full_model" if st and kp and mp else "registry_only")
    axes = (st or {}).get("axes") or {}
    kpi_ids = [k.get("id") for k in (kp or {}).get("critical_kpis", [])]
    # ART-REF-001..003 (только full_model; 024 — registry_only пропускает кросс-файловые проверки)
    if tr and profile == "full_model":
        for t in tr.get("triggers", []):
            tid = t.get("id")
            ax = t.get("axis")
            if ax is not None and ax not in axes:
                F.append(_f("ART-REF-001", f"triggers/{tid}/axis", f"ось {ax!r} не найдена в states.yaml"))
            if "transition" in t and ax in axes:
                states = (axes[ax].get("states") or {})
                for end in ("from", "to"):
                    s = (t["transition"] or {}).get(end)
                    if s not in states:
                        F.append(_f("ART-REF-002", f"triggers/{tid}/transition/{end}", f"состояние {s!r} не найдено в оси {ax!r}"))
            for k in t.get("kpis") or []:
                if k not in kpi_ids:
                    F.append(_f("ART-REF-003", f"triggers/{tid}/kpis", f"KPI {k!r} не найден в kpis.yaml"))
    # ART-REF-004: source_refs осей → sources
    if st:
        srcs = st.get("sources") or {}
        for ax, a in axes.items():
            for r in a.get("source_refs") or []:
                if r not in srcs:
                    F.append(_f("ART-REF-004", f"states/axes/{ax}/source_refs", f"ссылка {r!r} не найдена в states.sources"))
    # ART-REF-005/007/008/018/019/020/021/022: KPI
    if kp:
        for k in kp.get("critical_kpis", []):
            kid = k.get("id")
            if k.get("source_class") not in source_classes:
                F.append(_f("ART-REF-005", f"kpis/{kid}/source_class", f"класс {k.get('source_class')!r} вне enum"))
            lv = k.get("last_value")
            if not (lv is None or (isinstance(lv, (int, float)) and not isinstance(lv, bool))):
                F.append(_f("ART-REF-007", f"kpis/{kid}/last_value", f"не число и не null: {lv!r}"))
            if k.get("value_type") not in VALUE_TYPES:
                F.append(_f("ART-REF-008", f"kpis/{kid}/value_type", f"{k.get('value_type')!r} вне {sorted(VALUE_TYPES)}"))
            q = k.get("observation_qualifier")
            if q == "range":
                vr = k.get("value_range") or {}
                if lv is not None or not all(isinstance(vr.get(x), (int, float)) for x in ("min", "max")):
                    F.append(_f("ART-REF-018", f"kpis/{kid}", "range требует last_value=null и числовые value_range.min/max"))
            if q in ("lower_bound", "upper_bound") and not isinstance(lv, (int, float)):
                F.append(_f("ART-REF-019", f"kpis/{kid}", f"{q} требует числовой last_value"))
            sref = k.get("source_ref")
            if sref is not None and st is not None:
                src = (st.get("sources") or {}).get(sref)
                if src is None:
                    F.append(_f("ART-REF-020", f"kpis/{kid}/source_ref", f"{sref!r} не найден в states.sources"))
                elif isinstance(src, dict) and src.get("source_class") != k.get("source_class"):
                    F.append(_f("ART-REF-020", f"kpis/{kid}/source_class", f"{k.get('source_class')!r} ≠ класс источника {sref!r} ({src.get('source_class')!r})"))
            th = k.get("thresholds") or {}
            if th.get("binary") is not True and "yellow" not in th:
                F.append(_f("ART-REF-022", f"kpis/{kid}/thresholds", "нет жёлтой зоны у небинарного KPI"))
            if th.get("binary") is True and not ({"green", "red"} <= set(th)):
                F.append(_f("ART-REF-022", f"kpis/{kid}/thresholds", "бинарный KPI требует green и red"))
    # ART-REF-009/010/011/021/023: state.json
    if sj:
        for ax, s in (sj.get("scenario_state") or {}).items():
            if st is not None and ax not in axes:
                F.append(_f("ART-REF-009", f"state/scenario_state/{ax}", "ось не найдена в states.yaml"))
            elif st is not None:
                stt = (s or {}).get("state")
                if stt != "pending_verification" and stt not in (axes[ax].get("states") or {}):
                    F.append(_f("ART-REF-010", f"state/scenario_state/{ax}/state", f"состояние {stt!r} не найдено в оси"))
            if (s or {}).get("evidence_type") == "qualitative_primary_source" and not ((s or {}).get("source") or (s or {}).get("evidence")):
                F.append(_f("ART-REF-023", f"state/scenario_state/{ax}", "качественное свидетельство без source/evidence"))
        for i, o in enumerate(sj.get("kpi_observations") or []):
            if kp is not None and o.get("kpi_id") not in kpi_ids:
                F.append(_f("ART-REF-011", f"state/kpi_observations/{i}", f"kpi_id {o.get('kpi_id')!r} не найден в kpis.yaml"))
            vt = o.get("value_type")
            if vt is not None and vt not in VALUE_TYPES:
                F.append(_f("ART-REF-021", f"state/kpi_observations/{i}/value_type", f"{vt!r} вне enum (квалификатор → observation_qualifier)"))
            ids = o.get("verification_run_ids")
            if ids and (not o.get("verification_run_id") or ids[-1] != o.get("verification_run_id")):  # ART-REF-030 (v1.0.5)
                F.append(_f("ART-REF-030", f"state/kpi_observations/{i}/verification_run_id", f"{o.get('verification_run_id')!r} ≠ последний элемент verification_run_ids {ids[-1]!r}"))
        # ART-REF-031 (v1.0.5): наблюдение не дублируется при тех же kpi_id + period_end + value/value_range
        seen: dict[tuple, int] = {}
        for i, o in enumerate(sj.get("kpi_observations") or []):
            key = (o.get("kpi_id"), o.get("period_end"), json.dumps(_numf(o.get("value")), sort_keys=True), json.dumps(_numf(o.get("value_range")), sort_keys=True))
            if key in seen:
                F.append(_f("ART-REF-031", f"state/kpi_observations/{i}", f"дубликат наблюдения #{seen[key]} ({o.get('kpi_id')}, {o.get('period_end')}): история прогонов — в verification_run_ids существующей строки"))
            else:
                seen[key] = i
    # ART-REF-012: уникальность ID
    for name, ids in (("kpis", kpi_ids), ("triggers", [t.get("id") for t in (tr or {}).get("triggers", [])]),
                      ("failure_modes", [f.get("failure_id") for f in (mp or {}).get("failure_modes", [])])):
        dup = sorted({x for x in ids if ids.count(x) > 1})
        if dup:
            F.append(_f("ART-REF-012", name, f"дубликаты ID: {dup}"))
    # ART-REF-014: вектор драйверов == таксономия
    if mp:
        keys = set((mp.get("driver_exposure_vector") or {}).keys())
        if taxonomy_ids is None:
            F.append(_f("ART-REF-014", "mpc_inputs/driver_taxonomy_version", f"таксономия v{mp.get('driver_taxonomy_version')} не найдена в methodology/", "warning"))
        elif keys != taxonomy_ids:
            F.append(_f("ART-REF-014", "mpc_inputs/driver_exposure_vector", f"лишние: {sorted(keys - taxonomy_ids)}; отсутствуют: {sorted(taxonomy_ids - keys)}"))
    # ART-REF-015: trigger ≠ decision
    if tr:
        rules = tr.get("rules")
        if rules is not None and rules.get("trigger_not_decision") is not True:
            F.append(_f("ART-REF-015", "triggers/rules/trigger_not_decision", "должно быть true"))
        for t in tr.get("triggers", []):
            act = str(t.get("action") or "")
            if t.get("status") in INACTIVE_STATUSES:  # приостановленные/закрытые триггеры не действуют — не предупреждаем
                continue
            if TRADE_WORDS.search(act) and "не предопределено" not in act:
                F.append(_f("ART-REF-015", f"triggers/{t.get('id')}/action", "действие похоже на торговую инструкцию", "warning"))
    # ART-REF-016: версия схемы во всех файлах
    for fn, d in docs.items():
        if d is not None and d.get("schema_version") != SCHEMA_VERSION:
            F.append(_f("ART-REF-016", f"{fn}/schema_version", f"{d.get('schema_version')!r} ≠ {SCHEMA_VERSION!r}"))
    # ART-REF-017: тикер согласован
    tickers = {fn: v for fn, v in (("states.yaml", (st or {}).get("ticker")), ("kpis.yaml", (kp or {}).get("ticker")),
                                   ("triggers.yaml", ((tr or {}).get("meta") or {}).get("ticker")), ("mpc_inputs.yaml", (mp or {}).get("ticker"))) if v is not None}
    if len(set(tickers.values())) > 1:
        F.append(_f("ART-REF-017", "ticker", f"расходится: {tickers}"))
    return F


# ----------------------------------------------------------------------------------------------- правила целостности: кандидат
def integrity_candidate(c: dict, taxonomy_ids: set[str] | None) -> list[dict]:
    F: list[dict] = []
    srefs = [s.get("source_ref") for s in c.get("sources") or []]
    if len(set(srefs)) != len(srefs):
        F.append(_f("CAND-REF-001", "sources", "дубликаты source_ref"))
    axes = ((c.get("states") or {}).get("axes")) or {}
    for ax, a in axes.items():
        for r in (a.get("source_refs") or a.get("current_evidence_refs") or []):
            if r not in srefs:
                F.append(_f("CAND-REF-002", f"states/axes/{ax}", f"ссылка {r!r} не найдена в sources"))
        cur = a.get("current")
        if cur != "pending_verification" and cur not in (a.get("states") or {}):
            F.append(_f("CAND-REF-009", f"states/axes/{ax}/current", f"{cur!r} не найдено среди состояний оси"))
        ps = a.get("prior_snapshot")
        if ps is not None and ps not in (a.get("states") or {}):
            F.append(_f("CAND-REF-010", f"states/axes/{ax}/prior_snapshot", f"{ps!r} не найдено среди состояний оси"))
    kpis = ((c.get("kpis") or {}).get("items")) or []
    kids = [k.get("local_id") for k in kpis]
    if len(set(kids)) != len(kids):
        F.append(_f("CAND-REF-003", "kpis/items", "дубликаты local_id"))
    ticker = c.get("ticker") or ""
    canon = re.compile(rf"^{re.escape(ticker)}-(KPI|E|X|P|C|FM)-\d+", re.I) if ticker else None
    for k in kpis:
        kid = k.get("local_id")
        if k.get("source_ref") not in srefs:
            F.append(_f("CAND-REF-004", f"kpis/{kid}/source_ref", f"{k.get('source_ref')!r} не найден в sources"))
        lv = k.get("last_value")
        if not (lv is None or (isinstance(lv, (int, float)) and not isinstance(lv, bool))):
            F.append(_f("CAND-REF-012", f"kpis/{kid}/last_value", f"не число и не null: {lv!r}"))
        if k.get("value_type") not in VALUE_TYPES:
            F.append(_f("CAND-REF-013", f"kpis/{kid}/value_type", f"{k.get('value_type')!r} вне enum"))
        if canon and kid and canon.match(str(kid)):
            F.append(_f("CAND-REF-015", f"kpis/{kid}", "локальный ID похож на канонический — ID присваивает интегратор"))
    trs = ((c.get("transitions") or {}).get("items")) or []
    tids = [t.get("local_id") for t in trs]
    if len(set(tids)) != len(tids):
        F.append(_f("CAND-REF-005", "transitions/items", "дубликаты local_id"))
    for t in trs:
        tid = t.get("local_id")
        ax = t.get("axis")
        if ax not in axes:
            F.append(_f("CAND-REF-006", f"transitions/{tid}/axis", f"ось {ax!r} не найдена"))
        else:
            for end in ("from", "to"):
                s = (t.get("transition") or {}).get(end)
                if s not in (axes[ax].get("states") or {}):
                    F.append(_f("CAND-REF-007", f"transitions/{tid}/transition/{end}", f"состояние {s!r} не найдено в оси {ax!r}"))
        for r in t.get("kpi_refs") or []:
            if r not in kids:
                F.append(_f("CAND-REF-008", f"transitions/{tid}/kpi_refs", f"{r!r} не найден среди KPI"))
        if canon and tid and canon.match(str(tid)):
            F.append(_f("CAND-REF-015", f"transitions/{tid}", "локальный ID похож на канонический"))
        if TRADE_WORDS.search(str(t.get("action") or "") + " " + str(t.get("condition") or "")):
            F.append(_f("CAND-REF-016", f"transitions/{tid}", "переход содержит торговое действие", "warning"))
    mp = c.get("mpc_inputs") or {}
    keys = set((mp.get("driver_exposure_vector") or {}).keys())
    if taxonomy_ids is None:
        F.append(_f("CAND-REF-014", "mpc_inputs/driver_taxonomy_version", f"таксономия v{mp.get('driver_taxonomy_version')} не найдена", "warning"))
    elif keys != taxonomy_ids:
        F.append(_f("CAND-REF-014", "mpc_inputs/driver_exposure_vector", f"лишние: {sorted(keys - taxonomy_ids)}; отсутствуют: {sorted(taxonomy_ids - keys)}"))
    if c.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
        F.append(_f("CAND-REF-017", "candidate_schema_version", f"{c.get('candidate_schema_version')!r} ≠ {CANDIDATE_SCHEMA_VERSION!r}"))
    return F


# ----------------------------------------------------------------------------------------------- калибровки MC (MC-G5-*)
def _dists(o, path=""):
    """Все объекты-распределения калибровки: (путь, dict)."""
    if isinstance(o, dict):
        if "distribution" in o:
            yield path, o
        for k, v in o.items():
            yield from _dists(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _dists(v, f"{path}[{i}]")


def _target_kind(path: str) -> str:
    if "initial_growth" in path or "growth" in path:
        return "growth"
    if "margin" in path or "_nodes" in path or path.startswith("margin_model"):
        return "margin"
    if "multiple" in path:
        return "multiple"
    if path.startswith("milestone_model"):
        if path.endswith(".probability"):
            return "milestone_probability"
        if path.endswith(".timing"):
            return "milestone_timing"
        return "milestone"
    return "other"


def integrity_calibration(cal: dict, mpc: dict | None, joint_spec: dict | None, limits: dict, strict_aggregate: bool, agg: dict | None = None) -> list[dict]:
    """agg — необязательный словарь-накопитель σ суммарного сдвига по целям (заполняется для вывода aggregate_shift)."""
    F: list[dict] = []
    if agg is None:
        agg = {}
    maps = cal.get("driver_parameter_mapping") or []
    mapped = {m.get("driver_id") for m in maps}
    active = set((cal.get("joint_simulation") or {}).get("active_drivers") or [])
    # MC-G5-001: material-драйверы из mpc_inputs (|exposure| == 2 — error, ненулевые — warning)
    if mpc is not None:
        vec = mpc.get("driver_exposure_vector") or {}
        for d, e in vec.items():
            if e in (0, None) or d in mapped:
                continue
            F.append(_f("MC-G5-001", f"driver_parameter_mapping/{d}", f"драйвер {d!r} (exposure {e}) без mapping", "error" if abs(float(e)) >= 2 else "warning"))
    # MC-G5-002: mapping ⊆ active_drivers и наоборот
    for d in sorted(mapped - active):
        F.append(_f("MC-G5-002", f"joint_simulation/active_drivers", f"драйвер {d!r} есть в mapping, но не в active_drivers"))
    for d in sorted(active - mapped):
        F.append(_f("MC-G5-002", f"driver_parameter_mapping", f"драйвер {d!r} активен, но без mapping", "warning"))
    # MC-G5-005/006: вехи архетипа C
    mm = cal.get("milestone_model")
    if cal.get("archetype") == "pre_service_or_milestone_driven" and isinstance(mm, dict):
        ms = mm.get("milestones") or []
        ids = [m.get("id") for m in ms]
        if len(set(ids)) != len(ids):
            F.append(_f("MC-G5-005", "milestone_model/milestones", "дубликаты id вех"))
        req = {m.get("id"): list(m.get("requires") or []) for m in ms}
        for mid, rs in req.items():
            for r in rs:
                if r not in req:
                    F.append(_f("MC-G5-005", f"milestone_model/milestones/{mid}/requires", f"предпосылка {r!r} не существует"))
        if mm.get("service_onset_milestone") not in req:
            F.append(_f("MC-G5-005", "milestone_model/service_onset_milestone", f"{mm.get('service_onset_milestone')!r} не среди вех"))
        # ацикличность (DFS)
        state: dict = {}

        def visit(n, stack):
            if n in stack:
                return True
            if state.get(n) == 2:
                return False
            state[n] = 1
            for r in req.get(n, []):
                if r in req and visit(r, stack | {n}):
                    return True
            state[n] = 2
            return False

        if any(visit(n, set()) for n in req):
            F.append(_f("MC-G5-005", "milestone_model/milestones", "граф предпосылок содержит цикл"))
        up = sum(float(m.get("value_uplift") or 0) for m in ms)
        if up > 1.0 + 1e-9:
            F.append(_f("MC-G5-006", "milestone_model/milestones", f"Σ value_uplift = {up:.3f} > 1"))
    # MC-G5-007: упорядоченность распределений
    for path, d in _dists(cal):
        kind = (d.get("distribution") or "").lower()
        try:
            if kind in ("triangular", "pert") and not (float(d["min"]) <= float(d["mode"]) <= float(d["max"])):
                F.append(_f("MC-G5-007", path, f"{kind}: нарушено min ≤ mode ≤ max"))
            if kind == "truncated_normal":
                lo, hi = d.get("min"), d.get("max")
                if lo is not None and hi is not None and not (float(lo) < float(hi)):
                    F.append(_f("MC-G5-007", path, "truncated_normal: min < max нарушено"))
                if lo is not None and float(d["mean"]) < float(lo) or hi is not None and float(d["mean"]) > float(hi):
                    F.append(_f("MC-G5-007", path, "truncated_normal: mean вне [min, max]"))
            if kind == "lognormal" and float(d.get("sigma", 0)) <= 0:
                F.append(_f("MC-G5-007", path, "lognormal: sigma должна быть > 0"))
        except (KeyError, TypeError, ValueError) as e:
            F.append(_f("MC-G5-007", path, f"распределение не читается: {e}"))
    # MC-G5-008: границы маржи и PSD корреляций факторов
    mg = cal.get("margin_model") or {}
    if mg.get("lower_bound") is not None and mg.get("upper_bound") is not None and float(mg["lower_bound"]) > float(mg["upper_bound"]):
        F.append(_f("MC-G5-008", "margin_model", "lower_bound > upper_bound"))
    dep = cal.get("dependencies") or {}
    factors = list(dep.get("latent_factors") or [])
    corr = dep.get("factor_correlations") or {}
    if factors:
        import numpy as np
        names = [f if isinstance(f, str) else f.get("id") for f in factors]
        M = np.eye(len(names))
        for key, rho in corr.items():
            a, _, b = str(key).partition("__")
            if a in names and b in names:
                i, j = names.index(a), names.index(b)
                M[i, j] = M[j, i] = float(rho)
        mn = float(np.linalg.eigvalsh(M).min())
        if mn < -1e-9:
            F.append(_f("MC-G5-008", "dependencies/factor_correlations", f"матрица корреляций факторов не PSD (мин. собственное число {mn:.3f})"))
    # MC-G5-013: σ суммарного сдвига цели от всех драйверов на путях Joint Layer (q20)
    if maps and joint_spec is not None and active:
        try:
            import numpy as np
            from engine import joint_layer as jl

            drivers = sorted(active)
            shocks = jl.driver_shocks(joint_spec, drivers, 4000, 24, 7, True, None)
            per: dict = {}
            for m in maps:
                for t in m.get("stochastic_targets") or []:
                    per.setdefault(t["path"], []).append((m["driver_id"], float(t["effect_per_plus_1sigma"]), int(t.get("lag_quarters") or 0), float(t.get("decay_half_life_quarters") or 0)))
            for path, items in per.items():
                tot = None
                for d, e, lag, hl in items:
                    if d not in drivers:
                        continue
                    x = np.asarray(shocks[d] if isinstance(shocks, dict) else shocks[drivers.index(d)])
                    xe = jl.effective_shock(x, lag, hl) if hasattr(jl, "effective_shock") else x
                    tot = e * xe if tot is None else tot + e * xe
                if tot is None:
                    continue
                if path.startswith("milestone_model.milestones."):
                    # Rules v1.1.2: цели вех измеряются в момент применения движком — квартал моды сроков вехи (company_mc._driver_effects), не q20
                    mid = path.split(".")[2]
                    ms_ = next((m for m in ((cal.get("milestone_model") or {}).get("milestones") or []) if m.get("id") == mid), None)
                    qn = int(min(31, max(0, round(float(((ms_ or {}).get("timing") or {}).get("mode", 4))))))
                else:
                    qn = 11 if ".Y3" in path or "Y3" in path.split(".")[-1] else (31 if ".Y8" in path or "Y8" in path.split(".")[-1] else 19)
                sd = float(tot[:, min(qn, tot.shape[1] - 1)].std())
                kind = _target_kind(path); lim = float(limits.get(kind, limits.get("other", 0.15)))
                agg[path] = {"sigma": round(sd, 4), "cap": lim, "kind": kind, "quarter": qn + 1, "drivers": len(items), "sum_abs_effect": round(sum(abs(e) for _, e, _, _ in items), 4), "ok": sd <= lim}
                if sd > lim:
                    F.append(_f("MC-G5-013", f"driver_parameter_mapping → {path}", f"σ суммарного сдвига q{qn + 1} = {sd:.3f} > {lim} ({kind}; драйверов {len(items)}, Σ|effect| {sum(abs(e) for _, e, _, _ in items):.2f})", "warning" if not strict_aggregate else "error"))
                else:
                    F.append(_f("MC-G5-013", f"driver_parameter_mapping → {path}", f"σ суммарного сдвига q{qn + 1} = {sd:.3f} ≤ {lim} ({kind}; драйверов {len(items)})", "info"))
        except Exception as e:  # noqa: BLE001 — диагностика не должна ронять валидацию
            F.append(_f("MC-G5-013", "driver_parameter_mapping", f"не удалось посчитать суммарный сдвиг: {type(e).__name__}: {str(e)[:120]}", "warning"))
    return F


def _dispersion_check(cal: dict, joint_spec: dict | None, rules: dict | None, paths: int, equity_value_0: float) -> tuple[dict, list[dict]]:
    """intrinsic (mapping выключен) vs full: W = q95 − q5 CAGR equity 5Y, ориентиры по архетипу (диагностика, warning)."""
    import copy

    from engine import company_mc as cm

    F: list[dict] = []
    bands = ((rules or {}).get("dispersion_plausibility") or {}).get("reference_bands") or {}
    band = bands.get(cal.get("archetype")) or {}
    res = {}
    for label in ("intrinsic", "full"):
        d = copy.deepcopy(cal)
        if label == "intrinsic":
            d["driver_parameter_mapping"] = []
            d.setdefault("joint_simulation", {})["active_drivers"] = []
        inp = {"calibration": d, "equity_value_0": float(equity_value_0), "paths": paths, "convergence_check": False, "robustness": False}
        if joint_spec is not None:
            inp["joint_layer_spec"] = joint_spec
        b = cm.run(inp, 0)["base"]
        q = b["return"]["CAGR_5Y_quantiles"]
        res[label] = {"W": round(q["0.95"] - q["0.05"], 4), "q05": q["0.05"], "q95": q["0.95"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"],
                      "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"], "P_2x_5Y": b["return"].get("P_2x_5Y")}
    ratio = res["full"]["W"] / res["intrinsic"]["W"] if res["intrinsic"]["W"] > 0 else None
    out = {"paths": paths, "equity_value_0": float(equity_value_0), "intrinsic": res["intrinsic"], "full": res["full"], "full_to_intrinsic_ratio": round(ratio, 3) if ratio else None, "bands": band or None}
    if band:
        lo, hi = band.get("intrinsic_W", [None, None])
        if lo is not None and res["intrinsic"]["W"] < lo:
            F.append(_f("MC-DISP-001", "dispersion/intrinsic", f"intrinsic W = {res['intrinsic']['W']:.3f} ниже ориентира {lo}–{hi}: собственная неопределённость слишком узкая", "warning"))
        elif hi is not None and res["intrinsic"]["W"] > hi:
            F.append(_f("MC-DISP-001", "dispersion/intrinsic", f"intrinsic W = {res['intrinsic']['W']:.3f} выше ориентира {lo}–{hi}", "warning"))
        lo, hi = band.get("full_W", [None, None])
        if lo is not None and res["full"]["W"] < lo:
            F.append(_f("MC-DISP-002", "dispersion/full", f"full W = {res['full']['W']:.3f} ниже ориентира {lo}–{hi}", "warning"))
        elif hi is not None and res["full"]["W"] > hi:
            F.append(_f("MC-DISP-002", "dispersion/full", f"full W = {res['full']['W']:.3f} выше ориентира {lo}–{hi}: двойной счёт / невозможные хвосты", "warning"))
        rmax = band.get("full_to_intrinsic_width_ratio_max")
        if ratio is not None and rmax is not None and ratio > rmax:
            F.append(_f("MC-DISP-003", "dispersion/ratio", f"W_full/W_intrinsic = {ratio:.2f} > {rmax}: Joint Layer доминирует в дисперсии", "warning"))
    return out, F


def _engine_dry_run(cal: dict, joint_spec: dict | None, paths: int) -> dict:
    from engine import company_mc as cm

    inp = {"calibration": cal, "equity_value_0": 1.0e9, "paths": paths, "convergence_check": False, "robustness": False}
    if joint_spec is not None:
        inp["joint_layer_spec"] = joint_spec
    a = cm.run(dict(inp), 0); b = cm.run(dict(inp), 0)
    ba, bb = a["base"], b["base"]
    return {"engine_version": a.get("model_version"), "mapping_warnings": ba.get("mapping_warnings"), "deterministic": ba["return"]["median_CAGR_5Y"] == bb["return"]["median_CAGR_5Y"],
            "median_CAGR_5Y": ba["return"]["median_CAGR_5Y"], "P_loss_gt_30pct_5Y": ba["downside"]["P_loss_gt_30pct_5Y"], "paths": paths}


# ----------------------------------------------------------------------------------------------- прогон
def _source_classes(art_schema: dict) -> set[str]:
    try:
        return set(art_schema["files"]["kpis.yaml"]["properties"]["critical_kpis"]["items"]["properties"]["source_class"]["enum"])
    except KeyError:
        return set()


def validate_documents(docs: dict, art_schema: dict, ws: Path) -> dict:
    files = {}
    n_schema = 0
    for fn in ARTIFACT_FILES:
        if fn in docs and docs[fn] is not None:
            errs = _schema_errors(art_schema["files"][fn], docs[fn])
            files[fn] = {"schema_errors": errs}
            n_schema += len(errs)
    mp = docs.get("mpc_inputs.yaml") or {}
    tax = _taxonomy_ids(ws, mp.get("driver_taxonomy_version")) if mp else None
    findings = integrity_workspace({fn: docs.get(fn) for fn in ARTIFACT_FILES}, tax, _source_classes(art_schema))
    n_err = sum(1 for f in findings if f["severity"] == "error")
    tr = docs.get("triggers.yaml") or {}
    return {"profile": tr.get("profile"), "files": files, "integrity": findings,
            "schema_errors": n_schema, "integrity_errors": n_err, "integrity_warnings": len(findings) - n_err, "pass": n_schema == 0 and n_err == 0}


SCENARIO_SCHEMA_VERSION = "1.0"


def _validate_scenario(inputs: dict, ws: Path, rules: dict) -> dict:
    """Режим scenario (Scenario_Engine_Specification_v1.0 §12): JSON-схема, уникальные id, ацикличность anchor'ов, драйверы в
    таксономии, корни в Joint-схеме, PSD фазовых матриц без ремонта, монотонность стартов (replay), детерминизм, контракт
    вероятностей набора, coverage по компаниям (§9: applicable / unmapped / explicitly_immaterial)."""
    import numpy as np
    from engine import joint_layer as jl
    scen = inputs.get("scenarios") or ([inputs["scenario"]] if inputs.get("scenario") else None)
    if not scen:
        raise ValueError("mode=scenario требует inputs.scenario (dict) или inputs.scenarios (list)")
    schemas: dict = {}   # 1.8.0: схема по schema_version файла (v1.0 и v1.1 сосуществуют; v1.1 = v1.0 + семантический слой)

    def _schema_for(sc_):
        ver = str(sc_.get("schema_version") or SCENARIO_SCHEMA_VERSION)
        if ver not in schemas:
            # явный scenario_schema_path применяется только к файлам версии по умолчанию; иные версии — по имени из methodology
            src = inputs if ver == SCENARIO_SCHEMA_VERSION else {"workspace": inputs.get("workspace")}
            schemas[ver] = _schema(src, "scenario_schema_path", f"Scenario_Engine_Schema_v{ver}.yaml")
        return schemas[ver]
    jspec = inputs.get("joint_layer_spec") or _schema(inputs, "joint_layer_spec_path", "Joint_Simulation_Layer_Schema_v1.0.yaml")
    tax_ver = inputs.get("taxonomy_version") or "1.2"
    tax = _taxonomy_ids(ws, tax_ver) or set()
    audit = inputs.get("coverage_audit") or {}
    n_chk = int(inputs.get("replay_paths", 4000)); Q = int(inputs.get("quarters", 32)); seed = int(inputs.get("global_seed", 20260920))
    per = {}; ids_seen = set(); mx_sets = set(); n_err = 0
    for sc in scen:
        sc = _norm(sc); sid = sc.get("scenario_id") or "?"
        errs = _schema_errors(_schema_for(sc), sc); findings: list[dict] = []
        if sid in ids_seen:
            findings.append(_f("SCN-001", "scenario_id", f"дубликат scenario_id {sid}"))
        ids_seen.add(sid); mx_sets.add(sc.get("mutual_exclusion_set"))
        phases = sc.get("phases") or []; pids = [p.get("phase_id") for p in phases]
        if len(set(pids)) != len(pids):
            findings.append(_f("SCN-002", "phases", "phase_id не уникальны"))
        for i, ph in enumerate(phases):
            anc = str((ph.get("effective_from") or {}).get("anchor", "t0"))
            if anc.startswith("phase:") and anc[6:] not in pids[:i]:
                findings.append(_f("SCN-003", f"phases/{i}/effective_from/anchor", f"{anc}: ссылка на фазу не раньше по списку (ацикличность/порядок)"))
            for d, o in (ph.get("driver_overrides") or {}).items():
                if tax and d not in tax:
                    findings.append(_f("SCN-004", f"phases/{i}/driver_overrides/{d}", f"драйвер {d} не в таксономии v{tax_ver}"))
                if float(o.get("volatility_multiplier", 1.0)) <= 0:
                    findings.append(_f("SCN-005", f"phases/{i}/driver_overrides/{d}", "volatility_multiplier ≤ 0"))
                po = o.get("persistence_override")
                if po is not None and not (0.0 <= float(po) <= 0.99):
                    findings.append(_f("SCN-005", f"phases/{i}/driver_overrides/{d}", "persistence_override вне [0, 0.99]"))
            try:
                T = jl.phase_correlation(jspec, ph); me = float(np.linalg.eigvalsh(T).min())
                findings.append(_f("SCN-006", f"phases/{i}/root_correlation_overrides", f"PSD ok, min eig {me:.4f}", "info"))
            except ValueError as e:
                findings.append(_f("SCN-006", f"phases/{i}/root_correlation_overrides", str(e)))
        # replay: монотонность стартов и детерминизм (малый n)
        replay = None
        if phases and not any(f["severity"] == "error" for f in findings) and not errs:
            try:
                drv = sorted({d for ph in phases for d in (ph.get("driver_overrides") or {})})
                drv_known = [d for d in drv if d in ((jspec.get("driver_generation") or {}).get("mappings") or {})] or drv[:1]
                a = jl.driver_shocks(jspec, drv_known, n_chk, Q, seed, scenario=sc); b = jl.driver_shocks(jspec, drv_known, n_chk, Q, seed, scenario=sc)
                det = all(np.array_equal(a[d], b[d]) for d in drv_known)
                diag = jl.scenario_diagnostics(jspec, sc, drv_known, n_chk, Q, seed)
                replay = {"deterministic": det, "phase_start_quantiles": diag["phase_start_quantiles"], "phase_active_share": diag["phase_active_share"], "n_corr_states": diag["n_corr_states"]}
                if not det:
                    findings.append(_f("SCN-007", "phases", "повторный прогон дал другие шоки — недетерминизм"))
                pers = jl.persistence_diagnostics(jspec, sc, drv_known, n_chk, Q, seed)
                replay["persistence"] = pers
                bad_p = [k for k, v in pers.items() if v.get("ok") is False]
                if bad_p:
                    findings.append(_f("SCN-011", "phases", f"persistence_override: Var(y) или lag-1 corr вне допуска на плато у {bad_p[:6]}", "warning"))
                unmapped_joint = [d for d in drv if d not in ((jspec.get("driver_generation") or {}).get("mappings") or {})]
                if unmapped_joint:
                    findings.append(_f("SCN-008", "phases", f"драйверы без root-mapping в Joint-схеме (идиосинкратические, без корреляции): {unmapped_joint}", "warning"))
            except ValueError as e:
                findings.append(_f("SCN-007", "phases", f"replay: {e}"))
        # coverage §9 по компаниям (калибровки из workspace)
        coverage = {}
        sdrv = sorted({d for ph in phases for d in (ph.get("driver_overrides") or {})})
        for folder, calname in (inputs.get("calibrations") or {}).items():
            cp = ws / "portfolio" / folder / calname
            if not cp.exists():
                coverage[folder] = {"error": f"нет файла {cp.name}"}; continue
            cal = _load(cp); active = set((cal.get("joint_simulation") or {}).get("active_drivers") or [])
            imm = set(((audit.get("decisions") or {}).get(cal.get("ticker") or folder.upper()) or {}).get("explicitly_immaterial") or [])
            excl = set(((audit.get("excluded_semantic_mismatch") or {}).get(cal.get("ticker") or folder.upper()) or []))
            coverage[folder] = {"ticker": cal.get("ticker"), "scenario_drivers_applicable": [d for d in sdrv if d in active and d not in excl],
                                "scenario_drivers_unmapped": [d for d in sdrv if d not in active and d not in imm],
                                "scenario_drivers_explicitly_immaterial": [d for d in sdrv if d in imm], "excluded_semantic_mismatch": sorted(excl & set(sdrv))}
        n_err += len(errs) + sum(1 for f in findings if f["severity"] == "error")
        per[sid] = {"schema_errors": errs, "integrity": findings, "replay": replay, "coverage": coverage,
                    "probability": sc.get("probability"), "probability_status": sc.get("probability_status"), "pass": not errs and not any(f["severity"] == "error" for f in findings)}
    # контракт вероятностей набора (§2)
    prob_findings = []
    # 1.8.0: семантический слой v1.1 (§14–19) — каталог событий, scope, критерии фаз, таблица исходов: SCN-012…015
    sem = _scenario_semantics([_norm(sc) for sc in scen], ws, per)
    prob_findings.extend(sem)
    if len(mx_sets) > 1:
        prob_findings.append(_f("SCN-009", "mutual_exclusion_set", f"сценарии из разных наборов: {sorted(str(x) for x in mx_sets)}"))
    pn = [sc.get("probability") for sc in scen if (sc.get("scenario_id") != "BASE")]
    if all(p is not None for p in pn) and pn:
        if any(float(p) < 0 for p in pn) or sum(float(p) for p in pn) > 1.0 + 1e-12:
            prob_findings.append(_f("SCN-010", "probability", f"Σ non-BASE = {sum(float(p) for p in pn):.4f} > 1 или отрицательная"))
        else:
            prob_findings.append(_f("SCN-010", "probability", f"p_BASE = {1.0 - sum(float(p) for p in pn):.4f} (остаток)", "info"))
    else:
        prob_findings.append(_f("SCN-010", "probability", "pending_owner_judgment: смесь/ScenarioConcentration/§3.3 not_testable", "info"))
    n_err += sum(1 for f in prob_findings if f["severity"] == "error")
    return {"model_version": VERSION, "mode": "scenario", "scenario_schema_version": SCENARIO_SCHEMA_VERSION, "taxonomy_version": tax_ver, "scenarios": per,
            "set_findings": prob_findings, "pass": n_err == 0, "rules": rules, "decision": "none"}


def _scenario_semantics(scen: list, ws: Path, per: dict) -> list:
    """Scenario Engine v1.1 §14–19 (семантический слой; численная семантика не затрагивается). Применяется, если хотя бы один
    сценарий несёт scope. Каталог событий — из scope.event_catalog_ref (methodology/), проверяется по
    Scenario_Event_Catalog_Schema_v1.0.yaml. Правила: SCN-012 — event_id не повторяется в includes разных членов одного набора;
    SCN-013 — у каждого modeled-события ровно один assigned_member ∈ {BASE} ∪ members, non-BASE → ровно один раз в includes этого
    сценария (если сценарий передан), external_events — только OUTSIDE_SET в outcome_mapping; SCN-014 — у каждой фазы непустые
    entry/exit_criteria, event_id есть в каталоге (events ∪ external), fact_id — в fact_catalog сценариев набора, иначе
    system_condition; SCN-015 — includes ∩ excludes = ∅; modeled-событие, не упомянутое ни в scope (includes/excludes/base_when) ни в
    outcome_mapping → warning scenario_event_coverage_gap. Файл состояния portfolio/_scenarios/state.json (если есть) — по
    Scenario_State_Schema_v<schema_version>.yaml (1.0 | 1.1 — партия 10; info/error)."""
    with_scope = [sc for sc in scen if isinstance(sc.get("scope"), dict)]
    if not with_scope:
        return []
    F: list[dict] = []
    refs = {sc["scope"].get("event_catalog_ref") for sc in with_scope}
    if len(refs) != 1:
        F.append(_f("SCN-013", "scope/event_catalog_ref", f"сценарии ссылаются на разные каталоги событий: {sorted(str(r) for r in refs)}")); return F
    cat_name = next(iter(refs)) or "Scenario_Event_Catalog_v1.0.yaml"; cp = ws / "methodology" / str(cat_name)
    if not cp.exists():
        F.append(_f("SCN-013", "scope/event_catalog_ref", f"каталог событий не найден: {cp}")); return F
    cat = _load(cp)
    cs = ws / "methodology" / "Scenario_Event_Catalog_Schema_v1.0.yaml"
    if cs.exists():
        for e in _schema_errors(_load(cs), cat)[:10]:
            F.append(_f("SCN-013", f"catalog/{e['path']}", f"каталог не по схеме: {e['message'][:160]}"))
    events = {e["event_id"]: e for e in (cat.get("events") or [])}
    external = {e["event_id"]: e for e in (cat.get("external_events") or [])}
    sets = {s.get("set_id"): s for s in (cat.get("mutual_exclusion_sets") or [])}
    set_ids = {sc.get("mutual_exclusion_set") for sc in with_scope}
    members_by_set = {sid: set(sets.get(sid, {}).get("members") or []) for sid in set_ids}
    # SCN-012: уникальность includes внутри набора
    seen: dict = {}
    for sc in with_scope:
        for inc in (sc["scope"].get("includes") or []):
            key = (sc.get("mutual_exclusion_set"), inc.get("event_id"))
            if key in seen and seen[key] != sc.get("scenario_id"):
                F.append(_f("SCN-012", f"{sc.get('scenario_id')}/scope/includes/{inc.get('event_id')}", f"событие уже в includes у {seen[key]} (один набор {key[0]})"))
            seen.setdefault(key, sc.get("scenario_id"))
    # SCN-013: принадлежность событий
    present = {sc.get("scenario_id"): sc for sc in with_scope}
    for eid, e in events.items():
        am = e.get("assigned_member")
        set_id = next((sid for sid in set_ids if am == "BASE" or am in members_by_set.get(sid, set())), None)
        if am is None or (am != "BASE" and not any(am in m for m in members_by_set.values())):
            F.append(_f("SCN-013", f"catalog/events/{eid}", f"assigned_member {am!r} не BASE и не член набора(ов) {sorted(str(s) for s in set_ids)}"))
        elif am != "BASE" and am in present:
            n_inc = sum(1 for inc in (present[am]["scope"].get("includes") or []) if inc.get("event_id") == eid)
            if n_inc != 1:
                F.append(_f("SCN-013", f"{am}/scope/includes/{eid}", f"событие приписано {am}, но в includes встречается {n_inc} раз (нужно ровно 1)"))
        elif am != "BASE":
            F.append(_f("SCN-013", f"catalog/events/{eid}", f"assigned_member {am} не передан в этот прогон валидатора — includes не проверены", "warning"))
    for sid, s in sets.items():
        for om in (s.get("outcome_mapping") or []):
            for de in (om.get("defining_event_ids") or []):
                if de in external and om.get("assigned_member") != "OUTSIDE_SET":
                    F.append(_f("SCN-013", f"catalog/mutual_exclusion_sets/{sid}/outcome_mapping/{om.get('outcome_id')}", f"внешнее событие {de} отображено в {om.get('assigned_member')}, допустим только OUTSIDE_SET"))
    # SCN-014: критерии фаз
    facts_all = {fi.get("fact_id") for sc in scen for fi in (sc.get("fact_catalog") or [])}
    for sc in with_scope:
        sid = sc.get("scenario_id")
        for i, ph in enumerate(sc.get("phases") or []):
            for kind in ("entry_criteria", "exit_criteria"):
                crit = ph.get(kind) or []
                if not crit:
                    F.append(_f("SCN-014", f"{sid}/phases/{i}/{kind}", "пусто")); continue
                for c in crit:
                    if c.get("event_id") is not None and c["event_id"] not in events and c["event_id"] not in external:
                        F.append(_f("SCN-014", f"{sid}/phases/{i}/{kind}", f"event_id {c['event_id']} не в каталоге"))
                    if c.get("fact_id") is not None and c["fact_id"] not in facts_all:
                        F.append(_f("SCN-014", f"{sid}/phases/{i}/{kind}", f"fact_id {c['fact_id']} не в каталогах фактов набора"))
                    if c.get("event_id") is None and c.get("fact_id") is None and not c.get("system_condition"):
                        F.append(_f("SCN-014", f"{sid}/phases/{i}/{kind}", "критерий без event_id / fact_id / system_condition"))
    # SCN-015: includes ∩ excludes, покрытие каталога
    mentioned = set()
    for sc in with_scope:
        inc = {x.get("event_id") for x in (sc["scope"].get("includes") or [])}; exc = {x.get("event_id") for x in (sc["scope"].get("excludes") or [])}
        both = sorted(inc & exc)
        if both:
            F.append(_f("SCN-015", f"{sc.get('scenario_id')}/scope", f"события и в includes, и в excludes: {both}"))
        mentioned |= inc | exc | {c.get("event_id") for c in ((sc["scope"].get("base_when") or {}).get("conditions") or [])}
    for s in sets.values():
        for om in (s.get("outcome_mapping") or []):
            mentioned |= set(om.get("defining_event_ids") or [])
    gap = sorted(eid for eid in events if eid not in mentioned)
    if gap:
        F.append(_f("SCN-015", "catalog/events", f"scenario_event_coverage_gap: {gap}", "warning"))
    # состояние сценариев (runtime) — по схеме, если файл есть
    sp = ws / "portfolio" / "_scenarios" / "state.json"
    if sp.exists():
        st = _load(sp); sv = str(st.get("schema_version") or "1.0")               # 1.8.1: схема по schema_version файла (1.0 | 1.1, партия 10)
        ss = ws / "methodology" / f"Scenario_State_Schema_v{sv}.yaml"
        if not ss.exists():
            F.append(_f("SCN-016", "portfolio/_scenarios/state.json", f"scenario_state: нет схемы Scenario_State_Schema_v{sv}.yaml в methodology", "error"))
        else:
            errs = _schema_errors(_load(ss), st)
            F.append(_f("SCN-016", "portfolio/_scenarios/state.json", f"scenario_state по схеме v{sv}" if not errs else f"scenario_state не по схеме v{sv}: {errs[0]['message'][:160]}", "info" if not errs else "error"))
    if not any(f["rule"] in ("SCN-012", "SCN-013", "SCN-014", "SCN-015") and f["severity"] != "info" for f in F):
        F.insert(0, _f("SCN-012", "scope", f"семантический слой v1.1: SCN-012…015 pass (каталог {cat_name}: {len(events)} событий, {len(external)} внешних)", "info"))
    return F


# ------------------------------------------------------------------------------------------- стратегии слоя действий (ACT-001…020)
STRATEGY_SCHEMA_VERSION = "1.0"
TRADE_ACTIONS = ("reduce", "add", "hedge", "cash_target")


def _round_toward_zero(x: float, step: float) -> float:
    return math.copysign(math.floor(abs(x) / step + 1e-9) * step, x)


def _validate_strategy(inputs: dict, ws: Path, rules: dict) -> dict:
    """Режим strategy (1.9.0, партия 10 часть B): ACT-001…020 по Scenario_Action_Validation_Rules v1.0 для файлов стратегий
    `inputs.strategy_files` (пути относительно workspace или абсолютные). Машинно проверяется всё, что проверяемо по файлам хоста:
    схема (001), сценарий в _scenarios с тем же scenario_id/set (002), фазы (003), strategy_ref калибровки → этот файл (004), цели
    действий — тикеры реестра портфеля, инструменты allowlist владельца, CASH (005), GLD ≤ лимита и допустимость весов условного
    оптимума по прогону (006), происхождение чисел (007 — схема), статусы active/executed без одобрения (008), conditional_optimum_ref →
    запись _runs portfolio_optimizer (009), candidate без торговых действий и политика владельца (010), set_state ≠ ambiguous при active
    (011), staleness: max_abs_target_diff > порога без review_required (012), воспроизведение дельт по §5 от базы
    `inputs.base_optimum_run_id` (веса бумаг прогона + фиксированные GLD/UFO из реестра, кэш — остаток) с deadband/округлением к нулю
    (013), turnover cap владельца и порядок «сокращения раньше докупок» (014), risk budget before/after = значения прогона (015),
    пороги policy = решение владельца (016), применимость концентрации — по policy (017, info), exit_rule (018), GLD только owner_rule/review
    без принятой hedge-модели (019), ACT-020 — свойство сигнала агента, не файла (info: шаблон в AGENTS.md)."""
    files = inputs.get("strategy_files") or []
    if not files:
        raise ValueError("mode=strategy требует inputs.strategy_files (список путей)")
    schema = _schema(inputs, "strategy_schema_path", f"Scenario_Strategy_Schema_v{STRATEGY_SCHEMA_VERSION}.yaml")
    reg = _load(ws / "portfolio" / "_portfolio.yaml")
    positions = {str(x.get("ticker")) for x in (reg.get("portfolio") or {}).get("positions") or []}
    cur_w = ((reg.get("machine_outputs") or {}).get("current_weights") or {})
    lim11 = ((reg.get("constraints") or {}).get("approved_limits_v1_1") or {})
    sc_lim = lim11.get("scenario_conditional") or {}; exec_lim = lim11.get("strategy_execution") or {}
    hedge_p = ws / "portfolio" / "_scenarios" / "owner_hedge_instrument_constraints_v1.0.yaml"
    hedge = _load(hedge_p) if hedge_p.exists() else {}
    allowed = {str(i.get("instrument_id")): i for i in hedge.get("allowed_instruments") or []}
    hedge_models = {}
    for hp in (ws / "portfolio" / "_scenarios").glob("hedge_model_*.yaml"):
        hm = _load(hp); hedge_models[str(hm.get("ticker") or hm.get("instrument_id"))] = hm.get("status")
    pol_p = ws / "methodology" / "Portfolio_Optimizer_Scenario_Conditional_Policy_v1.0.yaml"
    policy = _load(pol_p) if pol_p.exists() else None
    state_p = ws / "portfolio" / "_scenarios" / "state.json"
    state = _load(state_p) if state_p.exists() else None
    base_id = inputs.get("base_optimum_run_id")
    base_w = None
    if base_id:
        br = _load(ws / "portfolio" / "_runs" / f"{base_id}.json"); bo = br.get("outputs") or {}
        base_w = {t: float(w) for t, w in (bo.get("proposed_weights") or {}).items()}
        for t in ("GLD", "UFO"):                                              # фиксированные позиции — по текущим весам реестра
            base_w[t] = float(cur_w.get(t, 0.0))
        base_w["CASH"] = 1.0 - sum(v for k, v in base_w.items() if k != "CASH")
    per = []
    for fp in files:
        path = Path(fp) if Path(fp).is_absolute() else ws / fp
        try:
            rel = str(path.resolve().relative_to(ws.resolve())).replace("\\", "/")
        except ValueError:
            rel = str(fp).replace("\\", "/")
        F: list = []
        st = _norm(_load(path))
        errs = _schema_errors(schema, st)
        F.append(_f("ACT-001", rel, "по Scenario_Strategy_Schema v1.0" if not errs else f"схема: {errs[0]['message'][:160]}", "info" if not errs else "error"))
        sid = str(st.get("scenario_id")); sref = ws / str(st.get("scenario_ref") or "")
        scen = _norm(_load(sref)) if sref.exists() else None
        if scen is None or str(scen.get("scenario_id")) != sid:
            F.append(_f("ACT-002", f"{rel}/scenario_ref", f"сценарий {st.get('scenario_ref')} не найден или scenario_id не совпадает"))
        else:
            F.append(_f("ACT-002", rel, f"сценарий {sid} (schema_version {scen.get('schema_version')}) найден", "info"))
        phases = [str(ph.get("phase_id")) for ph in (scen or {}).get("phases") or []]
        sp = [str(ph.get("phase_id")) for ph in st.get("phase_strategies") or []]
        if len(set(sp)) != len(sp) or any(x not in phases for x in sp):
            F.append(_f("ACT-003", f"{rel}/phase_strategies", f"фазы стратегии {sp} не разрешаются уникально в фазах сценария {phases}"))
        else:
            F.append(_f("ACT-003", rel, f"{len(sp)} фаз разрешены", "info"))
        if scen is not None:
            refs = [scen.get("strategy_ref")] + [ph.get("strategy_ref") for ph in scen.get("phases") or []]
            bad = [r for r in refs if r is not None and str(r) != rel]
            if bad:
                F.append(_f("ACT-004", f"{rel}/strategy_ref", f"strategy_ref калибровки указывает не на этот файл: {bad[:2]}"))
            elif all(r is None for r in refs):
                F.append(_f("ACT-004", f"{rel}/strategy_ref", "калибровка сценария ещё не ссылается на стратегию (strategy_ref null) — патч v1.1.1 не применён", "warning"))
            else:
                F.append(_f("ACT-004", rel, "strategy_ref калибровки → этот файл", "info"))
        gld_max = float((allowed.get("GLD") or {}).get("max_weight", 0.10))
        for ph in st.get("phase_strategies") or []:
            pid = ph.get("phase_id"); pp = f"{rel}/{pid}"
            acts = ph.get("actions") or []
            trade = [a for a in acts if a.get("action_type") in TRADE_ACTIONS]
            for a in acts:                                                     # ACT-005 цели
                tg = a.get("target") or {}; k, i = tg.get("kind"), str(tg.get("id"))
                ok = (k == "ticker" and i in positions) or (k == "instrument" and i in allowed) or (k == "cash" and i == "CASH")
                if not ok:
                    F.append(_f("ACT-005", f"{pp}/{a.get('action_id')}", f"цель {k}:{i} вне реестра портфеля / allowlist / CASH"))
            stt = (ph.get("status") or {}); sstate = stt.get("state")          # ACT-008 / 010 / 011
            if sstate in ("active", "executed") and not (stt.get("owner_approved_at") and stt.get("owner_approval_ref") and stt.get("activation_decision_ref")):
                F.append(_f("ACT-008", f"{pp}/status", f"статус {sstate} без owner_approved_at / owner_approval_ref / activation_decision_ref"))
            trig = ph.get("trigger") or {}
            if trig.get("candidate_policy") not in (None, "none", "signal_only", "prepare_only") or trig.get("activate_on_phase_status") != "confirmed":
                F.append(_f("ACT-010", f"{pp}/trigger", f"trigger {trig} — активация только по confirmed; candidate — none/signal_only/prepare_only"))
            if exec_lim.get("candidate_policy") and trig.get("candidate_policy") != exec_lim["candidate_policy"]:
                F.append(_f("ACT-010", f"{pp}/trigger/candidate_policy", f"{trig.get('candidate_policy')} ≠ решение владельца {exec_lim['candidate_policy']}", "warning"))
            if state is not None:
                set_state = ((state.get("set_state") or {}).get("status"))
                if set_state == "ambiguous_set_conflict" and sstate == "active":
                    F.append(_f("ACT-011", f"{pp}/status", "набор в ambiguous_set_conflict — стратегия не может быть active"))
            opt_ref = ph.get("conditional_optimum_ref"); run_o = None           # ACT-009 условный оптимум
            if any(a.get("basis") == "conditional_optimum" for a in acts):
                rp = ws / "portfolio" / "_runs" / f"{opt_ref}.json" if opt_ref else None
                if not rp or not rp.exists():
                    F.append(_f("ACT-009", f"{pp}/conditional_optimum_ref", f"прогон {opt_ref} не найден в _runs"))
                else:
                    run_o = _load(rp)
                    if run_o.get("model") != "portfolio_optimizer":
                        F.append(_f("ACT-009", f"{pp}/conditional_optimum_ref", f"{opt_ref}: модель {run_o.get('model')} ≠ portfolio_optimizer")); run_o = None
                    else:
                        files_in = ((run_o.get("inputs") or {}).get("paths_files") or {})
                        F.append(_f("ACT-009", pp, f"условный оптимум {opt_ref} ({len(files_in)} файлов путей; conditional_run_ref {str(ph.get('conditional_run_ref'))[:70]})", "info"))
            for a in acts:                                                     # ACT-006 GLD-лимит
                tg = a.get("target") or {}
                if str(tg.get("id")) == "GLD" and a.get("action_type") in TRADE_ACTIONS:
                    mag = a.get("magnitude") or {}; amt = float(mag.get("amount", 0.0))
                    tot = amt if mag.get("kind") == "target_weight_nav" else float(cur_w.get("GLD", 0.0)) + amt
                    if tot > gld_max + 1e-9:
                        F.append(_f("ACT-006", f"{pp}/{a.get('action_id')}", f"GLD {tot:.4f} > лимит {gld_max}"))
            if run_o is not None:
                viol = (run_o.get("outputs") or {}).get("violations_at_optimum") or []
                if viol or not (run_o.get("outputs") or {}).get("feasible", True):
                    F.append(_f("ACT-006", f"{pp}/conditional_optimum_ref", f"условный оптимум нарушает лимиты владельца: {[v.get('constraint') for v in viol][:4]}"))
            dp = st.get("derivation_policy") or {}                              # ACT-013 дельты по §5
            dead = float(dp.get("min_action_delta_weight", 0.005)); step = float(dp.get("rounding_increment_weight", 0.0025))
            if run_o is not None and base_w is not None and trade:
                ow = {t: float(w) for t, w in ((run_o.get("outputs") or {}).get("proposed_weights") or {}).items()}
                ow["CASH"] = float((run_o.get("outputs") or {}).get("dry_powder_weight", 0.0))
                exp = {}
                for t in set(ow) | set(base_w):
                    if t in ("GLD", "UFO"):
                        continue
                    d = ow.get(t, 0.0) - base_w.get(t, 0.0)
                    if abs(d) >= dead - 1e-12:
                        exp[t] = round(_round_toward_zero(d, step), 6)
                got = {}
                for a in trade:
                    mag = a.get("magnitude") or {}; tid = str((a.get("target") or {}).get("id"))
                    if mag.get("kind") == "delta_weight_nav":
                        got[tid] = round(float(mag.get("amount", 0.0)), 6)
                diff = {t: (exp.get(t), got.get(t)) for t in set(exp) | set(got) if abs((exp.get(t) or 0.0) - (got.get(t) or 0.0)) > 1e-6}
                if diff:
                    F.append(_f("ACT-013", pp, f"дельты не воспроизводятся по §5 от базы {base_id}: {diff}"))
                else:
                    F.append(_f("ACT-013", pp, f"дельты воспроизведены по §5 (deadband {dead}, шаг {step}) от базы {base_id}: {len(got)} действий", "info"))
            cap = ph.get("turnover_cap_nav")                                    # ACT-014 cap и порядок
            if trade:
                if not cap or (cap.get("provenance") != "owner_judgment"):
                    F.append(_f("ACT-014", f"{pp}/turnover_cap_nav", "у фазы с торговыми действиями нет turnover_cap_nav (owner_judgment)"))
                else:
                    gross = sum(abs(float((a.get("magnitude") or {}).get("amount", 0.0))) for a in trade if (a.get("magnitude") or {}).get("kind") == "delta_weight_nav")
                    if gross > float(cap.get("value")) + 1e-9:
                        F.append(_f("ACT-014", f"{pp}/turnover_cap_nav", f"валовый оборот {gross:.4f} > cap {cap.get('value')}"))
                    if exec_lim.get("turnover_cap_nav_per_signal") is not None and abs(float(cap.get("value")) - float(exec_lim["turnover_cap_nav_per_signal"])) > 1e-9:
                        F.append(_f("ACT-014", f"{pp}/turnover_cap_nav", f"cap {cap.get('value')} ≠ решение владельца {exec_lim['turnover_cap_nav_per_signal']}", "warning"))
                red_start = [int((a.get("timing") or {}).get("start_after_trading_days", 0)) for a in trade if a.get("action_type") == "reduce"]
                add_start = [int((a.get("timing") or {}).get("start_after_trading_days", 0)) for a in trade if a.get("action_type") == "add"]
                if red_start and add_start and max(red_start) > min(add_start):
                    F.append(_f("ACT-014", f"{pp}/actions", "докупки стартуют раньше сокращений — сокращения должны быть забюджетированы первыми"))
            rb = ph.get("risk_budget_under_scenario")                          # ACT-015 risk budget = прогон
            if rb and run_o is not None:
                o = run_o.get("outputs") or {}; cur = (o.get("current_portfolio") or {}).get("return_distribution_Y5") or {}
                y5 = (o.get("portfolio_return_distribution") or {}).get("Y5") or {}; d5 = (o.get("portfolio_downside") or {}).get("Y5") or {}
                pairs = {("before", "median_cagr_5y"): cur.get("median_CAGR"), ("before", "es5_5y"): cur.get("expected_shortfall_5pct"), ("before", "p_loss_30_5y"): cur.get("P_loss_gt_30pct"),
                         ("after", "median_cagr_5y"): y5.get("median_CAGR"), ("after", "es5_5y"): d5.get("expected_shortfall_5pct"), ("after", "p_loss_30_5y"): d5.get("P_loss_gt_30pct")}
                bad = []
                for (side, key), ref in pairs.items():
                    m = (rb.get(side) or {}).get(key) or {}
                    if ref is None or m.get("provenance") != "derived_fact" or abs(float(m.get("value", 9)) - float(ref)) > 5e-4:
                        bad.append(f"{side}.{key}: {m.get('value')} vs прогон {ref}")
                if bad:
                    F.append(_f("ACT-015", f"{pp}/risk_budget_under_scenario", f"risk budget не равен значениям прогона {opt_ref}: {bad[:3]}"))
                else:
                    F.append(_f("ACT-015", pp, f"risk budget before/after = прогон {opt_ref} (derived_fact)", "info"))
            elif trade and not rb:
                F.append(_f("ACT-015", f"{pp}/risk_budget_under_scenario", "у фазы с торговыми действиями нет risk_budget_under_scenario"))
            ex = ph.get("exit_rule") or {}                                      # ACT-018
            if not ex.get("mode"):
                F.append(_f("ACT-018", f"{pp}/exit_rule", "exit_rule отсутствует"))
            elif ex.get("mode") == "owner_defined_reversal" and not ex.get("owner_rule_ref"):
                F.append(_f("ACT-018", f"{pp}/exit_rule", "owner_defined_reversal без owner_rule_ref"))
            for a in acts:                                                     # ACT-019 GLD
                if str((a.get("target") or {}).get("id")) == "GLD" and a.get("basis") == "conditional_optimum" and hedge_models.get("GLD") != "accepted":
                    F.append(_f("ACT-019", f"{pp}/{a.get('action_id')}", "GLD с basis conditional_optimum без принятой Hedge_Instrument_Model"))
            sl = ph.get("staleness") or {}                                      # ACT-012
            thr = float(dp.get("live_optimum_review_threshold", 0.02))
            if sl.get("max_abs_target_diff") is not None and float(sl["max_abs_target_diff"]) > thr and not sl.get("review_required"):
                F.append(_f("ACT-012", f"{pp}/staleness", f"max_abs_target_diff {sl['max_abs_target_diff']} > {thr}, но review_required = false"))
        if policy is not None:                                                 # ACT-016 / 017
            cc = policy.get("conditional_constraints") or {}
            want = {"probability_min": sc_lim.get("p_min"), "es5_5y_min": sc_lim.get("es5_min"), "p_loss_30_5y_max": sc_lim.get("p_loss_gt_30_max")}
            bad = [k for k, v in want.items() if v is not None and abs(float((cc.get(k) or {}).get("value", 9)) - float(v)) > 1e-9]
            cmax = ((policy.get("scenario_concentration") or {}).get("hard_max") or {}).get("value")
            if sc_lim.get("scenario_concentration_max") is not None and (cmax is None or abs(float(cmax) - float(sc_lim["scenario_concentration_max"])) > 1e-9):
                bad.append("scenario_concentration_max")
            F.append(_f("ACT-016", "methodology/Portfolio_Optimizer_Scenario_Conditional_Policy_v1.0.yaml", "пороги policy = решение владельца" if not bad else f"расхождение policy и решения владельца: {bad}", "info" if not bad else "error"))
            F.append(_f("ACT-017", "policy/scenario_concentration", str((policy.get("scenario_concentration") or {}).get("applicability"))[:120], "info"))
        F.append(_f("ACT-020", rel, "свойство сигнала агента, не файла: шаблон с «Решение за владельцем. Автоисполнение запрещено.» — AGENTS.md", "info"))
        n_err = sum(1 for f in F if f["severity"] == "error")
        per.append({"file": rel, "strategy_id": st.get("strategy_id"), "scenario_id": sid, "phases": sp, "findings": F, "errors": n_err, "pass": not errs and n_err == 0})
    return {"model_version": VERSION, "mode": "strategy", "strategy_schema_version": STRATEGY_SCHEMA_VERSION, "base_optimum_run_id": base_id, "strategies": per,
            "pass": all(x["pass"] for x in per), "rules": {**rules, "act": [f"ACT-{i:03d}" for i in range(1, 21)]}, "decision": "none"}


def run(inputs: dict, seed: int) -> dict:
    mode = inputs.get("mode", "workspace")
    ws = _workspace(inputs)
    rules = {"implemented": sorted({f"ART-REF-{i:03d}" for i in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 30, 31)} |
                                   {f"CAND-REF-{i:03d}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17)}),
             "partial_or_not_implemented": NOT_IMPLEMENTED}
    if mode == "candidate":
        cand = inputs.get("candidate")
        if not isinstance(cand, dict):
            raise ValueError("mode=candidate требует inputs.candidate (dict)")
        schema = _schema(inputs, "candidate_schema_path", f"Company_Candidate_Schema_v{CANDIDATE_SCHEMA_VERSION}.yaml")
        cand = _norm(cand)
        errs = _schema_errors(schema, cand)
        tax = _taxonomy_ids(ws, (cand.get("mpc_inputs") or {}).get("driver_taxonomy_version"))
        findings = integrity_candidate(cand, tax)
        n_err = sum(1 for f in findings if f["severity"] == "error")
        return {"model_version": VERSION, "schema_version": CANDIDATE_SCHEMA_VERSION, "mode": mode, "ticker": cand.get("ticker"),
                "schema_errors": errs, "integrity": findings, "pass": not errs and n_err == 0, "rules": rules, "decision": "none"}
    if mode == "calibration":
        cal = inputs.get("calibration")
        if not isinstance(cal, dict):
            raise ValueError("mode=calibration требует inputs.calibration (dict)")
        cal = _norm(cal)
        cal_sv = str(cal.get("schema_version") or CALIBRATION_SCHEMA_VERSION)
        if cal_sv not in CALIBRATION_SCHEMA_VERSIONS:
            cal_sv = CALIBRATION_SCHEMA_VERSION  # неизвестная версия — проверяется текущей схемой, const schema_version даст ошибку схемы
        schema = _schema(inputs, "calibration_schema_path", f"Company_MC_Calibration_Schema_v{cal_sv}.yaml")
        errs = _schema_errors(schema, cal)
        folders = inputs.get("folders") or []
        mpc = None
        if folders:
            mp = ws / "portfolio" / folders[0] / "mpc_inputs.yaml"
            mpc = _load(mp) if mp.exists() else None
        jp = Path(inputs.get("joint_layer_spec_path") or (ws / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml"))
        joint_spec = inputs.get("joint_layer_spec") or (yaml.safe_load(jp.read_text(encoding="utf-8")) if jp.exists() else None)
        limits = dict(AGG_SHIFT_LIMITS); limits.update(inputs.get("aggregate_shift_limits") or {})
        rp = Path(inputs.get("joint_rules_path") or (ws / "methodology" / "Joint_Simulation_Layer_Rules_v1.1.2.yaml"))
        rules = yaml.safe_load(rp.read_text(encoding="utf-8")) if rp.exists() else None
        agg: dict = {}
        findings = integrity_calibration(cal, mpc, joint_spec, limits, bool(inputs.get("strict_aggregate", True)), agg)
        engine = None
        dispersion = None
        if inputs.get("engine_dry_run", True) and not errs:
            try:
                engine = _engine_dry_run(cal, joint_spec, int(inputs.get("dry_run_paths", 2000)))
                for w in engine.get("mapping_warnings") or []:
                    findings.append(_f("MC-G5-003", "driver_parameter_mapping", f"движок: {w}"))
                if not engine.get("deterministic"):
                    findings.append(_f("MC-G5-DET", "simulation", "два прогона с одним seed дали разные результаты"))
            except Exception as e:  # noqa: BLE001
                findings.append(_f("MC-G5-ENGINE", "calibration", f"движок не принял калибровку: {type(e).__name__}: {str(e)[:200]}"))
            if inputs.get("dispersion_check", True) and not [f for f in findings if f["rule"] == "MC-G5-ENGINE"]:
                eq0 = inputs.get("equity_value_0")
                if not eq0:
                    findings.append(_f("MC-DISP-000", "dispersion", "equity_value_0 не задан — диагностика дисперсии (W зависит от стартовой стоимости) пропущена", "warning"))
                else:
                  try:
                    dispersion, dF = _dispersion_check(cal, joint_spec, rules, int(inputs.get("dispersion_paths", 20000)), eq0)
                    findings.extend(dF)
                  except Exception as e:  # noqa: BLE001
                    findings.append(_f("MC-DISP-000", "dispersion", f"диагностика дисперсии не выполнена: {type(e).__name__}: {str(e)[:160]}", "warning"))
        n_err = sum(1 for f in findings if f["severity"] == "error")
        return {"model_version": VERSION, "schema_version": cal_sv, "mode": mode, "ticker": cal.get("ticker"), "archetype": cal.get("archetype"),
                "schema_errors": errs, "integrity": findings, "engine_dry_run": engine, "aggregate_shift": agg, "dispersion": dispersion, "pass": not errs and n_err == 0,
                "note": "MC-G5-013 — hard gate по Joint_Simulation_Layer_Rules_v1.1 (strict_aggregate=false → warning); MC-G5-009 (антицикличность) и MC-G5-010 (полнота provenance сверх схемы) статически не проверяются", "decision": "none"}
    if mode == "scenario":
        return _validate_scenario(inputs, ws, rules)
    if mode == "strategy":
        return _validate_strategy(inputs, ws, rules)
    if mode == "dozor_report":
        rep = inputs.get("report")
        if not isinstance(rep, dict):
            raise ValueError("mode=dozor_report требует inputs.report (dict)")
        proto = _schema(inputs, "dozor_protocol_path", f"Dozor_Verification_Protocol_v{DOZOR_PROTOCOL_VERSION}.yaml")
        rep = _norm(rep)
        errs = _schema_errors(proto["output_report_schema"], rep)
        findings: list[dict] = []
        folders = inputs.get("folders") or []
        kp = st_doc = tr_doc = None
        if folders:
            fd = ws / "portfolio" / folders[0]
            kp = _load(fd / "kpis.yaml") if (fd / "kpis.yaml").exists() else None
            st_doc = _load(fd / "states.yaml") if (fd / "states.yaml").exists() else None
            tr_doc = _load(fd / "triggers.yaml") if (fd / "triggers.yaml").exists() else None
        if kp is not None:
            ids = {k.get("id") for k in kp.get("critical_kpis", [])}
            if kp.get("ticker") and rep.get("ticker") and kp.get("ticker") != rep.get("ticker"):
                findings.append(_f("DZR-001", "ticker", f"{rep.get('ticker')!r} ≠ kpis.yaml {kp.get('ticker')!r}"))
            for i, it in enumerate(rep.get("items") or []):
                if it.get("kpi_id") not in ids:
                    findings.append(_f("DZR-002", f"items/{i}/kpi_id", f"{it.get('kpi_id')!r} не найден в kpis.yaml"))
        # реестр статусов протокола (v1.1+: status_registry.<группа>.<статус>; v1.0: runtime_verified_mapping)
        reg = proto.get("status_registry") or {}
        legacy_map = proto.get("runtime_verified_mapping") or {}
        patch_statuses = ("mismatch_value", "mismatch_period", "mismatch_semantics", "formula_mismatch", "source_not_allowed")
        v12 = str(rep.get("protocol_version") or "").startswith("1.2")

        def _expect(group, status):
            e = (reg.get(group) or {}).get(status)
            if e is not None:
                return e.get("runtime_verified"), bool(e.get("default_patch_required"))
            v = legacy_map.get(status)
            return (v if isinstance(v, bool) else None), status in patch_statuses

        def _check(group, path, obj, key="status"):
            exp, need_patch = _expect(group, obj.get(key))
            if isinstance(exp, bool) and obj.get("runtime_verified") is not exp:
                findings.append(_f("DZR-003", f"{path}/runtime_verified", f"для статуса {obj.get(key)!r} ожидается {exp!r}, получено {obj.get('runtime_verified')!r}"))
            if need_patch and obj.get("patch_required") is not True:
                findings.append(_f("DZR-004", f"{path}/patch_required", f"статус {obj.get(key)!r} требует patch_required=true"))

        for i, it in enumerate(rep.get("items") or []):
            _check("kpi", f"items/{i}", it)
            fnd, cnd = it.get("found") or {}, it.get("candidate") or {}
            if v12 and it.get("status") in VERIFIED_KPI_STATUSES and fnd.get("formula_recomputed_value") is not None:  # DZR-012: derived_fact в базе кандидата
                fv, cv = fnd.get("value"), cnd.get("last_value")
                same_val = isinstance(fv, (int, float)) and isinstance(cv, (int, float)) and abs(fv - cv) <= 1e-3 * max(abs(cv), 1e-12)
                if fnd.get("unit") != cnd.get("unit") or not same_val:
                    findings.append(_f("DZR-012", f"items/{i}/found", f"derived_fact: found {fv!r} {fnd.get('unit')!r} не в базе кандидата {cv!r} {cnd.get('unit')!r}; слагаемые источника — в normalization.steps"))
        summ = rep.get("summary") or {}
        ids_patch = {it.get("kpi_id") for it in rep.get("items") or [] if it.get("patch_required")}
        if set(summ.get("patch_required_kpis") or []) != ids_patch:
            findings.append(_f("DZR-005", "summary/patch_required_kpis", f"не совпадает с items: {sorted(ids_patch)}"))
        # v1.1: оси и события
        axes = ((st_doc or {}).get("axes") or {}) if st_doc else None
        kpi_ids_rep = {it.get("kpi_id") for it in rep.get("items") or []}
        for i, a in enumerate(rep.get("axis_items") or []):
            ax = a.get("axis_id")
            if axes is not None and ax not in axes:
                findings.append(_f("DZR-006", f"axis_items/{i}/axis_id", f"ось {ax!r} не найдена в states.yaml"))
            elif axes is not None and a.get("current_state") not in ("pending_verification", None) and a.get("current_state") not in (axes[ax].get("states") or {}):
                findings.append(_f("DZR-006", f"axis_items/{i}/current_state", f"состояние {a.get('current_state')!r} не найдено в оси {ax!r}"))
            for r in a.get("kpi_item_refs") or []:
                if r not in kpi_ids_rep:
                    findings.append(_f("DZR-007", f"axis_items/{i}/kpi_item_refs", f"{r!r} не входит в items этого отчёта"))
            _check("axis", f"axis_items/{i}", a)
            if v12 and a.get("current_state") == "pending_verification" and (a.get("criteria") is not None or not a.get("pending_reason")):  # DZR-014
                findings.append(_f("DZR-014", f"axis_items/{i}", "каноническое pending_verification: criteria должен быть null, pending_reason — непустым (псевдокритерий не выдумывается)"))
        trig_map = {t.get("id"): t for t in (tr_doc or {}).get("triggers", [])} if tr_doc else None
        trig_ids = set(trig_map) if trig_map is not None else None
        for i, ev in enumerate(rep.get("event_items") or []):
            if trig_ids is not None and ev.get("trigger_id") not in trig_ids:
                findings.append(_f("DZR-008", f"event_items/{i}/trigger_id", f"{ev.get('trigger_id')!r} не найден в triggers.yaml"))
            if ev.get("fact_only") is not True:
                findings.append(_f("DZR-009", f"event_items/{i}/fact_only", "событие подтверждает факт, не переход и не действие: fact_only должен быть true"))
            _check("event", f"event_items/{i}", ev)
            if ev.get("status") == "condition_not_met" and ev.get("patch_required"):  # DZR-015
                findings.append(_f("DZR-015", f"event_items/{i}/patch_required", "condition_not_met — pass без правки: patch_required должен быть false"))
        # v1.2: transition_checks — проверки условий переходов (DZR-011 ссылки, реестр transition_result, DZR-015)
        ev_ids = {e.get("trigger_id") for e in rep.get("event_items") or []}
        trs = rep.get("transition_checks") or []
        for i, t in enumerate(trs):
            tid = t.get("trigger_id"); p = f"transition_checks/{i}"
            if trig_map is not None:
                tt = trig_map.get(tid)
                if tt is None:
                    findings.append(_f("DZR-011", f"{p}/trigger_id", f"{tid!r} не найден в triggers.yaml"))
                else:
                    if tt.get("axis") and tt.get("axis") != t.get("axis"):
                        findings.append(_f("DZR-011", f"{p}/axis", f"{t.get('axis')!r} ≠ ось триггера {tt.get('axis')!r} в triggers.yaml"))
                    ttr = tt.get("transition") or {}
                    if ttr and (ttr.get("from"), ttr.get("to")) != ((t.get("transition") or {}).get("from"), (t.get("transition") or {}).get("to")):
                        findings.append(_f("DZR-011", f"{p}/transition", f"{t.get('transition')!r} ≠ переход триггера {ttr!r} в triggers.yaml"))
            if axes is not None:
                if t.get("axis") not in axes:
                    findings.append(_f("DZR-011", f"{p}/axis", f"ось {t.get('axis')!r} не найдена в states.yaml"))
                else:
                    sts = axes[t.get("axis")].get("states") or {}
                    for end in ("from", "to"):
                        s = (t.get("transition") or {}).get(end)
                        if s not in sts:
                            findings.append(_f("DZR-011", f"{p}/transition/{end}", f"состояние {s!r} не найдено в оси {t.get('axis')!r}"))
            for r in t.get("kpi_item_refs") or []:
                if r not in kpi_ids_rep:
                    findings.append(_f("DZR-011", f"{p}/kpi_item_refs", f"{r!r} не входит в items этого отчёта"))
            for r in t.get("event_item_refs") or []:
                if r not in ev_ids:
                    findings.append(_f("DZR-011", f"{p}/event_item_refs", f"{r!r} не входит в event_items этого отчёта"))
            _check("transition_result", p, t, key="result")
            if t.get("result") in ("met", "not_met") and t.get("patch_required"):
                findings.append(_f("DZR-015", f"{p}/patch_required", f"result={t.get('result')} — pass без правки: patch_required должен быть false"))
        ax_patch = {a.get("axis_id") for a in rep.get("axis_items") or [] if a.get("patch_required")}
        if set(summ.get("patch_required_axes") or []) != ax_patch:
            findings.append(_f("DZR-005", "summary/patch_required_axes", f"не совпадает с axis_items: {sorted(ax_patch)}"))
        ev_patch = {e.get("trigger_id") for e in rep.get("event_items") or [] if e.get("patch_required")}
        if set(summ.get("patch_required_events") or []) != ev_patch:
            findings.append(_f("DZR-005", "summary/patch_required_events", f"не совпадает с event_items: {sorted(ev_patch)}"))
        tr_patch = {t.get("trigger_id") for t in trs if t.get("patch_required")}
        if set(summ.get("patch_required_transition_checks") or []) != tr_patch:
            findings.append(_f("DZR-005", "summary/patch_required_transition_checks", f"не совпадает с transition_checks: {sorted(tr_patch)}"))
        tr_pend = {t.get("trigger_id") for t in trs if t.get("result") == "pending_history"}
        if (trs or "pending_transition_checks" in summ) and set(summ.get("pending_transition_checks") or []) != tr_pend:
            findings.append(_f("DZR-005", "summary/pending_transition_checks", f"не совпадает с transition_checks: {sorted(tr_pend)}"))
        # DZR-010: итог по старшинству (gate_aggregation протокола); condition_not_met / met / not_met — pass, не pending
        st_kpi = [it.get("status") for it in rep.get("items") or []]
        st_ax = [a.get("status") for a in rep.get("axis_items") or []]
        st_ev = [e.get("status") for e in rep.get("event_items") or []]
        blocked_conflict = "source_conflict" in st_kpi or "evidence_conflict" in st_ax
        blocked_tech = "source_unavailable_technical" in st_kpi or "evidence_unavailable_technical" in st_ax or "source_unavailable_technical" in st_ev
        pending = ("not_found" in st_kpi or "event_unconfirmed" in st_ev or bool(tr_pend)
                   or any(a.get("status") == "state_pending_verification" and not a.get("patch_required") for a in rep.get("axis_items") or []))
        expected = ("BLOCKED_SOURCE_CONFLICT" if blocked_conflict else "BLOCKED_TECHNICAL" if blocked_tech else "PATCH_REQUIRED" if (ids_patch or ax_patch or ev_patch or tr_patch)
                    else "PASS_WITH_DECLARED_PENDING" if pending else "PASS")
        if summ.get("overall_status") != expected:
            findings.append(_f("DZR-010", "summary/overall_status", f"по старшинству статусов ожидается {expected!r}, в отчёте {summ.get('overall_status')!r}"))
        n_err = sum(1 for f in findings if f["severity"] == "error")
        return {"model_version": VERSION, "protocol_version": DOZOR_PROTOCOL_VERSION, "mode": mode, "ticker": rep.get("ticker"), "run_id": rep.get("run_id"),
                "schema_errors": errs, "integrity": findings, "pass": not errs and n_err == 0, "decision": "none"}
    art = _schema(inputs, "schema_path", f"Company_Artifact_Schema_v{SCHEMA_VERSION}.yaml")
    results = {}
    if inputs.get("documents"):
        results["<documents>"] = validate_documents(_norm(inputs["documents"]), art, ws)
    else:
        skip = set(inputs.get("skip_folders", ["spacex"]))
        folders = inputs.get("folders", "all")
        if folders == "all":
            names = [p.name for p in sorted((ws / "portfolio").iterdir()) if p.is_dir() and not p.name.startswith("_") and p.name not in skip and (p / "triggers.yaml").exists()]
        else:
            names = list(folders)
        for name in names:
            d = ws / "portfolio" / name
            if not d.exists():
                results[name] = {"error": "папка не найдена", "pass": False}
                continue
            docs = {fn: _load(d / fn) for fn in ARTIFACT_FILES if (d / fn).exists()}
            results[name] = validate_documents(docs, art, ws)
    n_pass = sum(1 for r in results.values() if r.get("pass"))
    return {"model_version": VERSION, "schema_version": SCHEMA_VERSION, "mode": mode, "workspace": str(ws), "folders": results,
            "summary": {"folders": len(results), "pass": n_pass, "fail": len(results) - n_pass,
                        "failed": sorted(k for k, r in results.items() if not r.get("pass"))},
            "rules": rules, "decision": "none"}
