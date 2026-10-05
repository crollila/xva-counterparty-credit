# Analysis

> **Simulated portfolio, simplified XVA methodology.** Every input is synthetic (see `src/xva/config.py`). The
> purpose is to show how exposure and XVA respond to netting, collateral, credit and model choices, not to
> report real prices. Every number on this page is written from `results/summary.json` by
> `python -m xva.report --write` and checked by `--check`.

Base run: <!--v:config.n_paths|i-->20,000<!--/v--> antithetic paths, 48 steps per year over 10 years, seed
`20261004`. Amounts are in the made-up currency DOM.

## 1. Headline results

<!-- BEGIN:exposure -->
| Regime | EPE (mm) [95% CI] | EEPE 1y (mm) | Peak EE (mm) | Peak PFE 95% (mm) | Peak PFE 99% (mm) [95% CI] | EPE reduction vs gross |
|---|---:|---:|---:|---:|---:|---:|
| 1. Gross, uncollateralised | 5.02 [4.98, 5.05] | 6.07 | 9.41 | 23.51 | 30.79 [30.39, 31.53] | 0.0% |
| 2. Netted, uncollateralised | 3.84 [3.81, 3.87] | 2.51 | 6.05 | 21.01 | 28.22 [27.49, 28.81] | 23.4% |
| 3. Collateralised, not netted | 2.15 [2.15, 2.16] | 3.94 | 4.71 | 11.59 | 15.35 [15.08, 15.63] | 57.1% |
| 4. Netted + collateralised | 1.03 [1.03, 1.03] | 1.36 | 2.78 | 9.86 | 13.14 [12.92, 13.42] | 79.4% |
<!-- END:exposure -->

<!-- BEGIN:xva -->
| Regime | CVA (k) [95% CI] | CVA reduction vs gross | DVA (k) | FCA (k) | FBA (k) | FVA = FCA - FBA (k) | Bilateral CVA (k) | Bilateral DVA (k) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. Gross, uncollateralised | 657.7 [653.3, 662.1] | 0.0% | 260.3 | 223.6 | 180.1 | 43.5 | 629.1 | 233.9 |
| 2. Netted, uncollateralised | 509.4 [506.0, 512.9] | 22.5% | 191.5 | 160.8 | 117.3 | 43.5 | 483.8 | 167.9 |
| 3. Collateralised, not netted | 279.1 [278.6, 279.5] | 57.6% | 121.5 | 99.0 | 87.4 | 11.6 | 267.3 | 109.5 |
| 4. Netted + collateralised | 134.1 [133.9, 134.3] | 79.6% | 54.7 | 43.6 | 33.4 | 10.2 | 127.0 | 47.4 |
<!-- END:xva -->

## 2. Netting

* Netting cuts EPE by <!--v:reductions_vs_gross.netted.EPE_pct|pct-->23.4<!--/v-->% and CVA by
  <!--v:reductions_vs_gross.netted.CVA_pct|pct-->22.5<!--/v-->%. That is
  <!--v:d.netting_benefit_cva|k-->148.3<!--/v-->k of CVA.
* The benefit depends heavily on **time**. In the first year the receiver swaps and the FX forwards offset the
  big pay-fixed swap, so EEPE (a first-year measure) drops from
  <!--v:regimes.gross.EEPE_1y|mm-->6.07<!--/v-->mm to <!--v:regimes.netted.EEPE_1y|mm-->2.51<!--/v-->mm.
  After 5 years only the two pay-fixed swaps (IRS1, IRS3) are left. They point the same way, so there is
  nothing left to net (figure 13).
* For the same reason, peak PFE 99% falls by only
  <!--v:reductions_vs_gross.netted.peak_PFE_0.99_pct|pct-->8.3<!--/v-->%. The tail is driven by large rate moves
  at 4-5 years, which hit the same-direction pay-fixed swaps together.

## 3. Collateral

* A per-trade CSA without netting cuts CVA by <!--v:reductions_vs_gross.collateralised.CVA_pct|pct-->57.6<!--/v-->%.
  Netting plus a netting-set CSA cuts it by
  <!--v:reductions_vs_gross.netted_collateralised.CVA_pct|pct-->79.6<!--/v-->%. The per-trade case is worse
  partly because every trade gets its own 2mm threshold, so 12mm of uncollateralised allowance in total instead
  of 2mm.
