"""End-to-end experiment on the SIMULATED netting set.

    python -m xva.experiment [--quick] [--out results]

Writes results/summary.json, results/*.csv and results/profiles.npz. All
randomness comes from the seed in ExperimentConfig, so reruns reproduce the
same numbers (timings excepted).
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .collateral import CSA, collateral_balance, collateralised_mtm
from .config import MM, ExperimentConfig
from .hull_white import HullWhite1F
from .exposure import ExposureProfile, gross_parts, net_parts
from .simulation import simulate
from .stats import bootstrap_quantile_ci, mean_estimate
from .wwr import conditional_exposure, wwr_default_probs
from .xva import cva, dva, fva

REGIMES = ("gross", "netted", "collateralised", "netted_collateralised")
REGIME_LABELS = {
    "gross": "1. Gross, uncollateralised",
    "netted": "2. Netted, uncollateralised",
    "collateralised": "3. Collateralised, no netting (per-trade CSA)",
    "netted_collateralised": "4. Netted + collateralised",
}


def value_trades(cfg: ExperimentConfig, n_paths: int, seed: int, antithetic: bool, model=None):
    t0 = time.perf_counter()
    scen = simulate(model or cfg.model, cfg.grid, n_paths, seed, cfg.fx_model, antithetic)
    t1 = time.perf_counter()
    trades = cfg.portfolio()
    Vs = [tr.mtm(scen) for tr in trades]
    t2 = time.perf_counter()
    return scen, trades, Vs, {"simulation_s": t1 - t0, "valuation_s": t2 - t1}


def xva_block(times, PE, NE, D, cfg: ExperimentConfig, anti: bool) -> dict:
    c, o = cfg.counterparty, cfg.own
    out = {
        "CVA": cva(times, PE, D, c, anti).as_dict(),
        "DVA": dva(times, NE, D, o, anti).as_dict(),
        "CVA_bilateral": cva(times, PE, D, c, anti, own=o).as_dict(),
        "DVA_bilateral": dva(times, NE, D, o, anti, cpty=c).as_dict(),
    }
    fca, fba, fv = fva(times, PE, NE, D, c, o, cfg.funding_spread_borrow, cfg.funding_spread_lend, anti)
    out["FCA"], out["FBA"], out["FVA"] = fca.as_dict(), fba.as_dict(), fv.as_dict()
    return out


def value_netted(cfg: ExperimentConfig, n_paths: int, seed: int, antithetic: bool, model=None):
    """Memory-lean: stream trade values into the netting-set sum, keep only (times, D, V)."""
    t0 = time.perf_counter()
    scen = simulate(model or cfg.model, cfg.grid, n_paths, seed, cfg.fx_model, antithetic)
    t1 = time.perf_counter()
    V = np.zeros_like(scen.D)
    for tr in cfg.portfolio():
        V += tr.mtm(scen)
    t2 = time.perf_counter()
    times, D = scen.times, scen.D
    del scen
    return times, D, V, {"simulation_s": t1 - t0, "valuation_s": t2 - t1}


def netted_cva_only(cfg, n_paths, seed, antithetic):
    t0 = time.perf_counter()
    times, D, V, timing = value_netted(cfg, n_paths, seed, antithetic)
    t1 = time.perf_counter()
    np.maximum(V, 0.0, out=V)  # V is now PE
    ch = cva(times, V, D, cfg.counterparty, antithetic)
    epe = ExposureProfile.from_parts(times, V, None, D, antithetic, quantiles=(0.99,))
    t2 = time.perf_counter()
    timing["aggregation_s"] = t2 - t1
    timing["total_s"] = t2 - t0
    return ch.estimate, epe.epe, epe.peak_pfe(0.99)[0], timing


def run(cfg: ExperimentConfig, out_dir: Path, quick: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    T0 = time.perf_counter()
    anti = cfg.antithetic
    res: dict = {
        "label": "SIMULATED PORTFOLIO / SIMPLIFIED XVA METHODOLOGY - educational, not production",
        "currency": "DOM (generic synthetic domestic currency)",
        "config": {
            "seed": cfg.seed,
            "n_paths": cfg.n_paths,
            "antithetic": anti,
            "steps_per_year": cfg.steps_per_year,
            "horizon_years": cfg.horizon,
            "hw_a": cfg.hw_a,
            "hw_sigma": cfg.hw_sigma,
            "fx_spot": cfg.fx_spot,
            "fx_vol": cfg.fx_vol,
            "foreign_rate": cfg.foreign_rate,
            "corr_rates_fx": cfg.corr_rates_fx,
            "cpty_cds_bp": list(cfg.cpty_cds_bp),
            "own_cds_bp": list(cfg.own_cds_bp),
            "cds_tenors": list(cfg.cds_tenors),
            "cpty_recovery": cfg.cpty_recovery,
            "own_recovery": cfg.own_recovery,
            "funding_spread_borrow_bp": cfg.funding_spread_borrow * 1e4,
            "funding_spread_lend_bp": cfg.funding_spread_lend * 1e4,
            "csa": cfg.csa.__dict__,
            "quick": quick,
        },
    }

    # ---------------- 1. base run ----------------
    scen, trades, Vs, timing = value_trades(cfg, cfg.n_paths, cfg.seed, anti)
    times, D = scen.times, scen.D
    del scen  # rates/FX state no longer needed once every trade is valued
    V = sum(Vs)
    res["trades"] = []
    trade_ee = []
    for tr, v in zip(trades, Vs):
        prof_t = ExposureProfile.from_mtm(times, v, D, anti, quantiles=(0.95,))
        trade_ee.append(prof_t.ee)
        res["trades"].append({
            "name": tr.name,
            "type": type(tr).__name__,
            "notional": getattr(tr, "notional", getattr(tr, "notional_foreign", None)),
            "maturity": tr.maturity,
            "rate_or_strike": getattr(tr, "fixed_rate", getattr(tr, "strike", None)),
            "mtm_t0": float(v[0].mean()),
            "standalone_EPE": float(prof_t.epe.value),
        })
    res["portfolio_mtm_t0"] = float(V[0].mean())
    fx_i = next(i for i, tr in enumerate(trades) if tr.name.startswith("FXF1"))
    k1 = int(cfg.steps_per_year * 1.0)
    fx_m = mean_estimate(D[k1] * Vs[fx_i][k1] - Vs[fx_i][0], anti)
    early_diag = {
        "fx_forward_martingale_err_1y_DOM": fx_m.value,
        "fx_forward_martingale_z_1y": fx_m.value / fx_m.se,
        "fx_forward_notional_DOM": float(trades[fx_i].notional_foreign * cfg.fx_spot),
        "irs3_mtm_t0_par_check_DOM": float(Vs[2][0].mean()),
    }

    t_agg = time.perf_counter()
    profiles = {}
    res["regimes"] = {}

    def do_regime(name, PE, NE):
        prof = ExposureProfile.from_parts(times, PE, NE, D, anti)
        profiles[name] = prof
        block = {"label": REGIME_LABELS[name], **prof.summary(), **xva_block(times, PE, NE, D, cfg, anti)}
        for q in (0.95, 0.99):
            _, tq = prof.peak_pfe(q)
            k = int(round(tq * cfg.steps_per_year))
            lo, hi = bootstrap_quantile_ci(PE[k], q, anti, n_boot=200 if quick else 400)
            block[f"peak_PFE_{q:g}_ci95"] = [lo, hi]
        res["regimes"][name] = block

    # regimes are built one at a time to bound memory
    PE, NE = gross_parts(Vs)
    do_regime("gross", PE, NE)
    PE[:] = 0.0
    NE[:] = 0.0
    for v in Vs:  # per-trade CSA, then no netting across trades
        vc = collateralised_mtm(v, cfg.csa)
        PE += np.maximum(vc, 0.0)
        NE += np.minimum(vc, 0.0)
        del vc
    do_regime("collateralised", PE, NE)
    del Vs, PE, NE
    PEn, NEn = net_parts(V)
    do_regime("netted", PEn, NEn)
    del NEn
    Vc_net = collateralised_mtm(V, cfg.csa)
    do_regime("netted_collateralised", *net_parts(Vc_net))
    res["regimes"] = {name: res["regimes"][name] for name in REGIMES}
    timing["regime_aggregation_s"] = time.perf_counter() - t_agg
    res["base_timing"] = timing

    g = res["regimes"]["gross"]
    res["reductions_vs_gross"] = {
        name: {
            "EPE_pct": 100 * (1 - res["regimes"][name]["EPE"]["value"] / g["EPE"]["value"]),
            "CVA_pct": 100 * (1 - res["regimes"][name]["CVA"]["value"] / g["CVA"]["value"]),
            "peak_PFE_0.99_pct": 100 * (1 - res["regimes"][name]["peak_PFE_0.99"] / g["peak_PFE_0.99"]),
        }
        for name in REGIMES
    }

    # CVA term-structure contributions for the netted uncollateralised set
    cva_n = cva(times, PEn, D, cfg.counterparty, anti)
    PEc = np.maximum(Vc_net, 0.0)

    # ---------------- 2. CSA variants & sweeps (netted) ----------------
    def coll_metrics(csa: CSA) -> dict:
        Vc = collateralised_mtm(V, csa)
        PE, NE = net_parts(Vc)
        prof = ExposureProfile.from_parts(times, PE, NE, D, anti, quantiles=(0.95, 0.99))
        return {
            "EPE": prof.epe.value,
            "peak_PFE_0.95": prof.peak_pfe(0.95)[0],
            "peak_PFE_0.99": prof.peak_pfe(0.99)[0],
            "CVA": cva(times, PE, D, cfg.counterparty, anti).value,
            "CVA_se": cva(times, PE, D, cfg.counterparty, anti).estimate.se,
        }

    base = cfg.csa
    res["csa_variants"] = {
        "base_two_way": {"csa": base.__dict__, **coll_metrics(base)},
        "one_way_cpty_posts_only": {"csa": replace(base, own_threshold=np.inf).__dict__, **coll_metrics(replace(base, own_threshold=np.inf))},
        "base_plus_IA_5mm": {"csa": replace(base, independent_amount=5 * MM).__dict__, **coll_metrics(replace(base, independent_amount=5 * MM))},
        "zero_TH_MTA_daily_like_no_MPoR": {
            "csa": replace(base, cpty_threshold=0, own_threshold=0, mta=0, mpor_steps=0).__dict__,
            **coll_metrics(replace(base, cpty_threshold=0, own_threshold=0, mta=0, mpor_steps=0)),
        },
    }
    for v in res["csa_variants"].values():
        v["csa"] = {k: (None if isinstance(x, float) and np.isinf(x) else x) for k, x in v["csa"].items()}

    sweeps = {
        "mpor_steps": [0, 1, 2, 4, 8],
        "cpty_threshold_mm": [0, 1, 2, 5, 10, 20, 50],
        "mta_mm": [0, 0.25, 0.5, 1, 2, 5],
        "margin_freq_steps": [1, 2, 4, 12],
        "settlement_lag_steps": [0, 1, 2],
        "independent_amount_mm": [0, 2.5, 5, 10],
    }
    sweep_rows = []
    for param, values in sweeps.items():
        for val in values:
            if param == "mpor_steps":
                csa = replace(base, mpor_steps=val)
            elif param == "cpty_threshold_mm":
                csa = replace(base, cpty_threshold=val * MM, own_threshold=val * MM)
            elif param == "mta_mm":
                csa = replace(base, mta=val * MM)
            elif param == "margin_freq_steps":
                csa = replace(base, margin_freq_steps=val)
            elif param == "settlement_lag_steps":
                csa = replace(base, settlement_lag_steps=val)
            else:
                csa = replace(base, independent_amount=val * MM)
            sweep_rows.append({"parameter": param, "value": val, **coll_metrics(csa)})
    res["csa_sweeps"] = sweep_rows
    _write_csv(out_dir / "csa_sweeps.csv", sweep_rows)

    # ---------------- 3. CVA sensitivities ----------------
    sens_rows = []
    for m in [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        cp = cfg.counterparty.with_(hazard=cfg.counterparty.hazard.scaled(m))
        sens_rows.append({"driver": "hazard_multiplier", "value": m,
                          "CVA_netted": cva(times, PEn, D, cp, anti).value,
                          "CVA_netted_collateralised": cva(times, PEc, D, cp, anti).value})
    for lgd in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        cp = cfg.counterparty.with_(recovery=1.0 - lgd)  # hazard held fixed
        sens_rows.append({"driver": "LGD", "value": lgd,
                          "CVA_netted": cva(times, PEn, D, cp, anti).value,
                          "CVA_netted_collateralised": cva(times, PEc, D, cp, anti).value})
    n_vol = min(cfg.n_paths, 10_000)
    for sig in [0.0025, 0.005, 0.0075, 0.010, 0.0125, 0.015]:
        model = HullWhite1F(cfg.hw_a, sig, cfg.curve)
        t2_, D2, V2, _ = value_netted(cfg, n_vol, cfg.seed, anti, model=model)
        sens_rows.append({"driver": "rates_vol", "value": sig,
                          "CVA_netted": cva(t2_, np.maximum(V2, 0), D2, cfg.counterparty, anti).value,
                          "CVA_netted_collateralised": cva(t2_, np.maximum(collateralised_mtm(V2, cfg.csa), 0), D2, cfg.counterparty, anti).value})
        del D2, V2
    res["cva_sensitivity"] = sens_rows
    _write_csv(out_dir / "cva_sensitivity.csv", sens_rows)

    # ---------------- 4. Wrong-way risk ----------------
    betas = [-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0] if not quick else [-0.5, 0.0, 0.5]
    wwr_rows = []
    wwr_profiles = {}
    for regime, Vr in (("netted", V), ("netted_collateralised", Vc_net)):
        PEr = np.maximum(Vr, 0.0)
        base_cva = cva(times, PEr, D, cfg.counterparty, anti).value
        for b in betas:
            pdp = wwr_default_probs(times, Vr, cfg.counterparty.hazard, b)
            ch = cva(times, PEr, D, cfg.counterparty, anti, pd_paths=pdp)
            cee = conditional_exposure(PEr, pdp)
            cpfe = conditional_exposure(PEr, pdp, 0.99)
            row = {
                "regime": regime, "beta": b, "CVA": ch.value, "CVA_se": ch.estimate.se,
                "CVA_ratio_to_independent": ch.value / base_cva if base_cva else float("nan"),
                "cond_peak_EE": float(cee.max()), "cond_peak_PFE_0.99": float(cpfe.max()),
                "uncond_peak_EE": float(PEr.mean(axis=1).max()),
                "uncond_peak_PFE_0.99": float(np.quantile(PEr, 0.99, axis=1).max()),
                "max_abs_PD_calibration_error": float(np.max(np.abs(pdp.mean(axis=1) - cfg.counterparty.hazard.marginal_pd(times)))),
            }
            wwr_rows.append(row)
            if regime == "netted":
                wwr_profiles[b] = (cee, cpfe)
    res["wrong_way_risk"] = wwr_rows
    _write_csv(out_dir / "wrong_way_risk.csv", wwr_rows)

    # ---------------- 5. Diagnostics ----------------
    P0 = cfg.curve.discount(times)
    zD = [mean_estimate(D[k] / P0[k] - 1.0, anti) for k in range(1, len(times))]
    res["diagnostics"] = {
        "max_abs_rel_err_E[D(t)]_vs_P0(t)": float(max(abs(e.value) for e in zD)),
        "max_abs_z_E[D(t)]_vs_P0(t)": float(max(abs(e.value / e.se) for e in zD)),
        **early_diag,
    }

    # ---------------- 6. persist arrays for figures ----------------
    rng = np.random.default_rng(1)
    sample_idx = rng.choice(V.shape[1], size=40, replace=False)
    # a typical in-the-money path for the CSA figure: V(1.5y) near its 85th percentile
    k15 = int(1.5 * cfg.steps_per_year)
    path_k = int(np.argmin(np.abs(V[k15] - np.quantile(V[k15], 0.85))))
    bal = collateral_balance(V[:, [path_k]], cfg.csa)[:, 0]
    m = cfg.csa.mpor_steps
    lagged = bal.copy()
    if m > 0:
        lagged[m:] = bal[:-m]
        lagged[:m] = bal[0]
    arrays = dict(
        times=times,
        sample_paths=V[:, sample_idx],
        mech_V=V[:, path_k],
        mech_balance=bal,
        mech_lagged=lagged,
        mech_coll=collateralised_mtm(V[:, [path_k]], cfg.csa)[:, 0],
        cva_buckets=cva_n.bucket_contrib,
        surv_c=cfg.counterparty.hazard.survival(times),
        surv_b=cfg.own.hazard.survival(times),
        haz_c=cfg.counterparty.hazard.hazard(np.maximum(times, 1e-9)),
        haz_b=cfg.own.hazard.hazard(np.maximum(times, 1e-9)),
        pd_c=cfg.counterparty.hazard.marginal_pd(times),
        wwr_betas=np.array(sorted(wwr_profiles)),
        wwr_cond_ee=np.array([wwr_profiles[b][0] for b in sorted(wwr_profiles)]),
        wwr_cond_pfe99=np.array([wwr_profiles[b][1] for b in sorted(wwr_profiles)]),
        **{f"{r}_{k}": getattr(profiles[r], k) for r in REGIMES for k in ("ee", "ene", "ee_disc", "ee_se", "mean_mtm")},
        **{f"{r}_pfe{int(q * 1000)}": profiles[r].pfe[q] for r in REGIMES for q in profiles[r].pfe},
        **{f"trade{i}_ee": ee for i, ee in enumerate(trade_ee)},
    )
    np.savez_compressed(out_dir / "profiles.npz", **arrays)
    del V, Vc_net, PEn, PEc, D, arrays  # free the base-run arrays before the convergence study

    # ---------------- 7. Convergence, variance reduction, runtime ----------------
    counts = [500, 1000, 2000, 4000, 8000, 16000, 32000] if not quick else [500, 1000, 2000]
    conv_rows = []
    for n in counts:
        for a in (True, False):
            est, epe, pfe99, tm = netted_cva_only(cfg, n, cfg.seed + 1, a)
            conv_rows.append({"n_paths": n, "antithetic": a, "CVA": est.value, "CVA_se": est.se,
                              "CVA_ci_lo": est.lo, "CVA_ci_hi": est.hi, "EPE": epe.value, "EPE_se": epe.se,
                              "peak_PFE_0.99": pfe99, **tm})
    res["convergence"] = conv_rows
    _write_csv(out_dir / "convergence.csv", conv_rows)

    # reference: independent large antithetic runs pooled
    n_ref, n_ref_batches = (32000, 4) if not quick else (2000, 2)
    ref_vals, ref_ses = [], []
    for i in range(n_ref_batches):
        est, _, _, _ = netted_cva_only(cfg, n_ref, cfg.seed + 1000 + i, True)
        ref_vals.append(est.value)
        ref_ses.append(est.se)
    ref = float(np.mean(ref_vals))
    ref_se = float(np.sqrt(np.sum(np.square(ref_ses))) / n_ref_batches)
    res["reference_CVA_netted"] = {"value": ref, "se": ref_se, "n_paths_total": n_ref * n_ref_batches}

    # seed replication: does the reported CI cover the reference?
    n_rep, n_seeds = (2000, 40) if not quick else (500, 6)
    reps = []
    for i in range(n_seeds):
        est, _, _, _ = netted_cva_only(cfg, n_rep, cfg.seed + 5000 + i, True)
        reps.append((est.value, est.se, est.lo <= ref <= est.hi))
    vals = np.array([r[0] for r in reps])
    res["seed_replication"] = {
        "n_paths": n_rep, "n_seeds": n_seeds, "mean_CVA": float(vals.mean()),
        "empirical_std": float(vals.std(ddof=1)), "mean_reported_se": float(np.mean([r[1] for r in reps])),
        "ci95_coverage_of_reference": float(np.mean([r[2] for r in reps])),
    }

    # variance reduction factor at equal path budget (largest n)
    nmax = counts[-1]
    a_row = next(r for r in conv_rows if r["n_paths"] == nmax and r["antithetic"])
    p_row = next(r for r in conv_rows if r["n_paths"] == nmax and not r["antithetic"])
    res["variance_reduction"] = {
        "n_paths": nmax,
        "CVA_variance_ratio_plain_over_antithetic": (p_row["CVA_se"] / a_row["CVA_se"]) ** 2,
        "EPE_variance_ratio_plain_over_antithetic": (p_row["EPE_se"] / a_row["EPE_se"]) ** 2,
        "runtime_ratio_antithetic_over_plain": a_row["total_s"] / p_row["total_s"],
    }

    res["total_runtime_s"] = time.perf_counter() - T0
    res["machine"] = {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()}

    with open(out_dir / "summary.json", "w") as f:
        json.dump(_clean(res), f, indent=2)
    return res


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="small path counts for CI smoke runs")
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)
    cfg = ExperimentConfig(n_paths=2000) if args.quick else ExperimentConfig()
    res = run(cfg, Path(args.out), quick=args.quick)
    n = res["regimes"]["netted"]
    print(f"done in {res['total_runtime_s']:.1f}s | netted EPE {n['EPE']['value'] / MM:.3f}mm | CVA {n['CVA']['value']:,.0f}")


if __name__ == "__main__":
    main()
