"""22.09: средние цены P2 (счёт Казахстана) → cost_basis; полный расчёт вложенного капитала и превью invested-capital лимитов."""
import json, re
from pathlib import Path
import yaml

Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
AVG = {"RKLB": (24, 104.56), "UFO": (7, 55.13), "ASTS": (32, 77.36), "GLD": (6, 438.93), "CRWV": (11, 152.93), "PLTR": (18, 130.2), "HOOD": (112, 55.53)}
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
tail = "      target: {weight: null, target_version: null, effective_from: null}\n"
rows = []
for tk, (q, avg) in AVG.items():
    mm = list(re.finditer(r"    - ticker: %s\n      account: P2[^\n]*\n" % re.escape(tk), s)); assert len(mm) == 1, tk
    i = mm[0].start(); blk_end = s.index(tail, i) + len(tail); blk = s[i:blk_end]
    assert ("quantity: %s" % q) in blk, (tk, q)
    basis = q * avg
    cb = ('      cost_basis: {total_usd: %.2f, avg_price: %s, source: "owner (средняя цена брокера, сообщение 22.09.2026)", legacy_at_system_start: true, note: "лоты не переданы; средняя цена брокера, вероятно с комиссиями"}\n' % (basis, avg))
    if "      cost_basis:" not in blk:
        s = s[:blk_end] + cb + s[blk_end:]
    rows.append((tk, q, avg, Q[tk]["price"], q * Q[tk]["price"], basis))
p.write_text(s, encoding="utf-8"); d = yaml.safe_load(s)

print("P2 (счёт Казахстана), закрытие 18.09:")
tot_mv = tot_b = 0
for tk, q, avg, px, mv, b in sorted(rows, key=lambda r: -r[4]):
    tot_mv += mv; tot_b += b
    print("  %-5s %6s x $%-8s = $%9.0f -> $%9.0f  %+7.1f%%" % (tk, q, avg, b, mv, (mv / b - 1) * 100))
nbis2 = 15091.51; nbis_mv2 = 190 * Q["NBIS"]["price"]
tot_b += nbis2; tot_mv += nbis_mv2
print("  NBIS  (лоты)              = $%9.0f -> $%9.0f  %+7.1f%%" % (nbis2, nbis_mv2, (nbis_mv2 / nbis2 - 1) * 100))
print("  ИТОГО P2: вложено $%.0f -> $%.0f  %+.1f%%" % (tot_b, tot_mv, (tot_mv / tot_b - 1) * 100))

# --- полный вложенный капитал и превью invested-capital лимитов (Conviction Overlay §1.1) ---
pos = d["portfolio"]["positions"]
missing = [x["ticker"] + "/" + str(x["account"]) for x in pos if "cost_basis" not in x]
assert not missing, missing
cash = sum(float(c["amount"] or 0) for c in d["portfolio"]["cash"]["accounts"])
basis_by = {}
for x in pos:
    basis_by[x["ticker"]] = basis_by.get(x["ticker"], 0.0) + float(x["cost_basis"]["total_usd"])
risk_capital = sum(basis_by.values()) + cash
mv_by = {}
for x in pos:
    mv_by[x["ticker"]] = mv_by.get(x["ticker"], 0.0) + float(x["quantity"]) * float(x["market"]["price"])
nav = sum(mv_by.values()) + cash
print("\nВЛОЖЕННЫЙ КАПИТАЛ (risk capital basis) = $%.0f (позиции $%.0f + кэш $%.0f); NAV $%.0f; общий прирост %+.1f%%" % (risk_capital, risk_capital - cash, cash, nav, (nav / risk_capital - 1) * 100))
ov = yaml.safe_load(Path("methodology/Conviction_Overlay_Schema_v1.0.yaml").read_text(encoding="utf-8"))["proposed_parameters"]["invested_capital"]
prev = []
print("доля вложенного капитала по бумагам (лимиты 12%% обычно / 20%% доверие; предложение LLM, pending):")
for tk in sorted(basis_by, key=lambda k: -basis_by[k]):
    sh = basis_by[tk] / risk_capital
    st = "выше 20%" if sh > ov["conviction_name_limit"] else ("выше 12%" if sh > ov["standard_name_limit"] else "ok")
    prev.append({"ticker": tk, "invested_share": round(sh, 4), "basis_usd": round(basis_by[tk], 2), "market_share": round(mv_by[tk] / nav, 4), "gain": round(mv_by[tk] / basis_by[tk] - 1, 4), "status_vs_proposed": st})
    print("  %-5s basis $%8.0f = %5.1f%%  (рыночная доля %5.1f%%, прирост %+6.1f%%)  %s" % (tk, basis_by[tk], sh * 100, mv_by[tk] / nav * 100, (mv_by[tk] / basis_by[tk] - 1) * 100, st))
# сектор по вложенному капиталу
sec_b = {}
for x in pos:
    sec_b[x["sector_id"]] = sec_b.get(x["sector_id"], 0.0) + float(x["cost_basis"]["total_usd"])
print("сектора по вложенному капиталу (лимит 30%%): " + ", ".join("%s %.1f%%" % (k, v / risk_capital * 100) for k, v in sorted(sec_b.items(), key=lambda kv: -kv[1])))

# запись превью в _portfolio.yaml → conviction_overlay_v1_0
s = p.read_text(encoding="utf-8")
old = '    cost_basis_status: "не ведётся — история покупок владельцем не передана (кроме SPCX); при утверждении слоя legacy-позиции получают legacy_at_system_start и invested-capital лимит применяется к приросту вложений"\n'
assert s.count(old) == 1
new = ('    cost_basis_status: "22.09.2026: cost basis известен по ВСЕМ позициям (NBIS P2 — лоты; остальное — средние цены брокера); все legacy_at_system_start"\n'
       '    risk_capital_basis_usd: %.2f     # Σ cost basis + кэш, на 22.09.2026\n' % risk_capital +
       '    invested_capital_preview_2026_09_22:   # доля вложенного капитала по бумагам vs предложенные лимиты 12/20%%; не решение\n' +
       "".join("      - %s\n" % json.dumps(r, ensure_ascii=False) for r in prev) +
       '    invested_capital_by_sector: %s\n' % json.dumps({k: round(v / risk_capital, 4) for k, v in sec_b.items()}))
s = s.replace(old, new, 1); p.write_text(s, encoding="utf-8"); yaml.safe_load(s)
print("yaml ok")