* **What is left after collateral** is roughly the threshold plus the value change over the MPoR.
  Without an MPoR (and with other terms at base), EPE is
  <!--v:d.sweep_mpor_steps_0_epe|mm-->1.00<!--/v-->mm and peak PFE 99% is
  <!--v:csa_sweeps.0.peak_PFE_0.99|mm-->2.23<!--/v-->mm, close to the 2mm threshold. Once there is any MPoR, the
  peak PFE 99% jumps to <!--v:csa_sweeps.1.peak_PFE_0.99|mm-->12.81<!--/v-->mm.
* **Cashflow spikes.** That jump is the FX forward settling at 2y. On the settlement date its value drops out of
  the portfolio, but collateral is frozen at its level of one MPoR earlier. For a short time the collateral
  backing the forward no longer matches anything. The model assumes both parties still pay trade cashflows
  during the MPoR (close to the "Classic+" convention of Andersen, Pykhtin & Sokol). Other conventions move or
  remove the spike. So *peak* collateralised PFE depends on the convention, while EPE and CVA hardly do.
* **Two-way vs one-way CSA.** If only the client posts, EPE is
  <!--v:csa_variants.one_way_cpty_posts_only.EPE|mm-->1.01<!--/v-->mm against
  <!--v:csa_variants.base_two_way.EPE|mm-->1.03<!--/v-->mm for the two-way CSA. The one-way CSA is lower
  because collateral **we** post is itself at risk during the MPoR. The test suite checks both that a
  one-way CSA never increases exposure on any path and that a two-way CSA can.
* **Independent amount.** Holding a 5mm IA from the client takes CVA down to
  <!--v:csa_variants.base_plus_IA_5mm.CVA|k-->0.6<!--/v-->k. Peak PFE 99% is still
  <!--v:csa_variants.base_plus_IA_5mm.peak_PFE_0.99|mm-->8.14<!--/v-->mm, because the cashflow spike is bigger
  than the IA.

### CSA sweeps

<!-- BEGIN:csa_sweeps -->
| CSA parameter | Value | EPE (mm) | Peak PFE 99% (mm) | CVA (k) |
|---|---:|---:|---:|---:|
| mpor_steps | 0 | 1.00 | 2.23 | 129.1 |
| mpor_steps | 1 | 1.01 | 12.81 | 130.7 |
| mpor_steps | 2 | 1.03 | 13.14 | 134.1 |
| mpor_steps | 4 | 1.10 | 13.39 | 143.0 |
| mpor_steps | 8 | 1.23 | 14.20 | 161.2 |
| cpty_threshold_mm | 0 | 0.42 | 13.53 | 56.9 |
| cpty_threshold_mm | 1 | 0.66 | 13.06 | 86.4 |
| cpty_threshold_mm | 2 | 1.03 | 13.14 | 134.1 |
| cpty_threshold_mm | 5 | 2.07 | 14.36 | 271.0 |
| cpty_threshold_mm | 10 | 3.11 | 16.74 | 410.0 |
| cpty_threshold_mm | 20 | 3.77 | 21.12 | 499.4 |
| cpty_threshold_mm | 50 | 3.84 | 28.22 | 509.4 |
| mta_mm | 0 | 1.03 | 13.13 | 134.1 |
| mta_mm | 0.25 | 1.03 | 13.14 | 134.1 |
| mta_mm | 0.5 | 1.04 | 13.13 | 134.4 |
| mta_mm | 1 | 1.04 | 13.14 | 135.7 |
| mta_mm | 2 | 1.07 | 13.25 | 139.3 |
| mta_mm | 5 | 1.29 | 13.81 | 172.1 |
| margin_freq_steps | 1 | 1.03 | 13.14 | 134.1 |
| margin_freq_steps | 2 | 1.05 | 13.19 | 136.6 |
| margin_freq_steps | 4 | 1.09 | 13.39 | 141.9 |
| margin_freq_steps | 12 | 1.24 | 14.30 | 161.4 |
| settlement_lag_steps | 0 | 1.03 | 13.14 | 134.1 |
| settlement_lag_steps | 1 | 1.06 | 13.30 | 138.4 |
| settlement_lag_steps | 2 | 1.10 | 13.39 | 143.0 |
| independent_amount_mm | 0 | 1.03 | 13.14 | 134.1 |
| independent_amount_mm | 2.5 | 0.10 | 10.64 | 13.6 |
| independent_amount_mm | 5 | 0.01 | 8.14 | 0.6 |
| independent_amount_mm | 10 | 0.00 | 3.14 | 0.1 |
<!-- END:csa_sweeps -->

