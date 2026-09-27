"""Переименование каталогов переписки с IMMA: inbox/received → from_imma, inbox/<наши тексты> → to_imma, внутренние → notes.
Шаг 1 (git mv) выполняется отдельно в контейнере; этот скрипт правит ссылки в текстах (байтово, без переформатирования)
и README. Запуск: python _rename_inbox.py <workspace> [--apply]."""
import re
import sys
from pathlib import Path

WS = Path(sys.argv[1]); APPLY = "--apply" in sys.argv
NOTES = {"ai-infra-chatgpt.coverage.md", "ai-infra-chatgpt.onboarding.md", "war-economy-2026-01-05.coverage.md",
         "portfolio-approach.assessment.md", "portfolio-approach.summary.md", "positions-input.template.yaml"}
SCAN = ["portfolio", "methodology", "templates", "to_imma", "notes", "STATUS.md", "README.md", "AGENTS.md"]
name_re = re.compile(rb"inbox/([A-Za-z0-9_.\-]+\.(?:md|yaml|json|txt))")


def fix(b: bytes) -> bytes:
    b = b.replace(b"inbox/received/", b"from_imma/")
    b = b.replace(b"inbox/received", b"from_imma")
    b = name_re.sub(lambda m: (b"notes/" if m.group(1).decode() in NOTES else b"to_imma/") + m.group(1), b)
    b = b.replace(b"inbox/*.request.md", b"to_imma/*.request.md").replace(b"inbox/*", b"to_imma/*")
    b = re.sub(rb"inbox/(?=[\s`'\")\]:,.;])", b"to_imma/", b)
    return b


changed = []
for root in SCAN:
    p = WS / root
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and f.suffix in (".md", ".yaml", ".yml", ".json", ".js", ".txt")]
    for f in files:
        if "_runs" in f.parts:
            continue
        raw = f.read_bytes()
        if b"inbox" not in raw:
            continue
        new = fix(raw)
        if new != raw:
            changed.append((str(f.relative_to(WS)), raw.count(b"inbox"), new.count(b"inbox")))
            if APPLY:
                f.write_bytes(new)

# README: блок каталога переписки и оговорка IMMA/IMA
readme = WS / "README.md"; s = readme.read_bytes().decode("utf-8")
old_block_start = s.index("to_imma/                переписка") if "to_imma/                переписка" in s else s.index("to_imma/") if "to_imma/                " in s else -1
block_old_re = re.compile(r"(?:inbox|to_imma)/\s+переписка с LLM-методологом и владельцем\n(?:  .*\n)+")
new_block = """to_imma/                наши тексты для IMMA (Investment Modeling & Methodology Agent — роль внешней LLM):
  *.request.md          заказы (текст между «=== НАЧАЛО ===» и «=== КОНЕЦ ===» отправляется как есть; вложения перечислены в конце)
  *.feedback.md         приёмка полученных артефактов; обратная связь агента-дозора по прогонам (тоже адресована IMMA)
  *.review.md, *.validation-report.md, *.sync.md  разборы и отчёты проверок, переданные IMMA как вложения
from_imma/              ВСЁ полученное от IMMA как получено: модели компаний партий 1–5, пакеты методологии, схемы всех версий,
                        IMA_Foundation_v1.0/ (манифест роли, реестр скиллов IMA-01…08, контракты, golden cases — ещё не принят),
                        MC_v1.1_partA/, примеры отчётов; принятое копируется в methodology/, здесь остаётся архив
notes/                  внутренние документы, никому не адресованные: сводки и разборы переписок, отчёты покрытия, шаблон ввода позиций
"""
m = block_old_re.search(s)
if m:
    s2 = s[:m.start()] + new_block + s[m.end():]
else:
    s2 = s
role_old = "| Investment Modeling Agent (IMA) | внешняя LLM | модели компаний, методология, калибровки — кандидаты | не присваивает канонические ID, не принимает решений |"
role_new = "| IMMA — Investment Modeling & Methodology Agent (в пакете Foundation роль названа IMA, Investment Modeling Agent; проектирование методологии там — зарезервированный скилл IMA-12) | внешняя LLM (сейчас ChatGPT-проект) | модели компаний, методология, калибровки — кандидаты | не присваивает канонические ID, не принимает решений |"
if role_old in s2:
    s2 = s2.replace(role_old, role_new)
s2 = s2.replace("переписка с LLM-методологом. Всё", "переписка с IMMA (ролью внешней LLM-методолога). Всё")
if s2 != s:
    changed.append(("README.md (блок каталогов + роль IMMA)", 0, 0))
    if APPLY:
        readme.write_bytes(s2.encode("utf-8"))
for c in changed:
    print(f"{c[0]}: inbox-упоминаний {c[1]} → {c[2]}")
print("файлов изменено:", len(changed), "| режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
