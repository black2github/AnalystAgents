"""Сайдкар расчётного движка инвестиционного дозора (каркас).

Контракт (предварительный, до спецификации):
  GET  /health            — версия, библиотеки, доступность данных workspace
  GET  /models            — зарегистрированные модели движка (engine/registry)
  POST /run               — {"model": str, "version": str|None, "inputs": {...}, "seed": int|None,
                             "save": bool}  → {"run_id", "model", "version", "seed", "outputs", "saved_to"}
  GET  /runs?limit=N      — последние записи прогонов из portfolio/_runs/
Каждый прогон детерминирован: seed фиксируется и записывается; запись прогона хранит входы целиком.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, "/app")
DATA = Path(os.environ.get("CALC_DATA", "/data/workspace-invest"))
RUNS = DATA / "portfolio" / "_runs"

app = FastAPI(title="invest-calc", version="0.1.0")


class RunRequest(BaseModel):
    model: str
    version: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    save: bool = True


def _registry() -> dict[str, Any]:
    from engine import registry  # noqa: WPS433 — динамический импорт, engine монтируется с хоста
    importlib.reload(registry)
    return registry.MODELS


@app.get("/health")
def health() -> dict[str, Any]:
    import numpy, pandas, scipy  # noqa: E401
    return {
        "status": "ok",
        "service": "invest-calc",
        "version": app.version,
        "python": platform.python_version(),
        "libs": {"numpy": numpy.__version__, "pandas": pandas.__version__, "scipy": scipy.__version__},
        "data_mounted": DATA.exists(),
        "runs_dir": str(RUNS),
        "models": sorted(_registry().keys()),
    }


@app.get("/models")
def models() -> dict[str, Any]:
    return {name: {"version": m["version"], "doc": m["doc"]} for name, m in _registry().items()}


@app.post("/run")
def run(req: RunRequest) -> dict[str, Any]:
    reg = _registry()
    if req.model not in reg:
        raise HTTPException(404, f"unknown model {req.model!r}; known: {sorted(reg)}")
    entry = reg[req.model]
    if req.version and req.version != entry["version"]:
        raise HTTPException(409, f"model {req.model} has version {entry['version']}, requested {req.version}")
    seed = req.seed if req.seed is not None else int(time.time()) % 1_000_000
    t0 = time.perf_counter()
    outputs = entry["fn"](req.inputs, seed)
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + req.model + "-" + uuid.uuid4().hex[:6]
    record = {
        "run_id": run_id,
        "model": req.model,
        "version": entry["version"],
        "seed": seed,
        "inputs": req.inputs,
        "outputs": outputs,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "service": {"name": "invest-calc", "version": app.version},
    }
    saved_to = None
    if req.save:
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"{run_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        saved_to = str(path.relative_to(DATA))
    record["saved_to"] = saved_to
    return record


@app.get("/runs")
def runs(limit: int = 20) -> dict[str, Any]:
    if not RUNS.exists():
        return {"runs": []}
    files = sorted(RUNS.glob("*.json"), reverse=True)[:limit]
    out = []
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            out.append({"run_id": r.get("run_id"), "model": r.get("model"), "version": r.get("version"),
                        "seed": r.get("seed"), "elapsed_ms": r.get("elapsed_ms")})
        except Exception as e:  # noqa: BLE001
            out.append({"file": f.name, "error": str(e)[:80]})
    return {"runs": out}
