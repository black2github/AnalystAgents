"""Проверка текстов перед передачей (владельцу, IMMA, в decisions/notes): запрещённые термины из GLOSSARY.md.
Правило владельца 25.09.2026: слово «провенанс» в текстах не используем — «происхождение» (имя поля provenance
остаётся). Список расширяется здесь; проверка — grep по словоформам без учёта регистра.
Использование:  python calc/tools/check_terms.py <файл> [<файл> ...]   → код возврата 1, если найдено."""
from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED: dict[str, str] = {
    r"провенанс\w*": "происхождение (поле provenance не переименовывать)",
    r"летопис\w*": "хронология",
}


def main(paths: list[str]) -> int:
    bad = 0
    for p in paths:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for pat, repl in BANNED.items():
                for m in re.finditer(pat, line, flags=re.IGNORECASE):
                    bad += 1
                    print(f"{p}:{n}: «{m.group(0)}» → {repl}")
    print("OK — запрещённых терминов нет" if not bad else f"найдено: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else 2)
