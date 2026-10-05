"""The validation checklist: limiting cases, identities, fixtures, convergence."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.stats import norm

from xva.collateral import CSA, collateral_balance, collateralised_mtm
from xva.config import MM, ExperimentConfig
from xva.credit import CreditParty, HazardCurve
from xva.curves import NelsonSiegelCurve
from xva.exposure import ExposureProfile, gross_parts, net_parts
from xva.hull_white import HullWhite1F
from xva.instruments import FXForward, InterestRateSwap
from xva.simulation import FXModel, TimeGrid, simulate
from xva.stats import mean_estimate, pair_reduce
from xva.wwr import wwr_default_probs
from xva.xva import cva, dva, fva

CURVE = NelsonSiegelCurve()
CPTY = CreditParty("c", HazardCurve.flat(0.02), 0.4)
OWN = CreditParty("b", HazardCurve.flat(0.01), 0.4)


@pytest.fixture(scope="module")
def book():
    cfg = ExperimentConfig(n_paths=4000, horizon=10.0)
    scen = simulate(cfg.model, cfg.grid, cfg.n_paths, 3, cfg.fx_model, True)
    Vs = [tr.mtm(scen) for tr in cfg.portfolio()]
    return cfg, scen, Vs, sum(Vs)


# ---------------------------------------------------------------- limiting cases
def test_zero_hazard_gives_zero_cva(book):
    _, s, _, V = book
    c0 = CPTY.with_(hazard=HazardCurve.flat(0.0))
    assert cva(s.times, np.maximum(V, 0), s.D, c0, True).value == 0.0


def test_zero_exposure_gives_zero_cva():
    m = HullWhite1F(0.03, 0.01, CURVE)
    s = simulate(m, TimeGrid(5.0, 12), 200, 1)
    V = InterestRateSwap("z", 0.0, 0.03, 5.0, True).mtm(s)
    assert cva(s.times, np.maximum(V, 0), s.D, CPTY, True).value == 0.0


def test_zero_lgd_gives_zero_cva(book):
    _, s, _, V = book
    assert cva(s.times, np.maximum(V, 0), s.D, CPTY.with_(recovery=1.0), True).value == 0.0


def test_zero_own_hazard_gives_zero_dva_and_zero_spread_gives_zero_fva(book):
    _, s, _, V = book
    own0 = OWN.with_(hazard=HazardCurve.flat(0.0))
    assert dva(s.times, np.minimum(V, 0), s.D, own0, True).value == 0.0
    fca, fba, f = fva(s.times, np.maximum(V, 0), np.minimum(V, 0), s.D, CPTY, OWN, 0.0, 0.0, True)
    assert fca.value == fba.value == f.value == 0.0


def test_cva_monotone_in_hazard_and_lgd(book):
    _, s, _, V = book
    PE = np.maximum(V, 0)
    by_h = [cva(s.times, PE, s.D, CPTY.with_(hazard=HazardCurve.flat(h)), True).value for h in (0.0, 0.005, 0.01, 0.03, 0.1)]
    by_l = [cva(s.times, PE, s.D, CPTY.with_(recovery=1 - l), True).value for l in (0.0, 0.2, 0.5, 0.8, 1.0)]
    assert np.all(np.diff(by_h) > 0) and np.all(np.diff(by_l) > 0)
    # CVA is exactly linear in LGD
    assert np.isclose(by_l[2], 0.5 * by_l[4])


def test_bilateral_cva_below_unilateral(book):
    _, s, _, V = book
    PE = np.maximum(V, 0)
    assert cva(s.times, PE, s.D, CPTY, True, own=OWN).value < cva(s.times, PE, s.D, CPTY, True).value


# ---------------------------------------------------------------- deterministic fixture
def _deterministic_scen(horizon=5.0, spy=12, fx_vol=0.0):
    m = HullWhite1F(0.03, 0.0, CURVE)
    return simulate(m, TimeGrid(horizon, spy), 2, 0, FXModel(1.1, fx_vol, 0.02, 0.0), True)


def test_deterministic_fx_forward_exposure_and_closed_form_cva():
    """Zero vol: V(t) = V0 / P(0,t) so D(t)V(t) = V0 and CVA = LGD V0 (1 - S(t_last))."""
    s = _deterministic_scen()
    f = FXForward("f", 1e7, 1.0, 3.0, True)  # deep ITM: forward ~1.12 > 1.0
    V = f.mtm(s)
    V0 = 1e7 * (1.1 * np.exp(-0.02 * 3.0) - 1.0 * CURVE.discount(3.0))
    t = s.times
    live = t < 3.0
    assert np.allclose(V[live, 0], V0 / CURVE.discount(t[live]), rtol=1e-10)
    lam, lgd = 0.025, 0.6
    c = CreditParty("c", HazardCurve.flat(lam), 1 - lgd)
    t_last = t[live][-1]
    expected = lgd * V0 * (1 - np.exp(-lam * t_last))
    got = cva(t, np.maximum(V, 0), s.D, c, True).value
    assert np.isclose(got, expected, rtol=1e-10)


def test_deterministic_swap_matches_independent_curve_pricing():
    """Zero rate vol: swap MtM must equal an independent forward-curve valuation."""
    s = _deterministic_scen(5.0, 12)
    K, N = 0.037, 5e7
    sw = InterestRateSwap("s", N, K, 5.0, True)
    V = sw.mtm(s)[:, 0]
    P = CURVE.discount
    fixed, flt = np.arange(1, 11) * 0.5, np.arange(1, 21) * 0.25
    for t in (0.0, 0.25, 1.0, 1.0 + 1 / 12, 2.5, 4.75):
        k = int(round(t * 12))
        rem = fixed[fixed > t + 1e-12]
        fixed_pv = K * 0.5 * P(rem).sum() / P(t)
        i = np.searchsorted(flt, t + 1e-12)
        reset = 0.0 if i == 0 else flt[i - 1]
        float_pv = (P(reset) - P(5.0)) / P(t)
        assert np.isclose(V[k], N * (float_pv - fixed_pv), rtol=1e-9, atol=1e-6), t


# ---------------------------------------------------------------- PFE
def test_pfe_quantile_matches_lognormal_closed_form():
    m = HullWhite1F(0.03, 0.0, CURVE)
    rf, sig, S0, K, N, T = 0.02, 0.15, 1.1, 1.1, 1e7, 2.0
    s = simulate(m, TimeGrid(T, 12), 40000, 5, FXModel(S0, sig, rf, 0.0), True)
    V = FXForward("f", N, K, T, True).mtm(s)
    prof = ExposureProfile.from_mtm(s.times, V, s.D, True)
    t = 1.0
    k = 12
    mu = np.log(S0) - np.log(CURVE.discount(t)) - rf * t - 0.5 * sig**2 * t
    for q in (0.95, 0.99):
        Sq = np.exp(mu + sig * np.sqrt(t) * norm.ppf(q))
        pfe = N * (Sq * np.exp(-rf * (T - t)) - K * CURVE.discount(T) / CURVE.discount(t))
        assert np.isclose(prof.pfe[q][k], pfe, rtol=0.03), q


def test_pfe_quantiles_ordered_and_consistent(book):
    _, s, _, V = book
    prof = ExposureProfile.from_mtm(s.times, V, s.D, True)
    qs = sorted(prof.pfe)
    for a, b in zip(qs, qs[1:]):
        assert np.all(prof.pfe[a] <= prof.pfe[b] + 1e-9)
    PE = np.maximum(V, 0)
    k = 120
    assert np.isclose(prof.pfe[0.99][k], np.quantile(PE[k], 0.99))
    # empirical exceedance frequency of PFE_q is ~1-q
    assert abs(np.mean(PE[k] > prof.pfe[0.95][k]) - 0.05) < 0.005


# ---------------------------------------------------------------- netting
def test_netting_identities(book):
    _, s, Vs, V = book
    gPE, gNE = gross_parts(Vs)
    nPE, nNE = net_parts(V)
    assert np.all(gPE >= nPE - 1e-6)  # netting never increases positive exposure
    assert np.all(gNE <= nNE + 1e-6)
    assert np.allclose(gPE + gNE, V) and np.allclose(nPE + nNE, V)  # both decompose the same MtM
    # single trade: netting changes nothing
    p1, n1 = gross_parts([Vs[0]])
    assert np.array_equal(p1, np.maximum(Vs[0], 0))


def test_netting_same_sign_trades_equals_gross():
    s = _deterministic_scen()
    a = FXForward("a", 1e7, 1.0, 3.0, True).mtm(s)
    b = FXForward("b", 5e6, 0.9, 2.0, True).mtm(s)  # both deep ITM -> both >= 0
    gPE, _ = gross_parts([a, b])
    nPE, _ = net_parts(a + b)
    assert np.allclose(gPE, nPE)


# ---------------------------------------------------------------- collateral
def test_one_way_collateral_never_increases_exposure_pathwise(book):
    _, s, _, V = book
    for csa in (CSA(0, np.inf, 0, 0, 1, 2, 0), CSA(2 * MM, np.inf, 0.5 * MM, 0, 4, 2, 1), CSA(5 * MM, np.inf, 1 * MM, 1 * MM, 12, 8, 2)):
        Vc = collateralised_mtm(V, csa)
        assert np.all(np.maximum(Vc, 0) <= np.maximum(V, 0) + 1e-6)


def test_two_way_collateral_reduces_epe_but_posted_collateral_can_add_exposure(book):
    """Two-way CSA: overall EPE falls, but NOT pathwise. Collateral WE posted is
    itself at risk during the MPoR, e.g. when a trade cashflow settles and the
    MtM drops to zero while our posted collateral is not yet returned."""
    _, s, _, V = book
    Vc = collateralised_mtm(V, CSA(1 * MM, 1 * MM, 0.1 * MM, 0, 1, 2, 0))
    ee_c, ee_u = np.maximum(Vc, 0).mean(axis=1), np.maximum(V, 0).mean(axis=1)
    assert np.trapezoid(ee_c, s.times) < 0.5 * np.trapezoid(ee_u, s.times)
    assert ee_c[-1] > ee_u[-1] == 0.0  # final maturity: V = 0 but posted collateral is still out


def test_perfect_csa_removes_exposure_and_infinite_threshold_is_uncollateralised(book):
    _, s, _, V = book
    Vc = collateralised_mtm(V, CSA(0, 0, 0, 0, 1, 0, 0))
    assert np.allclose(Vc, 0, atol=1e-6)
    Vinf = collateralised_mtm(V, CSA(np.inf, np.inf, 0, 0, 1, 2, 0))
    assert np.allclose(Vinf, V)


def test_mta_blocks_small_transfers_and_settlement_lag_shifts_balance(book):
    _, s, _, V = book
    mta = 1 * MM
    bal = collateral_balance(V, CSA(0, 0, mta, 0, 1, 0, 0))
    moves = np.diff(bal, axis=0)
    assert np.all((moves == 0) | (np.abs(moves) >= mta - 1e-6))
    b0 = collateral_balance(V, CSA(0, 0, 0, 0, 1, 0, 0))
    b2 = collateral_balance(V, CSA(0, 0, 0, 0, 1, 0, 2))
    assert np.allclose(b2[3:], b0[1:-2])


def test_independent_amount_reduces_exposure(book):
    _, s, _, V = book
    base = CSA(2 * MM, 2 * MM, 0.25 * MM, 0, 1, 2, 0)
    e0 = np.maximum(collateralised_mtm(V, base), 0).mean()
    e1 = np.maximum(collateralised_mtm(V, replace(base, independent_amount=5 * MM)), 0).mean()
    assert e1 < e0


def test_longer_mpor_increases_exposure(book):
    _, s, _, V = book
    e = [np.maximum(collateralised_mtm(V, CSA(0, 0, 0, 0, 1, m, 0)), 0).mean() for m in (0, 1, 2, 4, 8)]
    assert np.all(np.diff(e) > 0)


# ---------------------------------------------------------------- Monte Carlo
def test_seed_determinism():
    m = HullWhite1F(0.03, 0.01, CURVE)
    a = simulate(m, TimeGrid(2.0, 12), 100, 42)
    b = simulate(m, TimeGrid(2.0, 12), 100, 42)
    c = simulate(m, TimeGrid(2.0, 12), 100, 43)
    assert np.array_equal(a.x, b.x) and not np.array_equal(a.x, c.x)


def test_antithetic_pairs_are_mirrored():
    m = HullWhite1F(0.03, 0.01, CURVE)
    s = simulate(m, TimeGrid(2.0, 12), 100, 42, antithetic=True)
    assert np.allclose(s.x[:, :50], -s.x[:, 50:])
    assert pair_reduce(np.arange(4.0), True).tolist() == [1.0, 2.0]


def _cva_estimate(n, seed, anti):
    cfg = ExperimentConfig()
    s = simulate(cfg.model, TimeGrid(5.0, 12), n, seed, None, anti)
    V = InterestRateSwap("s", 1e8, 0.035, 5.0, True).mtm(s)
    return cva(s.times, np.maximum(V, 0), s.D, CPTY, anti).estimate


def test_monte_carlo_convergence_rate_and_consistency():
    e1 = _cva_estimate(2000, 1, False)
    e4 = _cva_estimate(8000, 2, False)
    ref = _cva_estimate(40000, 3, True)
    assert 0.35 < e4.se / e1.se < 0.65  # ~ 1/sqrt(4) = 0.5
    for e in (e1, e4):
        assert abs(e.value - ref.value) < 4 * np.hypot(e.se, ref.se)


def test_antithetic_reduces_variance():
    a = _cva_estimate(8000, 9, True)
    p = _cva_estimate(8000, 9, False)
    assert a.se < p.se


# ---------------------------------------------------------------- wrong-way risk
def test_wwr_calibration_preserves_marginal_pd_and_beta_zero_is_independent(book):
    _, s, _, V = book
    hz = CPTY.hazard
    PE = np.maximum(V, 0)
    base = cva(s.times, PE, s.D, CPTY, True).value
    for beta in (-0.5, 0.0, 0.7):
        pdp = wwr_default_probs(s.times, V, hz, beta)
        assert np.allclose(pdp.mean(axis=1), hz.marginal_pd(s.times), atol=1e-14)
        c = cva(s.times, PE, s.D, CPTY, True, pd_paths=pdp).value
        if beta == 0.0:
            assert np.isclose(c, base, rtol=1e-10)
        elif beta > 0:
            assert c > base
        else:
            assert c < base
