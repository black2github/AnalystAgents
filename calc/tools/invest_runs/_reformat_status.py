"""Переформатирование хвоста STATUS.md (замечание владельца 25.09): записи-«простыни» (одна строка > 160 символов после
последнего заголовка «## 23.09 УТРО…») → заголовок «## <дата>: <суть>» + текст с переносами по ~118 символов.
Байты: LF/CRLF как в файле, кодировка UTF-8. Идемпотентно (повторный запуск ничего не меняет). Запуск: python _reformat_status.py [--apply]"""
import re
import sys
import textwrap
from pathlib import Path

P = Path("C:/openclaw-lab/data/workspace-invest/STATUS.md"); APPLY = "--apply" in sys.argv
raw = P.read_bytes(); nl = "\r\n" if b"\r\n" in raw else "\n"; lines = raw.decode("utf-8").split(nl)
start = max(i for i, l in enumerate(lines) if l.startswith("## 23.09 УТРО")) + 1
out = lines[:start]; changed = 0
DATE_RE = re.compile(r"^(\d{2}\.\d{2})(?:[ ,:—-]+)?(.*)$")


LAST = {"date": "23.09"}
FIND_DATE = re.compile(r"(2[2-6]\.09)")


def header(text: str) -> tuple[str, str]:
    """Заголовок: дата (из начала записи, иначе первая дата 22–26.09 в первых 250 символах, иначе дата предыдущей
    записи — записи хронологические) + суть до первого « — », «: » или « (», не длиннее 95 символов; тело — вся запись."""
    m = DATE_RE.match(text)
    if m:
        date = m.group(1)
    else:
        f = FIND_DATE.search(text[:250]); date = f.group(1) if f else LAST["date"]
    LAST["date"] = date
    body_for_title = m.group(2) if m else text
    cut = len(body_for_title)
    for sep in (" — ", ": ", " ("):
        j = body_for_title.find(sep)
        if 12 < j < cut:
            cut = j
    title = body_for_title[:cut].strip().rstrip(":—-, ")
    if len(title) > 95:
        title = title[:92].rsplit(" ", 1)[0] + "…"
    return f"## {date}: {title}", text


for l in lines[start:]:
    if len(l) > 160 and not l.startswith("#") and not l.startswith("|") and not l.startswith("- ") and not l.startswith("  "):
        h, body = header(l); changed += 1
        out.append(h); out.append("")
        out.extend(textwrap.wrap(body, width=118, break_long_words=False, break_on_hyphens=False))
    else:
        out.append(l)
# схлопнуть тройные пустые строки
res = []
for l in out:
    if l == "" and len(res) >= 2 and res[-1] == "" and res[-2] == "":
        continue
    res.append(l)
print(f"записей переформатировано: {changed}; строк {len(lines)} → {len(res)}; режим: {'ЗАПИСЬ' if APPLY else 'сухой прогон'}")
if APPLY and changed:
    P.write_bytes(nl.join(res).encode("utf-8"))
