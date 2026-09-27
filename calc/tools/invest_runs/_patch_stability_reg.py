"""Патч: чистка _iman_conover, регистрация portfolio_stability в реестре сайдкара."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")
p = ROOT / "engine/portfolio_stability.py"; s = p.read_text(encoding="utf-8")
old = '''    n = len(data[tick[0]]["r5"]); k = len(tick)
    rng = np.random.default_rng(seed)
    scores = np.array([(i + 0.5) / n for i in range(n)])
    from math import sqrt
    # van der Waerden-подобные баллы: обратная нормаль через приближение по erfinv-свободной формуле (Acklam) не нужна — берём
    # нормальные квантили через np.sort стандартных нормальных розыгрышей (детерминировано по seed)
    z = np.sort(rng.standard_normal(n))'''
new = '''    n = len(data[tick[0]]["r5"]); k = len(tick)
    rng = np.random.default_rng(seed)
    # баллы — отсортированные стандартные нормальные розыгрыши (аналог van der Waerden), по столбцу — своя перестановка (seed фиксирован)
    z = np.sort(rng.standard_normal(n))'''
assert old in s; s = s.replace(old, new)
old2 = '''        for key in ("r3", "r5", "r8", "maxdd5"):
            data[t][key] = data[t][key][perm]
    _ = sqrt  # noqa
'''
new2 = '''        for key in ("r3", "r5", "r8", "maxdd5"):
            data[t][key] = data[t][key][perm]
'''
assert old2 in s; s = s.replace(old2, new2)
p.write_text(s, encoding="utf-8", newline="\n")
r = ROOT / "engine/registry.py"; t = r.read_text(encoding="utf-8")
assert "portfolio_stability" not in t
t = t.replace("portfolio_optimizer, portfolio_paths, portfolio_regime,", "portfolio_optimizer, portfolio_paths, portfolio_regime, portfolio_stability,")
t = t.replace("importlib.reload(portfolio_optimizer)\n", "importlib.reload(portfolio_optimizer)\nimportlib.reload(portfolio_stability)\n")
t = t.replace('''MODELS = {
    "portfolio_optimizer": {''', '''MODELS = {
    "portfolio_stability": {
        "version": portfolio_stability.VERSION,
        "fn": portfolio_stability.run,
        "doc": portfolio_stability.__doc__.strip().splitlines()[0],
    },
    "portfolio_optimizer": {''')
assert t.count("portfolio_stability") == 6, t.count("portfolio_stability")
r.write_text(t, encoding="utf-8", newline="\n")
print("ok")
