"""Render result tables into the Markdown docs and reconcile them.

Two kinds of markers are supported in README.md / ANALYSIS.md:

  Block:   <!-- BEGIN:name --> ... <!-- END:name -->
           replaced by the generated table `name`.
  Inline:  <!--v:path|fmt-->123.4<!--/v-->
           a single number; `path` is a dotted path into summary.json (or
           into the derived dict `d.*`), `fmt` is one of mm, k, pct, x, s, f2, i.

    python -m xva.report --write    # regenerate all marked numbers
    python -m xva.report --check    # fail if any marked number is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DOCS = ("README.md", "ANALYSIS.md", "RESUME_BULLETS.md")
REG = ("gross", "netted", "collateralised", "netted_collateralised")
REG_SHORT = {
    "gross": "1. Gross, uncollateralised",
    "netted": "2. Netted, uncollateralised",
    "collateralised": "3. Collateralised, not netted",
    "netted_collateralised": "4. Netted + collateralised",
}


def fmt(v, kind: str) -> str:
    if v is None:
        return "n/a"
    if kind == "mm":
        return f"{v / 1e6:,.2f}"
    if kind == "k":
        return f"{v / 1e3:,.1f}"
    if kind == "pct":
        return f"{v:.1f}"
    if kind == "x":
        return f"{v:.2f}"
    if kind == "s":
        return f"{v:.2f}"
    if kind == "f2":
        return f"{v:.2f}"
    if kind == "f4":
        return f"{v:.4f}"
    if kind == "i":
        return f"{int(round(v)):,}"
    if kind == "e":
        return f"{v:.1e}"
    raise ValueError(kind)


def derived(S: dict) -> dict:
    d = {}
    for row in S["wrong_way_risk"]:
        key = f"wwr_{row['regime']}_b{row['beta']:+.2f}".replace(".", "p")
        d[key + "_ratio"] = row["CVA_ratio_to_independent"]
        d[key + "_cva"] = row["CVA"]
        d[key + "_cond_pfe99"] = row["cond_peak_PFE_0.99"]
        d[key + "_cond_ee"] = row["cond_peak_EE"]
    for row in S["convergence"]:
        tag = "anti" if row["antithetic"] else "plain"
        d[f"conv_{row['n_paths']}_{tag}_s"] = row["total_s"]
        d[f"conv_{row['n_paths']}_{tag}_se"] = row["CVA_se"]
    n = S["regimes"]["netted"]
    d["netting_benefit_cva"] = S["regimes"]["gross"]["CVA"]["value"] - n["CVA"]["value"]
    d["collateral_benefit_cva"] = n["CVA"]["value"] - S["regimes"]["netted_collateralised"]["CVA"]["value"]
    d["cva_ci_halfwidth_netted"] = n["CVA"]["ci95_hi"] - n["CVA"]["value"]
    d["cva_rel_ci_netted_pct"] = 100 * d["cva_ci_halfwidth_netted"] / n["CVA"]["value"]
    d["seed_cov_pct"] = 100 * S["seed_replication"]["ci95_coverage_of_reference"]
    sens = {(r["driver"], r["value"]): r for r in S["cva_sensitivity"]}
    d["cva_hazard_x4_ratio"] = sens[("hazard_multiplier", 4.0)]["CVA_netted"] / sens[("hazard_multiplier", 1.0)]["CVA_netted"]
    for key, tag in (("CVA_netted", "n"), ("CVA_netted_collateralised", "nc")):
        d[f"vol_ratio_{tag}"] = sens[("rates_vol", 0.015)][key] / sens[("rates_vol", 0.0025)][key]
    for r in S["csa_sweeps"]:
        d[f"sweep_{r['parameter']}_{r['value']:g}_cva".replace(".", "p")] = r["CVA"]
        d[f"sweep_{r['parameter']}_{r['value']:g}_epe".replace(".", "p")] = r["EPE"]
    return d


def _ci(e, kind):
    return f"{fmt(e['value'], kind)} [{fmt(e['ci95_lo'], kind)}, {fmt(e['ci95_hi'], kind)}]"


def tables(S: dict) -> dict:
    T = {}
    R = S["regimes"]
    # --- headline exposure table
    lines = [
        "| Regime | EPE (mm) [95% CI] | EEPE 1y (mm) | Peak EE (mm) | Peak PFE 95% (mm) | Peak PFE 99% (mm) [95% CI] | EPE reduction vs gross |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in REG:
        x = R[r]
        ci = x["peak_PFE_0.99_ci95"]
        lines.append(
            f"| {REG_SHORT[r]} | {_ci(x['EPE'], 'mm')} | {fmt(x['EEPE_1y'], 'mm')} | {fmt(x['peak_EE'], 'mm')} "
            f"| {fmt(x['peak_PFE_0.95'], 'mm')} | {fmt(x['peak_PFE_0.99'], 'mm')} [{fmt(ci[0], 'mm')}, {fmt(ci[1], 'mm')}] "
            f"| {fmt(S['reductions_vs_gross'][r]['EPE_pct'], 'pct')}% |"
        )
    T["exposure"] = "\n".join(lines)

    # --- XVA table
    lines = [
        "| Regime | CVA (k) [95% CI] | CVA reduction vs gross | DVA (k) | FCA (k) | FBA (k) | FVA = FCA - FBA (k) | Bilateral CVA (k) | Bilateral DVA (k) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in REG:
        x = R[r]
        lines.append(
            f"| {REG_SHORT[r]} | {_ci(x['CVA'], 'k')} | {fmt(S['reductions_vs_gross'][r]['CVA_pct'], 'pct')}% "
            f"| {fmt(x['DVA']['value'], 'k')} | {fmt(x['FCA']['value'], 'k')} | {fmt(x['FBA']['value'], 'k')} "
            f"| {fmt(x['FVA']['value'], 'k')} | {fmt(x['CVA_bilateral']['value'], 'k')} | {fmt(x['DVA_bilateral']['value'], 'k')} |"
        )
    T["xva"] = "\n".join(lines)

    # --- portfolio
    lines = ["| Trade (SIMULATED) | Type | Notional | Maturity (y) | Fixed rate / strike | MtM today (mm) | Stand-alone EPE (mm) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for tr in S["trades"]:
        rs = tr["rate_or_strike"]
        rs_s = f"{100 * rs:.3f}%" if tr["type"] == "InterestRateSwap" else f"{rs:.4f}"
        ccy = "FOR" if tr["type"] == "FXForward" else "DOM"
        lines.append(f"| {tr['name']} | {tr['type']} | {fmt(tr['notional'], 'mm')}mm {ccy} | {tr['maturity']:g} | {rs_s} "
                     f"| {fmt(tr['mtm_t0'], 'mm')} | {fmt(tr['standalone_EPE'], 'mm')} |")
    lines.append(f"| **Netting set** | | | | | **{fmt(S['portfolio_mtm_t0'], 'mm')}** | **{fmt(R['netted']['EPE']['value'], 'mm')}** |")
    T["portfolio"] = "\n".join(lines)

    # --- CSA variants
    names = {
        "base_two_way": "Base two-way CSA",
        "one_way_cpty_posts_only": "One-way CSA (only counterparty posts)",
        "base_plus_IA_5mm": "Base + 5mm independent amount received",
        "zero_TH_MTA_daily_like_no_MPoR": "Idealised: TH = MTA = MPoR = 0",
    }
    lines = ["| CSA variant (netted) | EPE (mm) | Peak PFE 95% (mm) | Peak PFE 99% (mm) | CVA (k) |", "|---|---:|---:|---:|---:|"]
    for key, lab in names.items():
        x = S["csa_variants"][key]
        lines.append(f"| {lab} | {fmt(x['EPE'], 'mm')} | {fmt(x['peak_PFE_0.95'], 'mm')} | {fmt(x['peak_PFE_0.99'], 'mm')} | {fmt(x['CVA'], 'k')} |")
    T["csa_variants"] = "\n".join(lines)

    # --- CSA sweeps
    lines = ["| CSA parameter | Value | EPE (mm) | Peak PFE 99% (mm) | CVA (k) |", "|---|---:|---:|---:|---:|"]
    for r in S["csa_sweeps"]:
        lines.append(f"| {r['parameter']} | {r['value']:g} | {fmt(r['EPE'], 'mm')} | {fmt(r['peak_PFE_0.99'], 'mm')} | {fmt(r['CVA'], 'k')} |")
    T["csa_sweeps"] = "\n".join(lines)

    # --- WWR
    lines = ["| Regime | beta | CVA (k) +/- 1.96 SE | CVA / independent | Peak EE given default (mm) | Peak PFE 99% given default (mm) |",
             "|---|---:|---:|---:|---:|---:|"]
    for r in S["wrong_way_risk"]:
        lines.append(f"| {r['regime']} | {r['beta']:+.2f} | {fmt(r['CVA'], 'k')} +/- {fmt(1.96 * r['CVA_se'], 'k')} | {fmt(r['CVA_ratio_to_independent'], 'x')}x "
                     f"| {fmt(r['cond_peak_EE'], 'mm')} | {fmt(r['cond_peak_PFE_0.99'], 'mm')} |")
    T["wwr"] = "\n".join(lines)

    # --- convergence
    lines = ["| Paths | Antithetic | CVA (k) | Std. error (k) | 95% CI (k) | EPE (mm) | Runtime (s) |", "|---:|:---:|---:|---:|---:|---:|---:|"]
    for r in S["convergence"]:
        lines.append(f"| {r['n_paths']:,} | {'yes' if r['antithetic'] else 'no'} | {fmt(r['CVA'], 'k')} | {fmt(r['CVA_se'], 'k')} "
                     f"| [{fmt(r['CVA_ci_lo'], 'k')}, {fmt(r['CVA_ci_hi'], 'k')}] | {fmt(r['EPE'], 'mm')} | {fmt(r['total_s'], 's')} |")
    T["convergence"] = "\n".join(lines)

    # --- sensitivities
    lines = ["| Driver | Value | CVA netted (k) | CVA netted + collateralised (k) |", "|---|---:|---:|---:|"]
    for r in S["cva_sensitivity"]:
        v = f"{r['value'] * 1e4:g}bp" if r["driver"] == "rates_vol" else f"{r['value']:g}"
        lines.append(f"| {r['driver']} | {v} | {fmt(r['CVA_netted'], 'k')} | {fmt(r['CVA_netted_collateralised'], 'k')} |")
    T["sensitivity"] = "\n".join(lines)

    # --- diagnostics
    dg = S["diagnostics"]
    sr = S["seed_replication"]
    vr = S["variance_reduction"]
    lines = [
        "| Check | Result |", "|---|---|",
        f"| max relative error of E[D(0,t)] vs P(0,t) over all dates | {fmt(dg['max_abs_rel_err_E[D(t)]_vs_P0(t)'], 'e')} (max abs z-score {fmt(dg['max_abs_z_E[D(t)]_vs_P0(t)'], 'f2')}) |",
        f"| FX forward deflated-value martingale error at 1y | {fmt(dg['fx_forward_martingale_err_1y_DOM'], 'i')} DOM on {fmt(dg['fx_forward_notional_DOM'], 'mm')}mm notional (z = {fmt(dg['fx_forward_martingale_z_1y'], 'f2')}) |",
        f"| Par forward-start swap MtM today | {fmt(dg['irs3_mtm_t0_par_check_DOM'], 'f2')} DOM |",
        f"| Variance reduction (plain / antithetic variance, CVA, {vr['n_paths']:,} paths) | {fmt(vr['CVA_variance_ratio_plain_over_antithetic'], 'x')}x |",
        f"| Variance reduction (EPE) | {fmt(vr['EPE_variance_ratio_plain_over_antithetic'], 'x')}x |",
        f"| Seed replication: {sr['n_seeds']} seeds x {sr['n_paths']:,} paths - empirical std of CVA vs mean reported SE | {fmt(sr['empirical_std'], 'k')}k vs {fmt(sr['mean_reported_se'], 'k')}k |",
        f"| Seed replication: share of 95% CIs covering the {S['reference_CVA_netted']['n_paths_total']:,}-path reference | {fmt(100 * sr['ci95_coverage_of_reference'], 'pct')}% |",
        f"| Reference netted CVA ({S['reference_CVA_netted']['n_paths_total']:,} paths) | {fmt(S['reference_CVA_netted']['value'], 'k')}k +/- {fmt(1.96 * S['reference_CVA_netted']['se'], 'k')}k |",
    ]
    T["diagnostics"] = "\n".join(lines)

    bt = S["base_timing"]
    lines = ["| Stage (base run, {:,} paths x {} dates x {} trades) | Seconds |".format(S["config"]["n_paths"], int(S["config"]["horizon_years"] * S["config"]["steps_per_year"]) + 1, len(S["trades"])),
             "|---|---:|",
             f"| Scenario simulation (rates, discount factors, FX) | {fmt(bt['simulation_s'], 's')} |",
             f"| Re-valuation of all trades on all paths and dates | {fmt(bt['valuation_s'], 's')} |",
             f"| Netting, 7 CSA simulations (6 per-trade + 1 netted), exposure stats, PFE bootstrap CIs, XVA for 4 regimes | {fmt(bt['regime_aggregation_s'], 's')} |",
             f"| Whole experiment (all sweeps, WWR, convergence) | {fmt(S['total_runtime_s'], 's')} |"]
    T["runtime"] = "\n".join(lines)
    return T


BLOCK_RE = re.compile(r"(<!-- BEGIN:(\w+) -->\n)(.*?)(<!-- END:\2 -->)", re.S)
INLINE_RE = re.compile(r"<!--v:([^|>]+)\|(\w+)-->(.*?)<!--/v-->")


def render_text(text: str, S: dict) -> str:
    T = tables(S)

    def blk(m):
        name = m.group(2)
        if name not in T:
            raise KeyError(f"unknown block {name}")
        return m.group(1) + T[name] + "\n" + m.group(4)

    def inl(m):
        return f"<!--v:{m.group(1)}|{m.group(2)}-->{fmt(_resolve_any(S, m.group(1)), m.group(2))}<!--/v-->"

    return INLINE_RE.sub(inl, BLOCK_RE.sub(blk, text))


def _resolve_any(S, path):
    # Support keys with dots (peak_PFE_0.99) by greedy matching.
    root = {**S, "d": derived(S)}
    parts = path.split(".")
    cur = root
    i = 0
    while i < len(parts):
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if isinstance(cur, list) and key.isdigit():
                cur = cur[int(key)]
                i = j
                break
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
                i = j
                break
        else:
            raise KeyError(path)
    return cur


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    ap.add_argument("--results", default="results/summary.json")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    S = json.load(open(a.results))
    stale = []
    n_marks = 0
    for doc in DOCS:
        p = Path(a.root) / doc
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        n_marks += len(BLOCK_RE.findall(text)) + len(INLINE_RE.findall(text))
        new = render_text(text, S)
        for m in BLOCK_RE.finditer(new):
            if not m.group(3).strip():
                raise SystemExit(f"{doc}: block {m.group(2)} rendered empty")
        if a.write:
            p.write_text(new, encoding="utf-8", newline="\n")
        elif new != text:
            stale.append(doc)
    if a.check:
        if stale:
            print(f"STALE numbers in: {', '.join(stale)} - run python -m xva.report --write")
            sys.exit(1)
        print(f"README/ANALYSIS reconciled with {a.results}: {n_marks} generated tables/values match")
    else:
        print(f"wrote {n_marks} generated tables/values")


if __name__ == "__main__":
    main()