The MTA has almost no effect until it gets close to the threshold. Going from 0 to 2mm changes CVA from
<!--v:d.sweep_mta_mm_0_cva|k-->134.1<!--/v-->k to <!--v:d.sweep_mta_mm_2_cva|k-->139.3<!--/v-->k. A 5mm MTA raises it to
<!--v:d.sweep_mta_mm_5_cva|k-->172.1<!--/v-->k. Less frequent margining and a settlement lag both work like a
longer MPoR, because they make collateral older on average at the time of default.

## 4. DVA and bilateral CVA

* DVA (<!--v:regimes.netted.DVA.value|k-->191.5<!--/v-->k netted) is smaller than CVA for two reasons: our
  synthetic credit spread is lower, and the netting set is net in-the-money to us today. In the first-to-default
  ("bilateral") version, CVA falls to <!--v:regimes.netted.CVA_bilateral.value|k-->483.8<!--/v-->k because the client's
  default only costs us if we have not defaulted first.

## 5. FVA

* With **equal** borrowing and lending spreads (60bp), FVA = FCA - FBA = $s\sum_k \mathbb{E}[D\,V(t_k)]\,S_CS_B\,\Delta t$.
  That is linear in the netting-set value, so **netting cannot change it**. Gross and netted FVA are both
  <!--v:regimes.gross.FVA.value|k-->43.5<!--/v-->k. FCA alone does fall with netting, from
  <!--v:regimes.gross.FCA.value|k-->223.6<!--/v-->k to <!--v:regimes.netted.FCA.value|k-->160.8<!--/v-->k. This is why
  practitioners usually use asymmetric spreads, or report FCA only, to avoid overlap with DVA.
* Collateral cuts FVA because collateralised exposure needs no funding in this simple model. It assumes
  collateral received can be reused (rehypothecated) and earns nothing extra, and it ignores the cost of
  funding initial margin (MVA).

## 6. Wrong-way risk

<!-- BEGIN:wwr -->
| Regime | beta | CVA (k) +/- 1.96 SE | CVA / independent | Peak EE given default (mm) | Peak PFE 99% given default (mm) |
|---|---:|---:|---:|---:|---:|
| netted | -1.00 | 144.8 +/- 0.2 | 0.28x | 1.80 | 18.87 |
| netted | -0.50 | 289.1 +/- 0.9 | 0.57x | 3.47 | 23.49 |
| netted | -0.25 | 390.5 +/- 1.9 | 0.77x | 4.65 | 25.79 |
| netted | +0.00 | 509.4 +/- 3.4 | 1.00x | 6.05 | 28.23 |
| netted | +0.25 | 641.9 +/- 5.7 | 1.26x | 7.60 | 30.09 |
| netted | +0.50 | 782.7 +/- 8.8 | 1.54x | 9.23 | 31.86 |
| netted | +0.75 | 925.5 +/- 12.3 | 1.82x | 10.88 | 33.32 |
| netted | +1.00 | 1,063.6 +/- 16.0 | 2.09x | 12.48 | 34.33 |
| netted_collateralised | -1.00 | 37.1 +/- 0.1 | 0.28x | 0.62 | 8.41 |
| netted_collateralised | -0.50 | 77.1 +/- 0.1 | 0.58x | 1.48 | 10.94 |
| netted_collateralised | -0.25 | 104.0 +/- 0.1 | 0.78x | 2.08 | 12.02 |
| netted_collateralised | +0.00 | 134.1 +/- 0.2 | 1.00x | 2.78 | 13.14 |
| netted_collateralised | +0.25 | 165.8 +/- 0.2 | 1.24x | 3.56 | 14.04 |
| netted_collateralised | +0.50 | 197.5 +/- 0.3 | 1.47x | 4.40 | 14.72 |
| netted_collateralised | +0.75 | 227.9 +/- 0.4 | 1.70x | 5.28 | 15.53 |
| netted_collateralised | +1.00 | 255.9 +/- 0.5 | 1.91x | 6.17 | 16.42 |
<!-- END:wwr -->

* At every beta the calibration keeps the average default probability in each bucket equal to the CDS curve
  to within about 1e-16 (`max_abs_PD_calibration_error` in `results/wrong_way_risk.csv`). The changes in CVA
  above therefore come purely from the dependence.
