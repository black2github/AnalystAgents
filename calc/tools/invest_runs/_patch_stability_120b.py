"""Дополнение среза 2: выравнивание чанков (антитетические пары внутри чанка) — тест, сторож и проверка воспроизведения BASE."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")


def patch(path, reps):
    p = ROOT / path; s = p.read_text(encoding="utf-8")
    for a, b in reps:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    p.write_text(s, encoding="utf-8", newline="\n"); print("patched", path)


patch("tests/test_company_mc.py", [
    ('''    stored = cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": "t-AAA-sp"}, 0)
    disk = pp.load_paths(stored["paths_file"])
    mem = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000}, 0)
    assert np.array_equal(mem["paths"]["r5"], disk["r5"]) and np.array_equal(mem["paths"]["path_id"], disk["path_id"])     # память = диск
    sub = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 2000, "chunk": 50000}, 0)
    assert np.array_equal(sub["paths"]["r5"], disk["r5"][:2000])                                                            # усечённый прогон = первые пути''',
     '''    stored = cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "chunk": 2000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": "t-AAA-sp"}, 0)
    disk = pp.load_paths(stored["paths_file"])
    mem = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "chunk": 2000}, 0)
    assert np.array_equal(mem["paths"]["r5"], disk["r5"]) and np.array_equal(mem["paths"]["path_id"], disk["path_id"])     # память = диск
    sub = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 2000, "chunk": 2000}, 0)
    assert np.array_equal(sub["paths"]["r5"], disk["r5"][:2000])                                                            # усечённый прогон = первые пути при том же chunk (антитетические пары внутри чанка)
    other = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 2000, "chunk": 50000}, 0)
    assert not np.array_equal(other["paths"]["r5"], disk["r5"][:2000])                                                      # другой размер чанка — другие пары → НЕ выровнено'''),
    ('''    up = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "perturbation": {"margin_shift": 0.05}}, 0)''',
     '''    up = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "chunk": 2000, "perturbation": {"margin_shift": 0.05}}, 0)'''),
    ('''    ko = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "knockout": ["AI_COMPUTE_DEMAND"]}, 0)''',
     '''    ko = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "chunk": 2000, "knockout": ["AI_COMPUTE_DEMAND"]}, 0)'''),
])

patch("engine/portfolio_stability.py", [
    ('''    rs = _W["resim"]; n = _W["n"]; meta = _W["base"][t]["meta"]
    inp = {"calibration": rs["calibrations"][t], "equity_value_0": float(rs["equity_value_0"][t]), "joint_layer_spec": rs.get("joint_layer_spec"),
           "global_seed": int(rs.get("global_seed", meta.get("global_seed"))), "chunk": int(rs.get("chunk", meta.get("chunk") or 50000)), "paths": n}''',
     '''    rs = _W["resim"]; n = _W["n"]; meta = _W["base"][t]["meta"]
    chunk = int(rs.get("chunk", meta.get("chunk") or 50000))
    _check_chunk_alignment(int(meta.get("paths") or n), n, chunk)
    inp = {"calibration": rs["calibrations"][t], "equity_value_0": float(rs["equity_value_0"][t]), "joint_layer_spec": rs.get("joint_layer_spec"),
           "global_seed": int(rs.get("global_seed", meta.get("global_seed"))), "chunk": chunk, "paths": n}'''),
    ('''def _resimulate(t: str, perturbation: dict | None, knockout: list | None) -> dict:''',
     '''def _check_chunk_alignment(paths_base: int, n: int, chunk: int) -> None:
    """Пути выровнены по path_id только при одинаковых размерах чанков (антитетические пары формируются внутри чанка):
    размеры чанков усечённого прогона (n) должны совпадать с первыми чанками нормативного (paths_base)."""
    def sizes(total):
        out, done = [], 0
        while done < total:
            m = min(chunk, total - done); out.append(m if m % 2 == 0 else m + 1); done += m
        return out
    sb, sn = sizes(paths_base), sizes(n)
    if sn != sb[:len(sn)]:
        raise ValueError(f"resimulate: пути не выровняются — размеры чанков {sn} против нормативных {sb[:len(sn)]} (chunk {chunk}); нужен n, кратный chunk, или chunk нормативного прогона")


def _resimulate(t: str, perturbation: dict | None, knockout: list | None) -> dict:'''),
    ('''    resim = cfg.get("resimulate") or None
    if resim:
        miss = [t for t in tick if t not in (resim.get("calibrations") or {}) or t not in (resim.get("equity_value_0") or {})]
        if miss:
            raise ValueError(f"resimulate: нет калибровки/equity_value_0 для {miss}")''',
     '''    resim = cfg.get("resimulate") or None
    resim_check = None
    if resim:
        miss = [t for t in tick if t not in (resim.get("calibrations") or {}) or t not in (resim.get("equity_value_0") or {})]
        if miss:
            raise ValueError(f"resimulate: нет калибровки/equity_value_0 для {miss}")
        # сторож: пересимуляция BASE первой компании должна побитно совпасть с нормативными путями (общие шоки, chunk, seed)
        _worker_init(inp, n, {}, 0.0)
        chk = _resimulate(tick[0], None, None)
        if not np.array_equal(chk["r5"], base[tick[0]]["r5"]):
            raise ValueError(f"resimulate: пересимуляция BASE {tick[0]} не воспроизводит нормативные пути (проверьте калибровку, equity_value_0, global_seed, chunk)")
        resim_check = {"company": tick[0], "reproduced": True}'''),
    ('''"resimulate": bool(resim), "assumptions_hash": ah,''', '''"resimulate": bool(resim), "resimulate_check": resim_check, "assumptions_hash": ah,'''),
])

patch("tests/test_portfolio_stability.py", [
    ('''    inp["stability"] = {**inp["stability"], "workers": 1, "families": ["terminal", "milestone", "driver_knockout"],
                        "resimulate": {"calibrations": cals, "equity_value_0": {"AAA": 30e9, "BBB": 30e9, "CCC": 30e9}, "joint_layer_spec": SPEC, "global_seed": 101, "chunk": 6000}}''',
     '''    inp["stability"] = {**inp["stability"], "workers": 1, "max_paths": 4000, "search_paths": 4000, "families": ["terminal", "milestone", "driver_knockout"],
                        "resimulate": {"calibrations": cals, "equity_value_0": {"AAA": 30e9, "BBB": 30e9, "CCC": 30e9}, "joint_layer_spec": SPEC, "global_seed": 101, "chunk": 4000}}'''),
    ('''    assert out["resimulate"] is True and out["runs_by_family"]["terminal_margin"] == 6 and "terminal_multiple" in out["runs_by_family"]''',
     '''    assert out["resimulate"] is True and out["resimulate_check"]["reproduced"] and out["runs_by_family"]["terminal_margin"] == 6 and "terminal_multiple" in out["runs_by_family"]
    import pytest
    with pytest.raises(ValueError):                                                                                          # другой chunk → сторож выравнивания
        ps.run({**inp, "stability": {**inp["stability"], "resimulate": {**inp["stability"]["resimulate"], "chunk": 1000}}}, 11)'''),
])
