

# ------------------------------------------------------------------ company_mc 2.3.1: непрерывная смена базы оценки (Conditional MC v1.1.3 §9/§16.6/§20)
P0 = {"growth_shift": 0.0, "margin_shift": 0.0, "mult_factor": 1.0, "rho_shift": 0.0}


def test_crossover_function_continuous_and_monotone():
    R, MR, MF, elig = 1.0e9, 7.0, 24.0, 0.08                                   # центральный случай RKLB из контракта
    m = np.linspace(-0.2, 0.6, 8001)
    v, code, pm = cm.crossover_value(m, np.full_like(m, R * MR), R * m * MF, np.full_like(m, MR), np.full_like(m, MF), elig, 1)
    assert abs(float(pm[0]) - 7 / 24) < 1e-12
    m_start = max(elig, 7 / 24)
    assert np.all(np.diff(v) >= -1e-6)                                          # не убывает по марже
    for pt in (elig, m_start, m_start + cm.BLEND_WIDTH):                        # непрерывность в трёх точках контракта
        i = int(np.searchsorted(m, pt)); assert abs(v[i] - v[i - 1]) < R * 1e-3
    assert code[m < elig].min() == 1 and code[m < elig].max() == 1
    assert set(code[(m >= elig) & (m < m_start)]) == {5} and set(code[(m >= m_start) & (m < m_start + cm.BLEND_WIDTH)]) == {6} and set(code[m >= m_start + cm.BLEND_WIDTH]) == {0}
    assert abs(v[int(np.searchsorted(m, m_start)) - 1] - R * MR) < R * 1e-3      # в начале смеси стоимость = bridge, дальше ≥ bridge
    assert v[-1] > R * MR


def test_crossover_mode_by_schema_version_and_old_mode_unchanged():
    assert cm.crossover_mode({}) == cm.CROSSOVER_HARD and cm.crossover_mode({"schema_version": "1.0.1"}) == cm.CROSSOVER_HARD
    assert cm.crossover_mode({"schema_version": "1.0.2"}) == cm.CROSSOVER_PARITY and cm.crossover_mode({"schema_version": "1.1.0"}) == cm.CROSSOVER_PARITY
    old = cm.run({"calibration": cal_mature(), "equity_value_0": 30e9, "convergence_check": False, "robustness": False}, 0)["base"]
    assert old["valuation_crossover"]["mode"] == cm.CROSSOVER_HARD and old["basis_parity_margin"]["Y5"] is None
    assert old["valuation_basis_share"]["Y5"]["crossover_bridge"] == 0.0 and old["valuation_basis_share"]["Y5"]["basis_blend"] == 0.0


def test_parity_mode_value_never_falls_when_margin_rises_A():
    cal = cal_mature(schema_version="1.0.2")
    cal["margin_model"]["current_margin"] = 0.02; cal["margin_model"]["terminal_margin_Y5"] = TRI(0.05, 0.15, 0.30)   # маржа в зоне паритета 5/24≈0.21
    base = cm._run_once(cal, 30e9, 4000, 5, 4000, P0, [0.5], None, keep_paths=True)
    up = cm._run_once(cal, 30e9, 4000, 5, 4000, dict(P0, margin_shift=0.03), [0.5], None, keep_paths=True)
    assert base["valuation_crossover"]["mode"] == cm.CROSSOVER_PARITY
    sh = base["valuation_basis_share"]["Y5"]; assert sh["crossover_bridge"] + sh["basis_blend"] > 0.05      # переходная зона реально задействована
    assert base["basis_parity_margin"]["Y5"]["median"] > 0.1
    assert np.all(up["_paths"]["r5"] >= base["_paths"]["r5"] * (1 - 1e-5))                                 # тот же seed: путь за путём не хуже


def test_parity_mode_value_never_falls_when_margin_rises_C():
    from tests.test_milestone_mc import cal_c
    cal = cal_c(); cal["schema_version"] = "1.0.2"
    cal["valuation"] = {"fcf_maturity_margin": 0.08, "multiple_fcf": TRI(18, 24, 30), "multiple_revenue_bridge": TRI(4, 7, 11)}   # RKLB-подобный случай
    base = cm._run_once(cal, 5e9, 4000, 5, 4000, P0, [0.5], None, keep_paths=True)
    up = cm._run_once(cal, 5e9, 4000, 5, 4000, dict(P0, margin_shift=0.05), [0.5], None, keep_paths=True)
    assert np.all(up["_paths"]["r5"] >= base["_paths"]["r5"] * (1 - 1e-5))
    assert base["basis_parity_margin"]["Y5"]["median"] > 0.2                                               # bridge-зависимость видна явно, а не спрятана
    # прежняя семантика (схема 1.0.1) на том же случае действительно роняла стоимость при росте маржи — дефект, ради которого сделан 2.3.1
    old = dict(cal); old["schema_version"] = "1.0.1"
    b0 = cm._run_once(old, 5e9, 4000, 5, 4000, P0, [0.5], None, keep_paths=True); u0 = cm._run_once(old, 5e9, 4000, 5, 4000, dict(P0, margin_shift=0.05), [0.5], None, keep_paths=True)
    assert (u0["_paths"]["r5"] < b0["_paths"]["r5"] * 0.9).mean() > 0.01
