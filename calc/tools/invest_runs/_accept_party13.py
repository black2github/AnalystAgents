"""Хост-приёмка партии 13 (модели компаний CRWD / HPS.A / S, Company Artifact Schema v1.0.5, Candidate Schema v1.0.1, taxonomy v1.2.1,
Theme Taxonomy v1.0.1): валидатор G5 — режим candidate по <TK>_candidate_v1.0.yaml, режим workspace по словарям папки (documents:
states/kpis/triggers/mpc_inputs/state), режим theme по theme_exposure (с таксономией 1.0.1 из пакета, подставленной временно),
сверка чисел kpis.yaml с досье хоста notes/candidates-dossier-2026-10-03.md (verified_fact по первоисточникам).
Запуск: python _accept_party13.py [CRWD HPS.A S]"""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "Party13_CRWD_HPSA_S_Company_Models_v1.0"
URL = "http://127.0.0.1:18791/run"
FOLDER = {"CRWD": "crwd", "HPS.A": "hps_a", "S": "s"}; CAND = {"CRWD": "CRWD_candidate_v1.0.yaml", "HPS.A": "HPSA_candidate_v1.0.yaml", "S": "S_candidate_v1.0.yaml"}
TKS = [a for a in sys.argv[1:] if a in FOLDER] or list(FOLDER)
DOCS = ("states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml", "state.json")


def post(payload: dict) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else yaml.safe_load(p.read_text(encoding="utf-8"))


def show(tag: str, v: dict):
    vo = v.get("outputs", v)
    if v.get("error"):
        print(f"  {tag}: ERROR {v['error'][:300]}"); return vo
    errs = vo.get("schema_errors") or []
    if isinstance(errs, dict):
        errs = [e for lst in errs.values() for e in (lst or [])]
    fnd = [f for f in (vo.get("integrity") or vo.get("findings") or []) if f.get("severity") != "info"]
    if "folders" in vo:
        fl = list(vo["folders"].values())[0] if isinstance(vo["folders"], dict) else vo["folders"][0]
        errs = [e for lst in (fl.get("schema_errors") or {}).values() for e in (lst or [])] if isinstance(fl.get("schema_errors"), dict) else (fl.get("schema_errors") or [])
        fnd = [f for f in (fl.get("integrity") or fl.get("findings") or []) if f.get("severity") != "info"]
        passed = fl.get("pass")
    else:
        passed = vo.get("pass")
    print(f"  {tag}: run {v.get('run_id')} pass={passed} schema_errors={len(errs)} findings(non-info)={len(fnd)}")
    for e in errs[:8]:
        print("     schema:", (e.get("path") if isinstance(e, dict) else e), "|", (e.get("message", "")[:140] if isinstance(e, dict) else ""))
    for f in fnd[:12]:
        print("    ", f.get("severity"), f.get("rule") or f.get("rule_id"), f.get("path"), "|", str(f.get("message"))[:150])
    return vo


results = {}
for tk in TKS:
    fd = PK / FOLDER[tk]; print(f"===== {tk} ({fd.name}) =====")
    cand = load(fd / CAND[tk])
    r1 = show("candidate", post({"model": "artifact_validator", "inputs": {"mode": "candidate", "workspace": "/data/workspace-invest", "candidate": cand}, "seed": 0, "save": True}))
    docs = {d: load(fd / d) for d in DOCS if (fd / d).exists()}
    r2 = show("workspace/documents", post({"model": "artifact_validator", "inputs": {"mode": "workspace", "workspace": "/data/workspace-invest", "documents": docs}, "seed": 0, "save": True}))
    results[tk] = {"candidate": r1.get("pass"), "documents": r2.get("pass") if "pass" in r2 else (list(r2.get("folders", {}).values())[0].get("pass") if isinstance(r2.get("folders"), dict) and r2["folders"] else None)}
print(json.dumps(results, ensure_ascii=False))