* Moderate wrong-way risk (beta = 0.5) multiplies CVA by <!--v:d.wwr_netted_b+0p50_ratio|x-->1.54<!--/v-->x
  uncollateralised. Strong (beta = 1) gives <!--v:d.wwr_netted_b+1p00_ratio|x-->2.09<!--/v-->x. Right-way risk
  (beta = -0.5) gives <!--v:d.wwr_netted_b-0p50_ratio|x-->0.57<!--/v-->x.
* Collateral lowers the CVA *level* a lot, but the *multiplier* stays similar
  (<!--v:d.wwr_netted_collateralised_b+0p50_ratio|x-->1.47<!--/v-->x and
  <!--v:d.wwr_netted_collateralised_b+1p00_ratio|x-->1.91<!--/v-->x collateralised). The exposure left after
  collateral (threshold plus MPoR moves) is still largest on the paths where the portfolio value is high, so it
  stays correlated with the hazard rate.
* PFE **conditional on default** rises with beta. Its peak 99% level goes from
  <!--v:d.wwr_netted_b+0p00_cond_pfe99|mm-->28.23<!--/v-->mm (independent) to
  <!--v:d.wwr_netted_b+0p50_cond_pfe99|mm-->31.86<!--/v-->mm at beta = 0.5. The unconditional PFE does not
  change, because WWR changes *which* paths are likely to default, not the paths themselves.
* This mechanism is a deliberately simple stand-in. Beta is not estimated from data, and the dependence works
  through the whole portfolio value rather than through a specific market factor.

## 7. Sensitivities

<!-- BEGIN:sensitivity -->
| Driver | Value | CVA netted (k) | CVA netted + collateralised (k) |
|---|---:|---:|---:|
| hazard_multiplier | 0 | 0.0 | 0.0 |
| hazard_multiplier | 0.25 | 139.0 | 36.8 |
| hazard_multiplier | 0.5 | 269.9 | 71.3 |
| hazard_multiplier | 1 | 509.4 | 134.1 |
| hazard_multiplier | 1.5 | 722.0 | 189.5 |
| hazard_multiplier | 2 | 910.6 | 238.4 |
| hazard_multiplier | 3 | 1,226.5 | 319.9 |
| hazard_multiplier | 4 | 1,475.2 | 383.9 |
| LGD | 0 | 0.0 | 0.0 |
| LGD | 0.2 | 169.8 | 44.7 |
| LGD | 0.4 | 339.6 | 89.4 |
| LGD | 0.6 | 509.4 | 134.1 |
| LGD | 0.8 | 679.2 | 178.8 |
| LGD | 1 | 849.0 | 223.5 |
| rates_vol | 25bp | 205.5 | 119.8 |
| rates_vol | 50bp | 300.9 | 124.5 |
| rates_vol | 75bp | 404.2 | 128.9 |
| rates_vol | 100bp | 510.6 | 133.9 |
| rates_vol | 125bp | 618.6 | 139.9 |
| rates_vol | 150bp | 727.3 | 147.3 |
<!-- END:sensitivity -->

* **LGD:** CVA is exactly linear in LGD when the hazard rate is held fixed. In practice, hazard rates implied
  from CDS spreads depend on the recovery assumption ($\lambda \approx s/(1-R)$), which partly cancels this.
* **Hazard rate:** CVA increases but less than proportionally. Multiplying all hazard rates by 4 multiplies
  CVA by <!--v:d.cva_hazard_x4_ratio|x-->2.90<!--/v-->x, because the survival probability, and so the chance of
  defaulting later, shrinks.
* **Rate volatility:** going from 25bp to 150bp Hull-White sigma multiplies uncollateralised CVA by
  <!--v:d.vol_ratio_n|x-->3.54<!--/v-->x but collateralised CVA by only <!--v:d.vol_ratio_nc|x-->1.23<!--/v-->x.
  Collateral removes most of the dependence on volatility. What remains is mostly the threshold, which does
  not depend on volatility, plus the MPoR moves, which do.

## 8. Monte Carlo quality

