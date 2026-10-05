"""Joint Monte Carlo simulation of future market states.

Risk factors (all simulated under the domestic risk-neutral measure, bank
account numeraire):

* x(t)   - Hull-White state of the domestic short rate
* D(0,t) - stochastic discount factor exp(-int_0^t r(s) ds), simulated exactly
           together with x via the joint Gaussian transition of (x, int x)
* S(t)   - FX spot (domestic per unit of foreign), lognormal with drift
           r_d(t) - r_f, where r_f is a deterministic foreign rate

Time is a uniform grid of `steps_per_year` steps per year (default 48, i.e.
~1.1 weeks). Product schedules are built on the same grid so that every reset
and payment date is a simulation date.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .hull_white import HullWhite1F


@dataclass(frozen=True)
class TimeGrid:
    horizon_years: float
    steps_per_year: int = 48

    @property
    def n_steps(self) -> int:
        return int(round(self.horizon_years * self.steps_per_year))

    @property
    def dt(self) -> float:
        return 1.0 / self.steps_per_year

    @property
    def times(self) -> np.ndarray:
        return np.arange(self.n_steps + 1) * self.dt

    def index(self, t: float) -> int:
        k = t * self.steps_per_year
        ik = int(round(k))
        if abs(k - ik) > 1e-9:
            raise ValueError(f"time {t} is not on the simulation grid")
        return ik


@dataclass(frozen=True)
class FXModel:
    spot: float
    vol: float
    foreign_rate: float  # deterministic, continuously compounded
    corr_rates_fx: float = 0.0

    def foreign_discount(self, t, T):
        return np.exp(-self.foreign_rate * (np.asarray(T, dtype=float) - t))


@dataclass
class Scenarios:
    grid: TimeGrid
    model: HullWhite1F
    fx_model: FXModel | None
    x: np.ndarray  # (n_t, n_paths)
    D: np.ndarray  # (n_t, n_paths) stochastic discount factor to time 0
    fx: np.ndarray | None  # (n_t, n_paths)
    antithetic: bool
    seed: int
    meta: dict = field(default_factory=dict)

    @property
    def times(self) -> np.ndarray:
        return self.grid.times

    @property
    def n_paths(self) -> int:
        return self.x.shape[1]


def simulate(
    model: HullWhite1F,
    grid: TimeGrid,
    n_paths: int,
    seed: int,
    fx_model: FXModel | None = None,
    antithetic: bool = True,
) -> Scenarios:
    """Simulate (x, D, S) on the grid with a deterministic seed.

    With `antithetic=True` the first n/2 paths use normals Z and the second n/2
    use -Z, so path i and path i + n/2 form an antithetic pair.
    """
    if antithetic and n_paths % 2:
        raise ValueError("antithetic simulation needs an even path count")
    rng = np.random.default_rng(seed)
    n_t = grid.n_steps + 1
    dt = grid.dt
    times = grid.times
    n_draw = n_paths // 2 if antithetic else n_paths

    decay, mI, vx, vI, cxi = model.step_moments(dt)
    sx = np.sqrt(vx)
    if sx > 0:
        lI1 = cxi / sx
        lI2 = np.sqrt(max(vI - lI1 * lI1, 0.0))
    else:
        lI1 = lI2 = 0.0

    # Deterministic part of int r over each step: int phi.
    lnP = np.log(model.curve.discount(times))
    V0 = model.V(0.0, times)
    int_phi = (lnP[:-1] - lnP[1:]) + 0.5 * (V0[1:] - V0[:-1])

    x = np.zeros((n_t, n_paths))
    D = np.ones((n_t, n_paths))
    fx = None
    if fx_model is not None:
        fx = np.empty((n_t, n_paths))
        fx[0] = fx_model.spot
        lnS = np.full(n_paths, np.log(fx_model.spot))
        rho = fx_model.corr_rates_fx
        sv = fx_model.vol
        fx_drift_const = (-fx_model.foreign_rate - 0.5 * sv * sv) * dt
        fx_shock = sv * np.sqrt(dt)

    for k in range(n_t - 1):
        z = rng.standard_normal((n_draw, 3))
        if antithetic:
            z = np.concatenate([z, -z], axis=0)
        z1, z2, z3 = z[:, 0], z[:, 1], z[:, 2]
        xk = x[k]
        I = mI * xk + lI1 * z1 + lI2 * z2
        x[k + 1] = decay * xk + sx * z1
        int_r = I + int_phi[k]
        D[k + 1] = D[k] * np.exp(-int_r)
        if fx is not None:
            zf = rho * z1 + np.sqrt(1.0 - rho * rho) * z3
            lnS = lnS + int_r + fx_drift_const + fx_shock * zf
            fx[k + 1] = np.exp(lnS)

    return Scenarios(grid, model, fx_model, x, D, fx, antithetic, seed)
