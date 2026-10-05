"""Wrong-way risk via an exposure-linked stochastic hazard rate.

A transparent, simplified version of the Hull & White (2012) idea: on each
path the counterparty's hazard over (t_{k-1}, t_k] is

    lambda_k(omega) = c_k * exp(beta * Z_k(omega)),
    Z_k = (V_k - mean(V_k)) / std(V_k)     (standardised netting-set MtM)

* beta > 0  -> the counterparty becomes riskier exactly when we are owed
               more: WRONG-way risk.
* beta < 0  -> RIGHT-way risk.  beta = 0 reproduces the independent case.

c_k is solved numerically at every step so that the UNCONDITIONAL marginal
default probabilities equal those of the input hazard curve:

    E[ S_{k-1}(omega) (1 - exp(-lambda_k(omega) dt)) ] = S(t_{k-1}) - S(t_k)

so the term structure of credit risk (the 'CDS curve') is unchanged and any
difference in CVA is due to the dependence alone.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from .credit import HazardCurve


def standardise(V: np.ndarray) -> np.ndarray:
    mu = V.mean(axis=1, keepdims=True)
    sd = V.std(axis=1, keepdims=True)
    ok = sd > 1e-12
    return np.where(ok, (V - mu) / np.where(ok, sd, 1.0), 0.0)


def wwr_default_probs(times: np.ndarray, V: np.ndarray, hazard: HazardCurve, beta: float) -> np.ndarray:
    """Per-path marginal default probabilities, shape (n_t - 1, n_paths)."""
    Z = standardise(V)
    target = hazard.marginal_pd(times)
    n_t, n = V.shape
    S_prev = np.ones(n)
    out = np.empty((n_t - 1, n))
    for k in range(1, n_t):
        dt = times[k] - times[k - 1]
        m = np.exp(beta * Z[k])
        tgt = target[k - 1]
        if tgt <= 0:
            out[k - 1] = 0.0
            continue

        def f(c):
            return np.mean(S_prev * (1.0 - np.exp(-c * m * dt))) - tgt

        hi = max(hazard.hazard(times[k]) * 2.0, 1e-6)
        while f(hi) < 0:
            hi *= 4.0
            if hi > 1e6:
                raise RuntimeError("could not bracket WWR calibration")
        c = brentq(f, 0.0, hi, xtol=1e-14, rtol=1e-12)
        pd = S_prev * (1.0 - np.exp(-c * m * dt))
        out[k - 1] = pd
        S_prev = S_prev - pd
    return out


def conditional_exposure(PE: np.ndarray, pd_paths: np.ndarray, q: float | None = None) -> np.ndarray:
    """Exposure distribution CONDITIONAL on default in each interval.

    Weights each path by its default probability in (t_{k-1}, t_k]. Returns the
    conditional EE (q=None) or conditional q-quantile (PFE) per interval end."""
    X = PE[1:]
    w = pd_paths
    tot = w.sum(axis=1, keepdims=True)
    tot = np.where(tot > 0, tot, 1.0)
    if q is None:
        return (X * w).sum(axis=1) / tot[:, 0]
    out = np.empty(X.shape[0])
    for k in range(X.shape[0]):
        order = np.argsort(X[k])
        cw = np.cumsum(w[k, order]) / tot[k, 0]
        j = min(np.searchsorted(cw, q, side="left"), len(order) - 1)
        out[k] = X[k, order[j]]
    return out