<!-- BEGIN:convergence -->
| Paths | Antithetic | CVA (k) | Std. error (k) | 95% CI (k) | EPE (mm) | Runtime (s) |
|---:|:---:|---:|---:|---:|---:|---:|
| 500 | yes | 516.5 | 10.7 | [495.6, 537.5] | 3.90 | 0.23 |
| 500 | no | 534.9 | 21.4 | [493.0, 576.7] | 4.02 | 0.26 |
| 1,000 | yes | 502.8 | 7.4 | [488.3, 517.3] | 3.78 | 0.32 |
| 1,000 | no | 516.6 | 15.8 | [485.6, 547.6] | 3.91 | 0.29 |
| 2,000 | yes | 506.6 | 5.6 | [495.6, 517.6] | 3.82 | 0.44 |
| 2,000 | no | 516.1 | 11.0 | [494.5, 537.7] | 3.89 | 0.48 |
| 4,000 | yes | 508.3 | 3.9 | [500.6, 516.0] | 3.83 | 0.79 |
| 4,000 | no | 514.4 | 7.8 | [499.0, 529.8] | 3.88 | 0.77 |
| 8,000 | yes | 508.6 | 2.7 | [503.3, 514.0] | 3.83 | 1.44 |
| 8,000 | no | 515.3 | 5.5 | [504.4, 526.2] | 3.89 | 1.48 |
| 16,000 | yes | 509.6 | 2.0 | [505.8, 513.5] | 3.84 | 3.44 |
| 16,000 | no | 514.1 | 3.9 | [506.4, 521.8] | 3.87 | 3.83 |
| 32,000 | yes | 509.0 | 1.4 | [506.3, 511.7] | 3.84 | 13.88 |
| 32,000 | no | 513.6 | 2.8 | [508.1, 519.0] | 3.87 | 10.85 |
<!-- END:convergence -->

<!-- BEGIN:diagnostics -->
| Check | Result |
|---|---|
| max relative error of E[D(0,t)] vs P(0,t) over all dates | 8.0e-05 (max abs z-score 1.84) |
| FX forward deflated-value martingale error at 1y | 541 DOM on 44.00mm notional (z = 0.18) |
| Par forward-start swap MtM today | 0.00 DOM |
| Variance reduction (plain / antithetic variance, CVA, 32,000 paths) | 4.02x |
| Variance reduction (EPE) | 3.56x |
| Seed replication: 40 seeds x 2,000 paths - empirical std of CVA vs mean reported SE | 5.4k vs 5.5k |
| Seed replication: share of 95% CIs covering the 128,000-path reference | 92.5% |
| Reference netted CVA (128,000 paths) | 511.3k +/- 1.4k |
<!-- END:diagnostics -->

* Standard errors fall at the expected $1/\sqrt{N}$ rate (figure 11). Antithetic variates cut CVA variance by
  <!--v:variance_reduction.CVA_variance_ratio_plain_over_antithetic|x-->4.02<!--/v-->x at essentially no cost
  (runtime ratio <!--v:variance_reduction.runtime_ratio_antithetic_over_plain|x-->1.28<!--/v-->x, since only half
  as many random numbers are drawn).
* The confidence intervals are honest. Across 40 independent seeds, the spread of CVA estimates
  (<!--v:seed_replication.empirical_std|k-->5.4<!--/v-->k) matches the average reported standard error
  (<!--v:seed_replication.mean_reported_se|k-->5.5<!--/v-->k), and <!--v:d.seed_cov_pct|pct-->92.5<!--/v-->% of the
  95% intervals cover the high-precision reference. With 40 trials, the sampling error on that coverage
  figure is about 3.4 points, so this is consistent with the nominal 95%.
* At the base run size the 95% CI half-width for netted CVA is
  <!--v:d.cva_rel_ci_netted_pct|pct-->0.7<!--/v-->% of the estimate.

## 9. Runtime

<!-- BEGIN:runtime -->
| Stage (base run, 20,000 paths x 481 dates x 6 trades) | Seconds |
|---|---:|
| Scenario simulation (rates, discount factors, FX) | 0.36 |
| Re-valuation of all trades on all paths and dates | 3.57 |
| Netting, 7 CSA simulations (6 per-trade + 1 netted), exposure stats, PFE bootstrap CIs, XVA for 4 regimes | 7.96 |
| Whole experiment (all sweeps, WWR, convergence) | 223.64 |
<!-- END:runtime -->

Re-valuation grows linearly with paths x dates x remaining cashflows. The swap valuation is vectorised across
paths but loops over dates in Python. The collateral simulation is path-dependent (MTA, lag), so it loops over
dates too. A production engine would use AAD for sensitivities, compiled kernels and regression-based pricing
for products without closed forms. None of that is needed for this product set.
