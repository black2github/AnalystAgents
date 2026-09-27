"""Сухой прогон детерминированной миграции артефактов компаний к Company Artifact Schema v1.0.1 (MIG-101..111 + §7).
Ничего не пишет: читает workspace, мигрирует в памяти, валидирует, печатает остаток ошибок. Основа для боевой миграции."""
import copy, datetime, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator as V

DL = Path("C:/Users/alexe/Downloads")
W = Path(sys.argv[1] if len(sys.argv) > 1 else "C:/openclaw-lab/data/workspace-invest/portfolio")
ART = yaml.safe_load(open(DL / "Company_Artifact_Schema_v1.0.1.yaml", encoding="utf-8"))
FILES = ["states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml", "state.json"]
SV = "1.0.1"


def norm_dates(o):
    if isinstance(o, dict): return {k: norm_dates(v) for k, v in o.items()}
    if isinstance(o, list): return [norm_dates(v) for v in o]
    if isinstance(o, (datetime.date, datetime.datetime)): return o.isoformat()
    return o


def load(p):
    return norm_dates(json.load(open(p, encoding="utf-8")) if p.suffix == ".json" else yaml.safe_load(open(p, encoding="utf-8")))


def source_class(url: str | None, label: str | None) -> str:
    u = (url or "").lower(); t = (label or "").lower()
    if "yahoo" in u or "yahoo" in t: return "market_data_provider"
    if "transcript" in u or "transcript" in t or "call" in t: return "issuer_transcript"
    if "presentation" in u or "presentation" in t or "slides" in t: return "issuer_investor_presentation"
    if "sec.gov" in u:
        return "issuer_ir_release" if re.search(r"ex[-_]?99|ex99|_pr\.|press", u) else "regulatory_filing"
    if t in ("sec",) or "10-q" in t or "10-k" in t or "6-k" in t or "20-f" in t: return "regulatory_filing"
    if u or t: return "issuer_ir_release"
    return "other_primary"


def split_value(v):
    """last_value → (number|None, extra) по MIG-105 и §7."""
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return None, {"observation_qualifier": "range", "value_range": {"min": v[0], "max": v[1]}}
    if isinstance(v, str):
        m = re.fullmatch(r"\s*([<>]=?)\s*([-+]?\d+(?:\.\d+)?)\s*", v)
        if m:
            return float(m.group(2)), {"observation_qualifier": "lower_bound" if m.group(1).startswith(">") else "upper_bound"}
        m = re.fullmatch(r"\s*~\s*([-+]?\d+(?:\.\d+)?)\s*", v)
        if m: return float(m.group(1)), {"observation_qualifier": "approximate"}
    return v, {}


def migrate_kpi_like(k, val_key):
    v, extra = split_value(k.get(val_key))
    k[val_key] = v; k.update(extra)
    vt = k.get("value_type")
    if vt in ("lower_bound", "upper_bound", "approximate"):
        k["observation_qualifier"] = vt; k["value_type"] = "actual"
    elif vt is None:
        k["value_type"] = "actual"
    k.setdefault("provenance", "verified_fact")


def migrate(folder: Path):
    docs = {fn: load(folder / fn) for fn in FILES if (folder / fn).exists()}
    full = all(fn in docs for fn in ("states.yaml", "kpis.yaml", "mpc_inputs.yaml"))
    for d in docs.values(): d["schema_version"] = SV
    st = docs.get("states.yaml")
    if st:
        sem = st.setdefault("semantics", {})
        if "numeric_thresholds_provenance" not in sem:
            sem["numeric_thresholds_provenance"] = sem.pop("thresholds_provenance", None) or "model_assumption"
        else: sem.pop("thresholds_provenance", None)
        sem.setdefault("evidence_required", True); sem.setdefault("pending_verification_blocks_transition", True); sem.setdefault("trigger_not_decision", True)
        src = st.get("sources") or {}
        for key, val in list(src.items()):
            if isinstance(val, str): val = {"url": val}
            val = dict(val)
            val.setdefault("source_class", source_class(val.get("url"), val.get("type") or key))
            val.setdefault("as_of", val.get("date") or st.get("as_of"))
            val.pop("date", None)
            src[key] = val
    kp = docs.get("kpis.yaml")
    if kp:
        for k in kp.get("critical_kpis", []):
            k.setdefault("source_class", source_class(k.get("source_url"), k.get("source")))
            migrate_kpi_like(k, "last_value")
            th = k.get("thresholds") or {}
            if "yellow" not in th and set(th) >= {"green", "red"}:
                g, r = str(th["green"]), str(th["red"])
                if re.fullmatch(r"\s*=?\s*(1|0|true|false|yes|no)\s*", g, re.I) and re.fullmatch(r"\s*=?\s*(1|0|true|false|yes|no)\s*", r, re.I):
                    th["binary"] = True  # MIG-106: только когда зоны бинарны по форме
    tr = docs.get("triggers.yaml")
    if tr:
        tr.setdefault("profile", "full_model" if full else "registry_only")
        au = tr.get("automations")
        if isinstance(au, dict) and "_note" in au:
            tr["automations_note"] = au.pop("_note")
        for t in tr.get("triggers", []):
            if "transition" in t: t.setdefault("condition_provenance", "model_assumption")
            if tr["profile"] == "full_model": t.setdefault("fired", [])
        if tr["profile"] == "full_model":
            if "rules" not in tr and st:
                sem = st["semantics"]
                tr["rules"] = {k: sem[k] for k in ("evidence_required", "pending_verification_blocks_transition", "trigger_not_decision")}
            meta = tr.setdefault("meta", {})
            sj = docs.get("state.json") or {}
            meta.setdefault("source_artifact", (kp or {}).get("source_artifact"))
            meta.setdefault("price_source", (sj.get("price") or {}).get("source") or "Yahoo Finance chart (дозор)")
            meta.setdefault("price_at_registry", (sj.get("price") or {}).get("last"))
            meta.setdefault("position", None)
        meta = tr.get("meta") or {}
        if isinstance(meta.get("horizon"), int): meta["horizon"] = str(meta["horizon"])
    mp = docs.get("mpc_inputs.yaml")
    if mp: mp.setdefault("driver_vector_provenance", "model_assumption")
    sj = docs.get("state.json")
    if sj:
        for o in sj.get("kpi_observations", []) or []: migrate_kpi_like(o, "value")
        if isinstance(sj.get("conviction"), dict): sj["conviction"].setdefault("provenance", "owner_judgment")
        if isinstance(sj.get("notes"), str): sj["notes"] = [sj["notes"]]
        elif sj.get("notes") is None: sj["notes"] = []
        for key in ("fired", "events_reported", "pending_verification", "info_log", "state_transitions", "kpi_observations", "calc_runs"): sj.setdefault(key, [])
        sj.setdefault("scenario_state", {})
    return docs


if __name__ == "__main__":
    folders = [p for p in sorted(W.iterdir()) if p.is_dir() and not p.name.startswith("_") and (p / "triggers.yaml").exists() and p.name != "spacex"]
    residual = defaultdict(set); totals = {}
    for f in folders:
        docs = migrate(f); n = 0
        for fn, d in docs.items():
            for e in V(ART["files"][fn]).iter_errors(d):
                n += 1
                path = "/".join(str(x) for x in e.path if not isinstance(x, int))
                residual[(fn, path, re.sub(r"\{.*", "{…}", e.message)[:140])].add(f.name)
        totals[f.name] = n
    print("остаток ошибок после миграции:", totals)
    for (fn, p, m), cs in sorted(residual.items()): print(f"- {fn} {p or '<root>'}: {m} — {', '.join(sorted(cs))}")
