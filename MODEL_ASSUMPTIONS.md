# Model assumptions and limitations

This is an **educational / research implementation** on a **simulated portfolio**. It is built to make
the mechanics of exposure and XVA clear and testable. Below is every material simplification, so that no result
is mistaken for a production number.

## Data

* **Everything is synthetic.** The initial curve is a Nelson-Siegel curve with chosen parameters. The FX spot,
  volatilities and correlation are chosen, not calibrated. The CDS spreads for "Counterparty C" and "Bank B" are
  made up. Trades and notionals are invented, with fixed rates set relative to today's par rates. The currency
  "DOM" is fictional.
* There is no market calibration. The Hull-White parameters (a = 3%, sigma = 100bp) and FX vol (10%) are not
  fitted to swaption or FX option prices.

## Market model

* **Rates:** one-factor Hull-White (G1++), so all rates move together and the curve cannot twist. There is
  a single curve for discounting and projection (no OIS/IBOR basis), no negative-rate floors, and no smile.
* **FX:** lognormal with **deterministic** foreign rates and constant vol. The drift uses the simulated domestic
  short rate, so the discounted FX forward is a martingale (tested). The correlation is applied between the
  rate-state shock and the FX shock over each step.
* **Measure:** everything is under the domestic risk-neutral measure with bank-account numeraire. PFE is a
  quantile under this pricing measure. A risk-management PFE would normally use a real-world measure.
* **Time grid:** 48 steps per year. All CSA timings (margin frequency, MPoR, settlement lag) are whole numbers
  of steps, so daily margining is approximated by about weekly margining. Business-day calendars, day-count
  conventions and payment lags are ignored (accruals are exact 1/2 and 1/4 years).
* **Cashflow convention:** the value at a grid date excludes cashflows paid on that date.

## Products

* Vanilla single-curve IRS (spot or forward start) and FX forwards only. No optionality, no early exercise, no
  amortisation, no exchange of notional. All trades are priced in closed form on each path, so there is no
  regression (American Monte Carlo) error.

## Credit

* Default is a reduced-form (intensity) model with **deterministic, piecewise-constant hazard rates**, which
  makes default independent of the market unless the WWR module is used.
* Hazard rates come from CDS spreads through the **credit triangle** $\lambda \approx s/(1-R)$ applied bucket by
  bucket. This is an approximation of a full CDS bootstrap: it ignores premium accrual, discounting and the
  upfront convention.
* Recovery is a constant fraction (40%) paid at default. When LGD is varied in the sensitivity analysis, the
  hazard curve is held fixed rather than re-implied from spreads.

## Netting and collateral

* There is one netting set and one CSA. Netting is assumed fully enforceable.
* **Per-trade collateral** in the "collateralised, not netted" regime applies the full CSA terms to each trade
  on its own. That is a stylised comparison, not a real legal arrangement.
* **MPoR model:** the collateral available at default is the balance settled one MPoR earlier. Trade cashflows
  are assumed paid by both sides during the MPoR. That causes exposure spikes when a trade settles. Other
  conventions (for example the client stops paying while we keep paying) give different spike behaviour.
* Thresholds, MTA and IA are constant. There is no rounding, no collateral in other currencies or securities,
  no haircuts, no disputes, and no rating-dependent thresholds.
* The **independent amount** is a static amount held from the client. It is assumed segregated, so it reduces
  our exposure, and IA we post does not create exposure. There is **no dynamic initial margin model**: no
  SIMM, no simulated IM, and no MVA.
* The collateral rate equals the risk-free rate (no collateral-rate spread).

## XVA

* **CVA** is unilateral by default: $LGD\sum_k \mathbb{E}[D\,PE(t_k)]\,PD(t_{k-1},t_k)$, with exposure taken at
  the end of each bucket. The first-to-default variant multiplies by our survival probability and assumes the
  two defaults are independent.
* **DVA** is the mirror image using our own hazard. Whether DVA can be realised in practice, and how it is
  hedged, is not addressed.
* <a id="fva"></a>**FVA** is a simplified symmetric discounting-spread formula:
  FCA = $s_b \sum \mathbb{E}[D\,PE]\,S_C S_B\,\Delta t$ and FBA = $s_l \sum \mathbb{E}[D\,|NE|]\,S_C S_B\,\Delta t$.
  Its limitations:
  * the funding spread is one flat number, not a term structure, and not linked to our own hazard rate;
  * the **FBA and DVA overlap** (both reward our own credit), so adding CVA - DVA + FVA double counts;
  * the exposure being funded is the uncollateralised (or post-collateral) netting-set exposure. It ignores
    rehypothecation limits, the funding of initial margin (MVA), capital (KVA) and tax;
  * with symmetric spreads FVA is linear in the portfolio value, so netting does not change it (see
    ANALYSIS.md);
  * there is no recursive (non-linear) funding valuation of the Burgard-Kjaer or Piterbarg kind.
* There are no CVA sensitivities (no AAD / bump-and-revalue Greeks), no CVA capital (SA-CVA / BA-CVA), and no
  hedging analysis.

## Wrong-way risk

* WWR comes from an exposure-linked hazard rate $\lambda_k = c_k\,e^{\beta Z_k}$, where $Z_k$ is the
  **standardised netting-set value** on the path and $c_k$ is re-solved at every step so the average marginal
  PDs equal the CDS curve. It is a transparent stand-in for the Hull & White (2012) approach.
* Beta is a scenario parameter. It is not estimated. Real WWR sources (credit-FX jumps for sovereigns, specific
  WWR on own-equity trades, collateral-issuer correlation) are not modelled.
* Default is still drawn as a probability per bucket. Exposure paths are not re-simulated after default, so
  contagion and jump-at-default effects are ignored.

## Numerics

* Antithetic variates are the only variance reduction. Standard errors are computed on pair averages, PFE
  confidence intervals come from a pair bootstrap (400 resamples on the full run), and CIs assume a normal
  mean.
* The convergence study uses the netted uncollateralised CVA. Collateralised and WWR estimates have their own
  (smaller) standard errors, which are reported in the tables.
* Results are deterministic for a given seed and NumPy version. Runtimes depend on the machine.
