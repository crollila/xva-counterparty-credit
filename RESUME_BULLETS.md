# Resume bullets

*(The numbers are generated from `results/summary.json` and reconciled by CI. The portfolio is simulated and
the methodology is simplified and educational. Say so when you quote them.)*

**xva-counterparty-credit - Monte Carlo counterparty exposure & XVA engine (Python, NumPy/SciPy)**

- Built a Monte Carlo counterparty-exposure engine: an exact-transition Hull-White 1F rates model with a
  stochastic discount factor, plus correlated lognormal FX. It re-prices a simulated IRS / FX-forward netting
  set on <!--v:config.n_paths|i-->20,000<!--/v--> paths x 481 dates to produce EE, ENE, EPE, EEPE and PFE
  (90-99%) profiles with Monte Carlo and bootstrap confidence intervals.
- Implemented discretised unilateral and first-to-default CVA, DVA and a simplified FCA/FBA funding adjustment
  from CDS-implied piecewise hazard curves. Showed that netting plus a two-way CSA (threshold, MTA, IA, margin
  frequency, settlement lag, margin period of risk) cuts CVA by
  <!--v:reductions_vs_gross.netted_collateralised.CVA_pct|pct-->79.6<!--/v-->% against gross uncollateralised.
- Modelled wrong-way risk with an exposure-linked stochastic hazard re-calibrated each step to keep marginal
  default probabilities equal to the CDS curve (error below 1e-14). Measured a
  <!--v:d.wwr_netted_b+0p50_ratio|x-->1.54<!--/v-->x CVA uplift at beta = 0.5 and higher PFE conditional on default.
- Validated with 36 tests: limiting cases (zero hazard, LGD or exposure), closed-form deterministic fixtures,
  martingale and PFE-quantile checks, netting identities, and collateral-monotonicity fixtures.
  Antithetic variates gave a <!--v:variance_reduction.CVA_variance_ratio_plain_over_antithetic|x-->4.02<!--/v-->x
  variance reduction. A 40-seed study confirmed CI calibration
  (<!--v:d.seed_cov_pct|pct-->92.5<!--/v-->% coverage).
- Shipped a reproducible one-command pipeline (tests, experiment, 13 figures, auto-generated docs) with CI that
  checks every reported number in the README against the results file.
