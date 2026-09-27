"""Предпросмотр миграции v1.0.5 на копии workspace: применить, прогнать валидатор 1.5.0, показать историю прогонов NBIS/ASTS."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "C:/openclaw-lab/calc")
from engine import artifact_validator as av  # noqa: E402
from tools import migrate_artifacts_v1_0_1 as mig  # noqa: E402

WS = Path("C:/openclaw-lab/data/workspace-invest")
tmp = Path(tempfile.mkdtemp(prefix="mig105_"))
shutil.copytree(WS / "portfolio", tmp / "portfolio", ignore=shutil.ignore_patterns("_runs", "*.parquet", "*.npz"))
shutil.copytree(WS / "methodology", tmp / "methodology")
before = {}
for f in mig.iter_folders(tmp, None):
    before[f.name] = {fn: (f / fn).read_bytes() for fn in mig.FILES if (f / fn).exists()}
reps = [mig.migrate_folder(f, apply=True) for f in mig.iter_folders(tmp, None)]
print("ошибки:", [r for r in reps if r["errors"]] or "нет")
again = [mig.migrate_folder(f, apply=False) for f in mig.iter_folders(tmp, None)]
print("идемпотентность:", "OK" if all(not r["changed"] and not r["errors"] for r in again) else [r for r in again if r["changed"]])
for n, files in before.items():
    for fn, old in files.items():
        new = (tmp / "portfolio" / n / fn).read_bytes()
        assert (b"\r\n" in old) == (b"\r\n" in new), (n, fn, "CRLF изменился")
        assert old.count(b"#") <= new.count(b"#"), (n, fn, "комментарии потеряны")
print("байты: CRLF и комментарии сохранены")
out = av.run({"workspace": str(tmp), "folders": "all"}, 0)
print("валидатор 1.5.0 после миграции:", out["summary"])
for k, v in out["folders"].items():
    if not v["pass"]:
        print("  ", k, v["files"], [f for f in v["integrity"] if f["severity"] == "error"][:5])
for n in ("nbis", "asts"):
    sj = json.loads((tmp / "portfolio" / n / "state.json").read_text(encoding="utf-8"))
    print(f"{n}: наблюдений {len(sj['kpi_observations'])}")
    for o in sj["kpi_observations"]:
        print("   ", o["kpi_id"], o.get("period_end"), o.get("value"), o.get("value_range"), o.get("observation_qualifier"), "| ids:", o.get("verification_run_ids"), "| last:", o.get("verification_run_id"), "| value_raw:", "да" if o.get("value_raw") else "нет")
print("tmp:", tmp)
