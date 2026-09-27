"""Патч _integrate_batch4.py: адаптивный дамп state.json (формат по содержимому файла, как в _update_calc_runs_232.py)."""
from pathlib import Path

p = Path(__file__).with_name("_integrate_batch4.py"); s = p.read_text(encoding="utf-8")
old_start = s.index("def dump(st: dict) -> str:"); old_end = s.index("import os")
new_dump = r'''def dump(st: dict, raw: str) -> str:
    """Формат файла определяется по содержимому (как _update_calc_runs_232.py): однострочные наблюдения kpi_observations —
    только если они такие в файле; строковые массивы verification_run_ids — в одну строку, если так в файле; завершающий
    перевод строки — как в файле."""
    one_line = bool(re.search(r'\n\s*\{"kpi_id": ', raw))
    inline_ids = bool(re.search(r'"verification_run_ids": \[[ \t]*"', raw))
    st2 = dict(st); obs = st.get("kpi_observations") or []
    if one_line and obs:
        st2["kpi_observations"] = [f"@@OBS{i}@@" for i in range(len(obs))]
    txt = json.dumps(st2, ensure_ascii=False, indent=2) + "\n"
    if one_line:
        for i, o in enumerate(obs):
            txt = txt.replace(f'"@@OBS{i}@@"', json.dumps(o, ensure_ascii=False))
    if inline_ids:
        txt = re.sub(r'"verification_run_ids": \[\n((?:[ \t]*"[^"\n]*",?\n)+)[ \t]*\]', lambda m: '"verification_run_ids": [' + ", ".join(x.strip().rstrip(",") for x in m.group(1).strip().split("\n")) + "]", txt)
    return txt if raw.endswith("\n") else txt.rstrip("\n")


'''
s = s[:old_start] + new_dump + s[old_end:]
a = r'idem = dump(st) == raw.replace("\r\n", "\n")'
b = r'idem = dump(st, raw.replace("\r\n", "\n")) == raw.replace("\r\n", "\n")'
assert s.count(a) == 1; s = s.replace(a, b)
a2 = "                    fh.write(dump(st))"
b2 = r'                    fh.write(dump(st, raw.replace("\r\n", "\n")))'
assert s.count(a2) == 1; s = s.replace(a2, b2)
p.write_text(s, encoding="utf-8", newline="\n"); print("patched")
