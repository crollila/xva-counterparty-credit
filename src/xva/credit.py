"""Reduced-form (intensity) credit model for the counterparty and for ourselves.

Default time tau is the first jump of a Poisson process with deterministic,
piecewise-constant hazard rate lambda(t):

    S(t)            = P(tau > t) = exp(-int_0^t lambda(u) du)
    PD(t_{k-1},t_k) = S(t_{k-1}) - S(t_k)          (marginal default probability)
    LGD             = 1 - recovery
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class HazardCurve:
    """Piecewise-constant hazard. rates[i] applies on (knots[i-1], knots[i]];
    the last rate is extrapolated flat beyond the last knot."""

    knots: tuple
    rates: tuple

    def __post_init__(self):
        if len(self.knots) != len(self.rates) or not self.knots:
            raise ValueError("knots and rates must be non-empty and equal length")
        if any(r < 0 for r in self.rates):
            raise ValueError("hazard rates must be non-negative")
        if any(b <= a for a, b in zip(self.knots, self.knots[1:])):
            raise ValueError("knots must be increasing")

    @classmethod
    def flat(cls, rate: float) -> "HazardCurve":
        return cls((1.0,), (rate,))

    @classmethod
    def from_cds_spreads(cls, tenors, spreads, recovery: float) -> "HazardCurve":
        """'Credit triangle' approximation: average hazard to tenor T_i is
        s_i / (1 - R); bucket hazards are bootstrapped from the averages.
        This is an approximation, not a full CDS bootstrap (no premium-leg
        accrual or discounting)."""
        tenors = np.asarray(tenors, dtype=float)
        avg = np.asarray(spreads, dtype=float) / (1.0 - recovery)
        H = avg * tenors
        dH = np.diff(np.concatenate([[0.0], H]))
        dT = np.diff(np.concatenate([[0.0], tenors]))
        rates = dH / dT
        if np.any(rates < 0):
            raise ValueError("spread curve implies negative forward hazard")
        return cls(tuple(tenors), tuple(rates))

    def scaled(self, mult: float) -> "HazardCurve":
        return replace(self, rates=tuple(r * mult for r in self.rates))

    def integrated(self, t) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        knots = np.asarray(self.knots)
        rates = np.asarray(self.rates)
        starts = np.concatenate([[0.0], knots[:-1]])
        widths = np.clip(t[..., None] - starts, 0.0, None)
        caps = np.concatenate([knots - starts, [np.inf]])[:-1]
        caps[-1] = np.inf  # last bucket extends flat
        return np.sum(rates * np.minimum(widths, caps), axis=-1)

    def hazard(self, t) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        idx = np.searchsorted(np.asarray(self.knots), t, side="left")
        idx = np.minimum(idx, len(self.rates) - 1)
        return np.asarray(self.rates)[idx]

    def survival(self, t) -> np.ndarray:
        return np.exp(-self.integrated(t))

    def marginal_pd(self, times) -> np.ndarray:
        """PD over each grid interval: length len(times) - 1."""
        S = self.survival(times)
        return S[:-1] - S[1:]


@dataclass(frozen=True)
class CreditParty:
    name: str
    hazard: HazardCurve
    recovery: float

    @property
    def lgd(self) -> float:
        return 1.0 - self.recovery

    def with_(self, **kw) -> "CreditParty":
        return replace(self, **kw)
