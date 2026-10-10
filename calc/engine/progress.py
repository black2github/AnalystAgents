"""Вехи прогресса долгих моделей (правило владельца 10.10.2026): периодически — не полный журнал — писать, какие этапы пройдены, чтобы извне
оценивать продвижение и время завершения. Два канала: файл <_runs_dir>/_progress-<model>.json ({model, run_id, stage, done, total,
started_at, updated_at, elapsed_s, eta_s, note}) — перезаписывается целиком, и строка в stdout контейнера (docker logs). Частота — не чаще
раза в min_interval_s (по умолчанию 60 с), плюс обязательные вехи (force=True: смена этапа, завершение). Без _runs_dir файл не пишется
(тесты). Ошибки записи глушатся — прогресс не должен ронять расчёт."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


class Progress:
    def __init__(self, model: str, inputs: dict | None = None, total: int | None = None, min_interval_s: float = 60.0):
        inputs = inputs or {}
        self.model = model; self.run_id = inputs.get("_run_id"); self.rd = inputs.get("_runs_dir") or os.environ.get("CALC_PROGRESS_DIR")
        self.total = total; self.done = 0; self.stage = "start"; self.t0 = time.time(); self.last = 0.0; self.min_interval = float(min_interval_s)

    def set_total(self, total: int) -> None:
        self.total = int(total)

    def stage_start(self, stage: str, total: int | None = None, note: str = "") -> None:
        self.stage = stage
        if total is not None:
            self.total = int(total); self.done = 0
        self.emit(force=True, note=note)

    def tick(self, n: int = 1, note: str = "") -> None:
        self.done += n
        self.emit(note=note)

    def finish(self, note: str = "готово") -> None:
        self.stage = "done"; self.emit(force=True, note=note)
        try:
            p = self._path()
            if p and p.exists():
                p.unlink()                                                   # по завершении файл прогресса убирается (результат — в прогоне)
        except Exception:  # noqa: BLE001
            pass

    def _path(self) -> Path | None:
        return (Path(self.rd) / f"_progress-{self.model}.json") if self.rd else None

    def emit(self, force: bool = False, note: str = "") -> None:
        now = time.time()
        if not force and now - self.last < self.min_interval:
            return
        self.last = now; el = now - self.t0
        eta = (el / self.done * (self.total - self.done)) if (self.total and self.done) else None
        rec = {"model": self.model, "run_id": self.run_id, "stage": self.stage, "done": self.done, "total": self.total, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t0)),
               "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "elapsed_s": round(el), "eta_s": (round(eta) if eta is not None else None), "note": note}
        try:
            print(f"[progress {self.model}] {self.stage} {self.done}/{self.total} elapsed {el / 60:.1f} мин" + (f", ETA {eta / 60:.1f} мин" if eta is not None else "") + (f" — {note}" if note else ""), file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            p = self._path()
            if p:
                p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
