"""Deterministic initial discount curves.

Every curve in this project is SYNTHETIC. Nothing here is calibrated to market
quotes; the shapes are chosen to look like a plausible upward-sloping curve so
that the exposure machinery has something realistic-looking to work on.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FlatCurve:
    """Continuously compounded flat zero curve: P(0,T) = exp(-r T)."""

    rate: float

    def zero_rate(self, t):
        return np.full_like(np.asarray(t, dtype=float), self.rate)

    def discount(self, t):
        return np.exp(-self.rate * np.asarray(t, dtype=float))

    def inst_forward(self, t):
        return np.full_like(np.asarray(t, dtype=float), self.rate)


@dataclass(frozen=True)
class NelsonSiegelCurve:
    """Nelson-Siegel continuously compounded zero curve.

    z(T) = b0 + b1 * (1 - e^{-T/tau}) / (T/tau) + b2 * [(1 - e^{-T/tau}) / (T/tau) - e^{-T/tau}]

    With b1 < 0 the curve slopes upward from b0 + b1 at the short end to b0
    at the long end.
    """

    b0: float = 0.040
    b1: float = -0.010
    b2: float = 0.005
    tau: float = 2.0

    def zero_rate(self, t):
        t = np.maximum(np.asarray(t, dtype=float), 1e-10)
        x = t / self.tau
        f1 = (1.0 - np.exp(-x)) / x
        f2 = f1 - np.exp(-x)
        return self.b0 + self.b1 * f1 + self.b2 * f2

    def discount(self, t):
        t = np.asarray(t, dtype=float)
        return np.exp(-self.zero_rate(t) * t)

    def inst_forward(self, t):
        # f(0,T) = d/dT [z(T) T]; closed form for Nelson-Siegel.
        t = np.asarray(t, dtype=float)
        x = t / self.tau
        e = np.exp(-x)
        return self.b0 + self.b1 * e + self.b2 * x * e
