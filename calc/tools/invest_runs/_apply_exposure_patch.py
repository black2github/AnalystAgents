"""Применение Scenario_Company_Exposure_Patch_v1.1 (IMMA) к каноническим mpc_inputs.yaml пяти компаний — построчно, с
сохранением байтов (CRLF, порядок ключей): добавить ACCELERATOR_PRICE_COMPETITION в driver_exposure_vector (после
SPACE_REGULATION — последний ключ вектора), у MSFT/META TAIWAN_SUPPLY −1 → +1 (только в векторе; проверка «from»),
driver_taxonomy_version '1.1' → '1.2.1'. Остальные поля не трогать. Запуск: python _apply_exposure_patch.py [--apply]"""
import sys
import yaml
from pathlib import Path

WS = Path("C:/openclaw-lab/data/workspace-invest"); APPLY = "--apply" in sys.argv
patch = yaml.safe_load((WS / "from_imma/Joint_v1.1_Taxonomy_v1.2.1_Reissues/Scenario_Company_Exposure_Patch_v1.1.yaml").read_text(encoding="utf-8"))
for tk, drv in patch["companies"].items():
    p = WS / "portfolio" / tk.lower() / "mpc_inputs.yaml"; raw = p.read_bytes(); nl = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8").split(nl); out = []; in_vec = False; changes = []
    for ln in lines:
        if ln.startswith("driver_exposure_vector:"):
            in_vec = True; out.append(ln); continue
        if in_vec and not ln.startswith("  "):
            in_vec = False
        if in_vec:
            key = ln.strip().split(":")[0]
            if key == "TAIWAN_SUPPLY" and "TAIWAN_SUPPLY" in drv:
                cur = int(ln.split(":")[1]); assert cur == drv["TAIWAN_SUPPLY"]["from"], (tk, cur)
                ln = f"  TAIWAN_SUPPLY: {drv['TAIWAN_SUPPLY']['value']}"; changes.append(f"TAIWAN_SUPPLY {cur} → {drv['TAIWAN_SUPPLY']['value']}")
            if key == "ACCELERATOR_PRICE_COMPETITION":
                raise SystemExit(f"{tk}: ACCELERATOR_PRICE_COMPETITION уже есть")
            out.append(ln)
            if key == "SPACE_REGULATION":
                out.append(f"  ACCELERATOR_PRICE_COMPETITION: {drv['ACCELERATOR_PRICE_COMPETITION']['value']}"); changes.append(f"+ACCELERATOR_PRICE_COMPETITION {drv['ACCELERATOR_PRICE_COMPETITION']['value']}")
            continue
        if ln.startswith("driver_taxonomy_version:"):
            assert "'1.1'" in ln, (tk, ln); ln = "driver_taxonomy_version: '1.2.1'"; changes.append("taxonomy 1.1 → 1.2.1")
        out.append(ln)
    new = nl.join(out).encode("utf-8")
    assert "ACCELERATOR_PRICE_COMPETITION" in new.decode("utf-8") and "'1.2.1'" in new.decode("utf-8"), tk
    print(f"{tk}: {', '.join(changes)} | CRLF={nl == chr(13)+chr(10)}")
    if APPLY:
        p.write_bytes(new)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
