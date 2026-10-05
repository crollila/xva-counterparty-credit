"""Portfolio instruments re-valued on every simulated path and date.

Convention: the mark-to-market V(t) at a grid date t EXCLUDES any cashflow
paid at t (the exposure is measured just after payment). This produces the
characteristic saw-tooth exposure profile of a swap.

Values are from OUR (the bank's) perspective: V > 0 means the counterparty
owes us, so we are exposed to its default.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .simulation import Scenarios


def _schedule(start: float, maturity: float, freq: int) -> np.ndarray:
    n = int(round((maturity - start) * freq))
    if n <= 0 or abs(start + n / freq - maturity) > 1e-9:
        raise ValueError("maturity - start must be a whole number of periods")
    return start + np.arange(1, n + 1) / freq


@dataclass(frozen=True)
class InterestRateSwap:
    """Single-curve vanilla IRS: fixed leg vs floating (simple-compounded) leg."""

    name: str
    notional: float
    fixed_rate: float
    maturity: float
    pay_fixed: bool = True
    start: float = 0.0
    fixed_freq: int = 2
    float_freq: int = 4

    @property
    def fixed_dates(self) -> np.ndarray:
        return _schedule(self.start, self.maturity, self.fixed_freq)

    @property
    def float_dates(self) -> np.ndarray:
        return _schedule(self.start, self.maturity, self.float_freq)

    def par_rate(self, curve) -> float:
        P = curve.discount
        ann = np.sum(P(self.fixed_dates)) / self.fixed_freq
        return float((P(self.start) - P(self.maturity)) / ann)

    def mtm(self, scen: Scenarios) -> np.ndarray:
        grid, model = scen.grid, scen.model
        times = grid.times
        out = np.zeros((len(times), scen.n_paths))
        fixed = self.fixed_dates
        flt = self.float_dates
        flt_starts = np.concatenate([[self.start], flt[:-1]])
        tau_f = 1.0 / self.fixed_freq
        fixing_factor = None  # 1 / P(T_{i-1}, T_i) of the current float period
        sign = 1.0 if self.pay_fixed else -1.0
        for k, t in enumerate(times):
            if t >= self.maturity - 1e-12:
                break
            xk = scen.x[k]
            rem_fixed = fixed[fixed > t + 1e-12]
            fixed_pv = self.fixed_rate * tau_f * model.bond(t, rem_fixed, xk).sum(axis=1)
            P_mat = model.bond(t, self.maturity, xk)
            if t < self.start - 1e-12:
                float_pv = model.bond(t, self.start, xk) - P_mat
            else:
                i = int(np.searchsorted(flt, t + 1e-12, side="left"))  # current period pays flt[i]
                if abs(t - flt_starts[i]) < 1e-12:  # reset date: fix the coupon
                    fixing_factor = 1.0 / model.bond(t, flt[i], xk)
                float_pv = fixing_factor * model.bond(t, flt[i], xk) - P_mat
            out[k] = sign * self.notional * (float_pv - fixed_pv)
        return out


@dataclass(frozen=True)
class FXForward:
    """Buy (long=True) `notional_foreign` units of foreign currency at strike K at T."""

    name: str
    notional_foreign: float
    strike: float
    maturity: float
    long: bool = True

    def mtm(self, scen: Scenarios) -> np.ndarray:
        if scen.fx is None or scen.fx_model is None:
            raise ValueError("FX forward needs an FX simulation")
        times = scen.grid.times
        out = np.zeros((len(times), scen.n_paths))
        sign = 1.0 if self.long else -1.0
        for k, t in enumerate(times):
            if t >= self.maturity - 1e-12:
                break
            Pd = scen.model.bond(t, self.maturity, scen.x[k])
            Pf = scen.fx_model.foreign_discount(t, self.maturity)
            out[k] = sign * self.notional_foreign * (scen.fx[k] * Pf - self.strike * Pd)
        return out

    def forward_rate(self, fx_model, curve) -> float:
        return float(fx_model.spot * fx_model.foreign_discount(0.0, self.maturity) / curve.discount(self.maturity))
