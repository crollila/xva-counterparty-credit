"""Model-level checks: curves, Hull-White, simulation, instruments, credit."""
import numpy as np
import pytest

from xva.credit import HazardCurve
from xva.curves import FlatCurve, NelsonSiegelCurve
from xva.hull_white import HullWhite1F
from xva.instruments import FXForward, InterestRateSwap
from xva.simulation import FXModel, TimeGrid, simulate
from xva.stats import mean_estimate

CURVE = NelsonSiegelCurve()


@pytest.fixture(scope="module")
def scen():
    model = HullWhite1F(0.03, 0.01, CURVE)
    return simulate(model, TimeGrid(5.0, 24), 8000, seed=11, fx_model=FXModel(1.1, 0.12, 0.02, -0.3), antithetic=True)


def test_nelson_siegel_forward_is_derivative_of_log_discount():
    t = np.linspace(0.1, 20, 50)
    h = 1e-5
    num = -(np.log(CURVE.discount(t + h)) - np.log(CURVE.discount(t - h))) / (2 * h)
    assert np.allclose(num, CURVE.inst_forward(t), atol=1e-7)


def test_hw_bond_at_time_zero_reproduces_curve():
    m = HullWhite1F(0.05, 0.012, CURVE)
    T = np.array([0.5, 1, 5, 10])
    assert np.allclose(m.bond(0.0, T, np.array([0.0]))[0], CURVE.discount(T), rtol=1e-12)


def test_hw_zero_vol_bond_is_forward_discount():
    m = HullWhite1F(0.05, 0.0, CURVE)
    assert np.allclose(m.bond(2.0, np.array([3.0, 7.0]), np.zeros(3)), CURVE.discount(np.array([3.0, 7.0])) / CURVE.discount(2.0))


def test_discount_factor_is_martingale(scen):
    """E[D(0,t)] = P(0,t) within Monte Carlo error at every date."""
    P0 = CURVE.discount(scen.times)
    for k in range(1, len(scen.times), 6):
        e = mean_estimate(scen.D[k] - P0[k], True)
        assert abs(e.value) < 4 * e.se + 1e-12


def test_deflated_bond_is_martingale(scen):
    """E[D(0,t) P(t,T)] = P(0,T)."""
    k, T = 48, 4.0  # t = 2y
    pt = scen.model.bond(scen.times[k], T, scen.x[k])
    e = mean_estimate(scen.D[k] * pt - CURVE.discount(T), True)
    assert abs(e.value) < 4 * e.se


def test_fx_forward_deflated_value_is_martingale(scen):
    fwd = FXForward("f", 1e6, 1.12, 3.0, True)
    V = fwd.mtm(scen)
    for k in (12, 24, 48):
        e = mean_estimate(scen.D[k] * V[k] - V[0, 0], True)
        assert abs(e.value) < 4 * e.se


def test_par_swap_has_zero_value_today(scen):
    proto = InterestRateSwap("s", 1e8, 0.0, 5.0, True)
    sw = InterestRateSwap("s", 1e8, proto.par_rate(CURVE), 5.0, True)
    assert abs(sw.mtm(scen)[0, 0]) < 1e-4


def test_payer_and_receiver_swaps_are_negatives(scen):
    p = InterestRateSwap("p", 1e7, 0.035, 4.0, True).mtm(scen)
    r = InterestRateSwap("r", 1e7, 0.035, 4.0, False).mtm(scen)
    assert np.allclose(p, -r)


def test_swap_value_is_zero_at_and_after_maturity(scen):
    V = InterestRateSwap("s", 1e7, 0.035, 3.0, True).mtm(scen)
    assert np.all(V[scen.grid.index(3.0):] == 0)


def test_off_grid_schedule_rejected():
    with pytest.raises(ValueError):
        InterestRateSwap("s", 1.0, 0.03, 2.3, True).fixed_dates


def test_hazard_survival_and_pd_consistency():
    hz = HazardCurve((1.0, 3.0, 5.0), (0.01, 0.02, 0.03))
    t = np.linspace(0, 8, 97)
    S = hz.survival(t)
    assert S[0] == 1.0 and np.all(np.diff(S) < 0)
    assert np.isclose(hz.marginal_pd(t).sum(), 1 - S[-1])
    # integrated hazard at 4y: 0.01*1 + 0.02*2 + 0.03*1
    assert np.isclose(hz.integrated(np.array(4.0)), 0.08)
    # flat extrapolation beyond the last knot
    assert np.isclose(hz.integrated(np.array(7.0)), 0.01 + 0.04 + 0.06 + 0.06)


def test_credit_triangle_bootstrap():
    hz = HazardCurve.from_cds_spreads([1, 5], [0.006, 0.012], 0.4)
    assert np.isclose(hz.integrated(np.array(1.0)), 0.01)
    assert np.isclose(hz.integrated(np.array(5.0)), 0.02 * 5)


def test_flat_curve_basics():
    c = FlatCurve(0.03)
    assert np.isclose(c.discount(2.0), np.exp(-0.06))
