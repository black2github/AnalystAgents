"""Предпросмотр (НЕ норматив): применить patch-plan IMMA к META/ASML v1.0 в памяти и измерить intrinsic/full W валидатором.
Интерпретации: *_delta_pp — сдвиг границы в п.п. с ограничением floor/ceiling; *_pct_of_mode — сдвиг границы на долю моды
(min − |pct|·mode, max + pct·mode). Имена сегментов ASML в плане (EUV/DUV/InstalledBase) сопоставлены фактическим."""
import copy
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); SRC = WS / "from_imma" / "LLY_META_ASML_Calibrations_v1"; PL = WS / "from_imma" / "META_ASML_v1.0.1_patchplan"
URL = "http://127.0.0.1:18791/run"
ALIAS = {"EUV": "EUV_Systems", "DUV": "DUV_Systems", "InstalledBase": "InstalledBaseManagement"}


def get(d, path):
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, dict) and k in ALIAS and ALIAS[k] in cur:
            cur = cur[ALIAS[k]]
        else:
            return None
    return cur


def apply(cal, plan):
    c = copy.deepcopy(cal); log = []
    for op in plan["operations"]:
        d = get(c, op["path"])
        if d is None or "distribution" not in d:
            log.append(f"НЕТ ПУТИ: {op['path']}"); continue
        lo, mo, hi = float(d["min"]), float(d["mode"]), float(d["max"])
        if "lower_tail_delta_pp" in op:
            nlo, nhi = lo + float(op["lower_tail_delta_pp"]), hi + float(op["upper_tail_delta_pp"])
            b = op.get("bounds") or {}
            if "min_floor" in b: nlo = max(nlo, float(b["min_floor"]))
            if "max_ceiling" in b: nhi = min(nhi, float(b["max_ceiling"]))
        else:
            nlo, nhi = lo - abs(float(op["lower_tail_pct_of_mode"])) * mo, hi + float(op["upper_tail_pct_of_mode"]) * mo
        d["min"], d["max"] = round(nlo, 4), round(nhi, 4)
        log.append(f"{op['path']}: [{lo}, {mo}, {hi}] → [{d['min']}, {mo}, {d['max']}]")
    return c, log


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=1800))


for tk in ("META", "ASML"):
    cal = yaml.safe_load((SRC / f"{tk}_mc_calibration_v1.0.yaml").read_text(encoding="utf-8"))
    plan = yaml.safe_load((PL / f"{tk}_mc_calibration_v1.0.1_PATCH_PLAN.yaml").read_text(encoding="utf-8"))
    eq0 = yaml.safe_load((SRC / f"{tk}_calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]["market"]["equity_value"]
    patched, log = apply(cal, plan)
    print(f"===== {tk}: применено {sum(1 for l in log if not l.startswith('НЕТ'))} из {len(log)} операций")
    for l in log:
        print("  ", l)
    v = post({"model": "artifact_validator", "inputs": {"mode": "calibration", "workspace": "/data/workspace-invest", "calibration": patched, "folders": [tk.lower()], "equity_value_0": eq0, "dispersion_paths": 20000, "dry_run_paths": 1500}, "seed": 0, "save": False})
    o = v.get("outputs", v); d = o.get("dispersion") or {}
    print(f"   валидатор pass {o.get('pass')} | schema_errors {len(o.get('schema_errors') or [])} | intrinsic W {d.get('intrinsic', {}).get('W')} / full W {d.get('full', {}).get('W')} | bands {d.get('bands')}")
    for f in o.get("integrity") or []:
        if f["severity"] == "error":
            print("   ", f["rule"], f["path"], f["message"][:120])
