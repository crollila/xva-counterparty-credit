"""Figures generated from results/summary.json + results/profiles.npz.

    python -m xva.figures [--results results] [--out figures]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# Validated categorical order (blue, orange, aqua, yellow, magenta, green, violet, red)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
MM = 1e6
REG = ["gross", "netted", "collateralised", "netted_collateralised"]
REG_LBL = ["Gross, uncollateralised", "Netted, uncollateralised", "Collateralised, not netted", "Netted + collateralised"]
SIM_TAG = "SIMULATED portfolio · simplified methodology"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.axisbelow": True, "axes.titlesize": 11, "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 2,
})


def _tag(fig):
    fig.text(0.995, 0.005, SIM_TAG, ha="right", va="bottom", fontsize=7.5, color=MUTED)


def _save(fig, out: Path, name: str):
    _tag(fig)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(out / name, dpi=140)
    plt.close(fig)


def make_all(results: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    S = json.load(open(results / "summary.json"))
    P = np.load(results / "profiles.npz")
    t = P["times"]

    # 1. what a Monte Carlo exposure simulation looks like
    fig, ax = plt.subplots(figsize=(9, 5))
    for i in range(P["sample_paths"].shape[1]):
        ax.plot(t, P["sample_paths"][:, i] / MM, color=MUTED, lw=0.6, alpha=0.45)
    ax.plot(t, P["netted_ee"] / MM, color=C[0], label="EE: average of max(V, 0)")
    ax.plot(t, P["netted_ene"] / MM, color=C[1], label="ENE: average of min(V, 0)")
    ax.plot(t, P["netted_pfe950"] / MM, color=C[2], ls="--", label="PFE 95%")
    ax.plot(t, P["netted_pfe990"] / MM, color=C[6], ls="--", label="PFE 99%")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set(xlabel="years from today", ylabel="netting-set value V(t), DOM mm",
           title="40 simulated future values of the portfolio (grey) and the exposure statistics built from them")
    ax.legend(loc="upper right", ncol=2)
    _save(fig, out, "fig01_paths_ee_pfe.png")

    # 2. exposure profile with CI
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ee, se = P["netted_ee"] / MM, P["netted_ee_se"] / MM
    ax.fill_between(t, ee - 1.96 * se, ee + 1.96 * se, color=C[0], alpha=0.2, lw=0, label="95% MC confidence band")
    ax.plot(t, ee, color=C[0], label="EE (undiscounted)")
    ax.plot(t, P["netted_ee_disc"] / MM, color=C[0], ls=":", label="EE* discounted (feeds CVA)")
    ax.plot(t, P["netted_ene"] / MM, color=C[1], label="ENE")
    ax.plot(t, P["netted_mean_mtm"] / MM, color=INK2, lw=1, ls="--", label="expected MtM E[V]")
    epe = S["regimes"]["netted"]["EPE"]["value"] / MM
    ax.axhline(epe, color=C[0], lw=1, alpha=0.6)
    ax.annotate(f"EPE (time-average of EE) = {epe:.2f}mm", (9.9, epe), ha="right", va="bottom", color=INK2, fontsize=9)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set(xlabel="years", ylabel="DOM mm", title="Expected exposure profile - netted, uncollateralised")
    ax.legend(loc="lower left", ncol=2)
    _save(fig, out, "fig02_exposure_profile.png")

    # 3. PFE profile
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, r, ttl in ((axs[0], "netted", "Netted, uncollateralised"), (axs[1], "netted_collateralised", "Netted + collateralised")):
        for j, (q, lab) in enumerate(((900, "90%"), (950, "95%"), (975, "97.5%"), (990, "99%"))):
            ax.plot(t, P[f"{r}_pfe{q}"] / MM, color=[C[2], C[0], C[3], C[6]][j], label=f"PFE {lab}")
        ax.plot(t, P[f"{r}_ee"] / MM, color=INK2, lw=1, ls="--", label="EE")
        ax.set(title=ttl, xlabel="years")
    axs[0].set_ylabel("DOM mm")
    axs[0].legend(loc="upper right")
    axs[1].annotate("spike: FX forward settles at 2y while\ncollateral is frozen during the MPoR",
                    xy=(2.04, S["regimes"]["netted_collateralised"]["peak_PFE_0.99"] / MM), xytext=(3.2, 20),
                    arrowprops=dict(arrowstyle="->", color=INK2), fontsize=8.5, color=INK2)
    _save(fig, out, "fig03_pfe_profile.png")

    # 4. regimes
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.4))
    for i, r in enumerate(REG):
        axs[0].plot(t, P[f"{r}_ee"] / MM, color=C[i], label=REG_LBL[i])
        axs[1].plot(t, P[f"{r}_pfe990"] / MM, color=C[i], label=REG_LBL[i])
    axs[0].set(title="Expected exposure (EE)", xlabel="years", ylabel="DOM mm")
    axs[1].set(title="PFE 99%", xlabel="years")
    axs[0].legend(loc="upper right")
    _save(fig, out, "fig04_collateralised_vs_uncollateralised.png")

    # 5. collateral mechanics on one path
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.3, 1]})
    th = S["config"]["csa"]["cpty_threshold"] / MM
    for ax, (a, b) in zip(axs, ((0, 10), (1.0, 2.0))):
        m = (t >= a - 1e-9) & (t <= b + 1e-9)
        tv, v, lag = t[m], P["mech_V"][m] / MM, P["mech_lagged"][m] / MM
        expo = np.maximum(P["mech_coll"][m], 0) / MM
        ax.fill_between(tv, lag, lag + expo, color=C[7], alpha=0.35, lw=0, step="post", label="exposure = V - C(t - MPoR)")
        ax.plot(tv, v, color=C[0], label="portfolio value V(t)")
        ax.step(tv, P["mech_balance"][m] / MM, where="post", color=C[3], lw=1.5, label="collateral settled C(t)")
        ax.step(tv, lag, where="post", color=C[6], lw=1.5, ls="--", label="collateral at close-out C(t - MPoR)")
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set(xlabel="years")
    axs[0].set(title="One simulated path: value vs collateral", ylabel="DOM mm")
    axs[1].set(title=f"Zoom 1y-2y: the gap is threshold ({th:g}mm) + MPoR move")
    axs[0].legend(loc="upper right", fontsize=8.5)
    _save(fig, out, "fig05_collateral_mechanics.png")

    # 6. credit curves
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8))
    axs[0].step(t, P["haz_c"] * 1e4, where="pre", color=C[7], label="counterparty")
    axs[0].step(t, P["haz_b"] * 1e4, where="pre", color=C[0], label="us (own)")
    axs[0].set(title="Hazard rate lambda(t)", xlabel="years", ylabel="bp per year")
    axs[0].legend()
    axs[1].plot(t, P["surv_c"], color=C[7], label="counterparty")
    axs[1].plot(t, P["surv_b"], color=C[0], label="us (own)")
    axs[1].set(title="Survival probability S(t)", xlabel="years", ylim=(0.6, 1.005))
    yrs = np.arange(1, 11)
    pd_year = [P["pd_c"][(t[1:] > y - 1) & (t[1:] <= y + 1e-9)].sum() * 100 for y in yrs]
    axs[2].bar(yrs, pd_year, color=C[7], width=0.7)
    axs[2].set(title="Counterparty default prob. per year", xlabel="year", ylabel="%")
    _save(fig, out, "fig06_credit_curves.png")

    # 7. CVA term structure
    fig, ax = plt.subplots(figsize=(9, 4))
    b = P["cva_buckets"]
    by_year = [b[(t[1:] > y - 1) & (t[1:] <= y + 1e-9)].sum() / 1e3 for y in yrs]
    ax.bar(yrs, by_year, color=C[0], width=0.7)
    for y, v in zip(yrs, by_year):
        ax.text(y, v, f"{v:.0f}k", ha="center", va="bottom", fontsize=8.5, color=INK2)
    tot = S["regimes"]["netted"]["CVA"]["value"] / 1e3
    ax.set(title=f"Where the CVA comes from: LGD x EE*(t) x PD(t) summed by year (total {tot:,.0f}k)",
           xlabel="year", ylabel="CVA contribution, DOM thousands")
    _save(fig, out, "fig07_cva_term_structure.png")

    # 8. CVA sensitivity
    sens = S["cva_sensitivity"]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.9))
    for ax, drv, xl, scale in ((axs[0], "hazard_multiplier", "hazard-rate multiplier", 1),
                               (axs[1], "LGD", "LGD (hazard held fixed)", 1),
                               (axs[2], "rates_vol", "Hull-White sigma (bp)", 1e4)):
        rows = [r for r in sens if r["driver"] == drv]
        x = [r["value"] * scale for r in rows]
        ax.plot(x, [r["CVA_netted"] / 1e3 for r in rows], color=C[1], marker="o", ms=5, label="netted")
        ax.plot(x, [r["CVA_netted_collateralised"] / 1e3 for r in rows], color=C[0], marker="o", ms=5, label="netted + collateralised")
        ax.set(xlabel=xl, title=f"CVA vs {xl.split(' (')[0]}")
    axs[0].set_ylabel("CVA, DOM thousands")
    axs[0].legend()
    _save(fig, out, "fig08_cva_sensitivity.png")

    # 9. CSA sensitivity
    sw = S["csa_sweeps"]
    fig, axs = plt.subplots(1, 4, figsize=(13, 3.6), sharey=True)
    for ax, (p, xl) in zip(axs, (("mpor_steps", "MPoR (grid steps, ~1.1 wk)"), ("cpty_threshold_mm", "threshold (mm)"),
                                 ("mta_mm", "MTA (mm)"), ("margin_freq_steps", "margin call every n steps"))):
        rows = [r for r in sw if r["parameter"] == p]
        x = np.arange(len(rows))
        ax.bar(x, [r["CVA"] / 1e3 for r in rows], color=C[0], width=0.65)
        ax.set_xticks(x, [f"{r['value']:g}" for r in rows])
        ax.set(xlabel=xl)
        ax.grid(axis="x", visible=False)
    axs[0].set_ylabel("CVA, DOM thousands")
    fig.suptitle("Netted + collateralised CVA as each CSA term is varied (others at base)", fontweight="bold")
    _save(fig, out, "fig09_csa_sensitivity.png")

    # 10. wrong-way risk
    w = S["wrong_way_risk"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    for i, r in enumerate(("netted", "netted_collateralised")):
        rows = [x for x in w if x["regime"] == r]
        axs[0].errorbar([x["beta"] for x in rows], [x["CVA"] / 1e3 for x in rows],
                        yerr=[1.96 * x["CVA_se"] / 1e3 for x in rows], color=[C[1], C[0]][i], marker="o", ms=5,
                        capsize=3, label=REG_LBL[i + 1 if i == 0 else 3])
    axs[0].axvline(0, color=INK2, lw=0.8)
    axs[0].set(xlabel="beta  (<0 right-way, >0 wrong-way)", ylabel="CVA, DOM thousands", title="CVA vs dependence strength")
    axs[0].legend()
    betas = P["wwr_betas"]
    pick = [i for i, bb in enumerate(betas) if bb in (-0.5, 0.0, 0.5, 1.0)]
    cols = {-0.5: C[2], 0.0: INK2, 0.5: C[1], 1.0: C[7]}
    for i in pick:
        axs[1].plot(t[1:], P["wwr_cond_ee"][i] / MM, color=cols[float(betas[i])], label=f"beta = {betas[i]:g}")
    axs[1].set(xlabel="years", ylabel="DOM mm", title="EE conditional on counterparty default (netted)")
    axs[1].legend()
    _save(fig, out, "fig10_wrong_way_risk.png")

    # 11. convergence
    cv = S["convergence"]
    ref = S["reference_CVA_netted"]["value"] / 1e3
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.9))
    for j, a in enumerate((True, False)):
        rows = [r for r in cv if r["antithetic"] == a]
        n = np.array([r["n_paths"] for r in rows])
        lab = "antithetic" if a else "plain MC"
        axs[0].errorbar(n * (1.04 if a else 0.96), [r["CVA"] / 1e3 for r in rows], yerr=[1.96 * r["CVA_se"] / 1e3 for r in rows],
                        color=C[j], marker="o", ms=4, capsize=3, label=lab)
        axs[1].loglog(n, [r["CVA_se"] / 1e3 for r in rows], color=C[j], marker="o", ms=4, label=lab)
        axs[2].loglog(n, [r["total_s"] for r in rows], color=C[j], marker="o", ms=4, label=lab)
    axs[0].axhline(ref, color=INK2, lw=1, ls="--", label="reference (128k paths)")
    axs[0].set_xscale("log")
    axs[0].set(xlabel="paths", ylabel="CVA, DOM thousands", title="CVA estimate +/- 95% CI")
    n0 = np.array([r["n_paths"] for r in cv if r["antithetic"]])
    se0 = [r["CVA_se"] for r in cv if r["antithetic"]][0] / 1e3
    axs[1].loglog(n0, se0 * np.sqrt(n0[0] / n0), color=MUTED, ls=":", lw=1.5, label="1/sqrt(N) slope")
    axs[1].set(xlabel="paths", ylabel="std. error, DOM thousands", title="Standard error")
    axs[2].set(xlabel="paths", ylabel="seconds", title="Runtime (simulate + value + CVA)")
    axs[0].legend(fontsize=8)
    axs[1].legend(fontsize=8)
    _save(fig, out, "fig11_convergence.png")

    # 12. netting/collateral waterfall-style bars
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    for ax, key, scale, unit in ((axs[0], "EPE", MM, "EPE, DOM mm"), (axs[1], "CVA", 1e3, "CVA, DOM thousands")):
        vals = [S["regimes"][r][key]["value"] / scale for r in REG]
        ax.bar(range(4), vals, color=C[:4], width=0.65)
        for i, v in enumerate(vals):
            red = S["reductions_vs_gross"][REG[i]][f"{key}_pct"]
            ax.text(i, v, (f"{v:,.2f}" if key == "EPE" else f"{v:,.0f}") + (f"\n(-{red:.0f}%)" if i else ""), ha="center", va="bottom", fontsize=8.5, color=INK2)
        ax.set_xticks(range(4), ["gross", "netted", "collat.", "netted\n+ collat."])
        ax.set(ylabel=unit, title=f"{key} by netting / collateral regime")
        ax.set_ylim(0, max(vals) * 1.25)
        ax.grid(axis="x", visible=False)
    _save(fig, out, "fig12_netting_collateral_reduction.png")

    # 13. why netting helps: standalone EEs vs netted EE
    fig, ax = plt.subplots(figsize=(9, 4.4))
    names = [tr["name"] for tr in S["trades"]]
    stack = np.array([P[f"trade{i}_ee"] for i in range(len(names))]) / MM
    ax.stackplot(t, stack, colors=C[: len(names)], labels=names, alpha=0.85, edgecolor=SURF, linewidth=0.5)
    ax.plot(t, P["netted_ee"] / MM, color=INK, lw=2.2, label="netted EE (one netting set)")
    ax.set(xlabel="years", ylabel="DOM mm", title="Sum of stand-alone trade EEs (stacked) vs netted EE")
    ax.legend(loc="upper right", fontsize=8)
    _save(fig, out, "fig13_netting_benefit.png")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="figures")
    a = ap.parse_args(argv)
    make_all(Path(a.results), Path(a.out))


if __name__ == "__main__":
    main()
