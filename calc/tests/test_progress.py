"""Вехи прогресса (engine.progress): файл _progress-<model>.json пишется в _runs_dir с done/total/eta, принудительные вехи обходят
интервал, finish удаляет файл; без _runs_dir — только stdout, без ошибок."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.progress import Progress  # noqa: E402


def test_progress_file_and_finish(tmp_path):
    p = Progress("demo", {"_run_id": "r1", "_runs_dir": str(tmp_path)}, total=4, min_interval_s=1000)
    p.stage_start("tasks", 4, note="старт")
    f = tmp_path / "_progress-demo.json"; d = json.loads(f.read_text(encoding="utf-8"))
    assert d["stage"] == "tasks" and d["total"] == 4 and d["done"] == 0 and d["run_id"] == "r1" and d["eta_s"] is None
    p.tick(); p.tick()                                                   # интервал не истёк — файл не перезаписан
    assert json.loads(f.read_text(encoding="utf-8"))["done"] == 0
    p.emit(force=True); d = json.loads(f.read_text(encoding="utf-8"))
    assert d["done"] == 2 and d["eta_s"] is not None
    p.finish("готово")
    assert not f.exists()


def test_progress_without_runs_dir():
    p = Progress("demo", {}, total=2, min_interval_s=0)
    p.stage_start("x"); p.tick(); p.finish()
    assert p.done == 1 and p.stage == "done"
