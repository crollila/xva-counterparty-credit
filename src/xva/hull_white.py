"""One-factor Hull-White (G1++) short-rate model fitted to an initial curve.

    r(t) = x(t) + phi(t),     dx = -a x dt + sigma dW,     x(0) = 0

phi(t) is chosen so that the model reproduces the initial discount curve
P^M(0,T) exactly (Brigo & Mercurio, "Interest Rate Models", sec. 3.3). The
zero-coupon bond price at a future date t, given the simulated state x(t), is
available in closed form, which is what makes swap re-valuation along every
Monte Carlo path cheap:

    P(t,T) = P^M(0,T)/P^M(0,t) * exp( 0.5[V(t,T) - V(0,T) + V(0,t)] - B(t,T) x(t) )
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HullWhite1F:
    a: float  # mean reversion speed
    sigma: float  # normal short-rate volatility
    curve: object  # initial curve with .discount(t) and .inst_forward(t)

    def __post_init__(self):
        if self.a <= 0:
            raise ValueError("mean reversion a must be > 0")
        if self.sigma < 0:
            raise ValueError("sigma must be >= 0")

    def B(self, t, T):
        return (1.0 - np.exp(-self.a * (np.asarray(T) - np.asarray(t)))) / self.a

    def V(self, t, T):
        """Variance of int_t^T x(s) ds conditional on x(t)."""
        a, s = self.a, self.sigma
        tau = np.asarray(T, dtype=float) - np.asarray(t, dtype=float)
        return (s * s / (a * a)) * (
            tau + (2.0 / a) * np.exp(-a * tau) - (1.0 / (2.0 * a)) * np.exp(-2.0 * a * tau) - 3.0 / (2.0 * a)
        )

    def bond(self, t: float, T, x):
        """P(t,T) for scalar t, array-like maturities T (k,) and states x (n,).

        Returns shape (n,) if T is scalar else (n, k).
        """
        T = np.asarray(T, dtype=float)
        x = np.asarray(x, dtype=float)
        P0t = self.curve.discount(t)
        P0T = self.curve.discount(T)
        conv = 0.5 * (self.V(t, T) - self.V(0.0, T) + self.V(0.0, t))
        A = (P0T / P0t) * np.exp(conv)
        Bv = self.B(t, T)
        if T.ndim == 0:
            return A * np.exp(-Bv * x)
        return A[None, :] * np.exp(-np.outer(x, Bv))

    def phi(self, t):
        a, s = self.a, self.sigma
        t = np.asarray(t, dtype=float)
        return self.curve.inst_forward(t) + (s * s) / (2 * a * a) * (1 - np.exp(-a * t)) ** 2

    def step_moments(self, dt: float):
        """Exact Gaussian transition of (x_{k+1}, I_k = int x ds) given x_k.

        Returns (decay, mean_I_coef, var_x, var_I, cov_xI):
          x_{k+1} = decay * x_k + eps_x
          I_k     = mean_I_coef * x_k + eps_I
        """
        a, s = self.a, self.sigma
        e1 = np.exp(-a * dt)
        e2 = np.exp(-2 * a * dt)
        var_x = s * s / (2 * a) * (1 - e2)
        var_I = s * s / (a * a) * (dt - 2 * (1 - e1) / a + (1 - e2) / (2 * a))
        cov = s * s / (2 * a * a) * (1 - e1) ** 2
        return e1, (1 - e1) / a, var_x, var_I, cov
