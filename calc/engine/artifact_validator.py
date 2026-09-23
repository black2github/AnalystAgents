"""Валидатор артефактов компаний v1.2 — гейт G5 (Runtime_Quality_Gates: schema + ID + references) по Company Artifact
Schema v1.0.4 и Company Candidate Schema v1.0.1 (принято 22.09.2026; нормативный дом схем — workspace/methodology/).
Нулевой LLM: JSON Schema Draft 2020-12 по каждому файлу + правила целостности ART-REF-* / CAND-REF-* кодом.
Даты YAML нормализуются к ISO-строкам до проверки (MIG-111 — правило валидатора, не схемы).

inputs:
  mode: "workspace" (по умолчанию) | "candidate" | "dozor_report" | "calibration" (calibration: dict по Company MC Calibration
        Schema; folders: ["<папка>"] для MC-G5-001 по mpc_inputs; правила MC-G5-001..013 кодом, MC-G5-013 — σ суммарного
        сдвига цели на путях Joint Layer (по умолчанию warning; strict_aggregate: true → error); engine_dry_run: true —
        company_mc на малом числе путей: mapping_warnings, детерминизм)
        | "dozor_report" (report: dict по output_report_schema протокола дозора;
        "folders": ["<папка>"] для сверки с kpis/states/triggers папки; правила DZR-001..010: тикер, kpi_id, runtime_verified и
        patch_required по status_registry протокола, согласованность summary, оси/состояния/kpi_item_refs, trigger_id, fact_only, итог)
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
import os
import re
from pathlib import Path

import yaml

VERSION = "1.3.0"
SCHEMA_VERSION = "1.0.4"            # Company Artifact Schema (v1.0.4: recorded_at, verification_run_id у осей/событий)
CANDIDATE_SCHEMA_VERSION = "1.0.1"  # Company Candidate Schema (не менялась с партии 1)
DOZOR_PROTOCOL_VERSION = "1.1"      # Dozor Verification Protocol (схема отчёта output_report_schema; отчёты v1.0 валидны)
CALIBRATION_SCHEMA_VERSION = "1.0.1"  # Company MC Calibration Schema (калибровки company_mc v2)
# MC-G5-013 (предложение 23.09, до принятия IMMA — предупреждение): порог σ суммарного сдвига цели от всех драйверов на q20
AGG_SHIFT_LIMITS = {"growth": 0.15, "margin": 0.05, "multiple": 0.15, "milestone": 0.75, "other": 0.15}
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
    for v in (drivers.values() if isinstance(drivers, dict) else [drivers]):
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
        return "milestone"
    return "other"


def integrity_calibration(cal: dict, mpc: dict | None, joint_spec: dict | None, limits: dict, strict_aggregate: bool) -> list[dict]:
    F: list[dict] = []
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
                sd = float(tot[:, min(19, tot.shape[1] - 1)].std())
                kind = _target_kind(path); lim = float(limits.get(kind, limits.get("other", 0.15)))
                if sd > lim:
                    F.append(_f("MC-G5-013", f"driver_parameter_mapping → {path}", f"σ суммарного сдвига q20 = {sd:.3f} > {lim} ({kind}; драйверов {len(items)}, Σ|effect| {sum(abs(e) for _, e, _, _ in items):.2f})", "error" if strict_aggregate else "warning"))
        except Exception as e:  # noqa: BLE001 — диагностика не должна ронять валидацию
            F.append(_f("MC-G5-013", "driver_parameter_mapping", f"не удалось посчитать суммарный сдвиг: {type(e).__name__}: {str(e)[:120]}", "warning"))
    return F


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


def run(inputs: dict, seed: int) -> dict:
    mode = inputs.get("mode", "workspace")
    ws = _workspace(inputs)
    rules = {"implemented": sorted({f"ART-REF-{i:03d}" for i in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)} |
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
        schema = _schema(inputs, "calibration_schema_path", f"Company_MC_Calibration_Schema_v{CALIBRATION_SCHEMA_VERSION}.yaml")
        cal = _norm(cal)
        errs = _schema_errors(schema, cal)
        folders = inputs.get("folders") or []
        mpc = None
        if folders:
            mp = ws / "portfolio" / folders[0] / "mpc_inputs.yaml"
            mpc = _load(mp) if mp.exists() else None
        jp = Path(inputs.get("joint_layer_spec_path") or (ws / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml"))
        joint_spec = inputs.get("joint_layer_spec") or (yaml.safe_load(jp.read_text(encoding="utf-8")) if jp.exists() else None)
        limits = dict(AGG_SHIFT_LIMITS); limits.update(inputs.get("aggregate_shift_limits") or {})
        findings = integrity_calibration(cal, mpc, joint_spec, limits, bool(inputs.get("strict_aggregate", False)))
        engine = None
        if inputs.get("engine_dry_run", True) and not errs:
            try:
                engine = _engine_dry_run(cal, joint_spec, int(inputs.get("dry_run_paths", 2000)))
                for w in engine.get("mapping_warnings") or []:
                    findings.append(_f("MC-G5-003", "driver_parameter_mapping", f"движок: {w}"))
                if not engine.get("deterministic"):
                    findings.append(_f("MC-G5-DET", "simulation", "два прогона с одним seed дали разные результаты"))
            except Exception as e:  # noqa: BLE001
                findings.append(_f("MC-G5-ENGINE", "calibration", f"движок не принял калибровку: {type(e).__name__}: {str(e)[:200]}"))
        n_err = sum(1 for f in findings if f["severity"] == "error")
        return {"model_version": VERSION, "schema_version": CALIBRATION_SCHEMA_VERSION, "mode": mode, "ticker": cal.get("ticker"), "archetype": cal.get("archetype"),
                "schema_errors": errs, "integrity": findings, "engine_dry_run": engine, "pass": not errs and n_err == 0,
                "note": "MC-G5-013 (σ суммарного сдвига) — предложение 23.09, до принятия IMMA выдаётся как warning; MC-G5-009 (антицикличность) и MC-G5-010 (полнота provenance сверх схемы) статически не проверяются", "decision": "none"}
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
        # реестр статусов протокола (v1.1: status_registry.<группа>.<статус>; v1.0: runtime_verified_mapping)
        reg = proto.get("status_registry") or {}
        legacy_map = proto.get("runtime_verified_mapping") or {}
        patch_statuses = ("mismatch_value", "mismatch_period", "mismatch_semantics", "formula_mismatch", "source_not_allowed")

        def _expect(group, status):
            e = (reg.get(group) or {}).get(status)
            if e is not None:
                return e.get("runtime_verified"), bool(e.get("default_patch_required"))
            v = legacy_map.get(status)
            return (v if isinstance(v, bool) else None), status in patch_statuses

        def _check(group, path, obj):
            exp, need_patch = _expect(group, obj.get("status"))
            if isinstance(exp, bool) and obj.get("runtime_verified") is not exp:
                findings.append(_f("DZR-003", f"{path}/runtime_verified", f"для статуса {obj.get('status')!r} ожидается {exp!r}, получено {obj.get('runtime_verified')!r}"))
            if need_patch and obj.get("patch_required") is not True:
                findings.append(_f("DZR-004", f"{path}/patch_required", f"статус {obj.get('status')!r} требует patch_required=true"))

        for i, it in enumerate(rep.get("items") or []):
            _check("kpi", f"items/{i}", it)
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
        trig_ids = {t.get("id") for t in (tr_doc or {}).get("triggers", [])} if tr_doc else None
        for i, ev in enumerate(rep.get("event_items") or []):
            if trig_ids is not None and ev.get("trigger_id") not in trig_ids:
                findings.append(_f("DZR-008", f"event_items/{i}/trigger_id", f"{ev.get('trigger_id')!r} не найден в triggers.yaml"))
            if ev.get("fact_only") is not True:
                findings.append(_f("DZR-009", f"event_items/{i}/fact_only", "событие подтверждает факт, не переход и не действие: fact_only должен быть true"))
            _check("event", f"event_items/{i}", ev)
        ax_patch = {a.get("axis_id") for a in rep.get("axis_items") or [] if a.get("patch_required")}
        if set(summ.get("patch_required_axes") or []) != ax_patch:
            findings.append(_f("DZR-005", "summary/patch_required_axes", f"не совпадает с axis_items: {sorted(ax_patch)}"))
        ev_patch = {e.get("trigger_id") for e in rep.get("event_items") or [] if e.get("patch_required")}
        if set(summ.get("patch_required_events") or []) != ev_patch:
            findings.append(_f("DZR-005", "summary/patch_required_events", f"не совпадает с event_items: {sorted(ev_patch)}"))
        if (ids_patch or ax_patch or ev_patch) and summ.get("overall_status") not in ("PATCH_REQUIRED", "BLOCKED_TECHNICAL", "BLOCKED_SOURCE_CONFLICT"):
            findings.append(_f("DZR-010", "summary/overall_status", "есть patch_required, а итог не PATCH_REQUIRED/BLOCKED_*"))
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
