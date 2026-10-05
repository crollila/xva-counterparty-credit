"""Monte Carlo statistics that respect antithetic pairing.

With antithetic variates, path i and path i + n/2 are NOT independent, so a
naive standard error over all n paths is wrong. We first average each pair
(giving n/2 i.i.d. samples) and compute the standard error over pairs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Z95 = 1.959963984540054


def pair_reduce(a: np.ndarray, antithetic: bool) -> np.ndarray:
    """Average antithetic pairs along the LAST axis."""
    if not antithetic:
        return a
    h = a.shape[-1] // 2
    return 0.5 * (a[..., :h] + a[..., h:])


@dataclass(frozen=True)
class Estimate:
    value: float
    se: float
    n_samples: int  # independent samples (pairs if antithetic)

    @property
    def lo(self) -> float:
        return self.value - Z95 * self.se

    @property
    def hi(self) -> float:
        return self.value + Z95 * self.se

    def as_dict(self) -> dict:
        return {"value": self.value, "se": self.se, "ci95_lo": self.lo, "ci95_hi": self.hi, "n_iid": self.n_samples}


def mean_estimate(per_path: np.ndarray, antithetic: bool) -> Estimate:
    s = pair_reduce(np.asarray(per_path, dtype=float), antithetic)
    n = s.shape[-1]
    se = float(np.std(s, ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return Estimate(float(np.mean(s)), se, n)


def bootstrap_quantile_ci(x: np.ndarray, q: float, antithetic: bool, n_boot: int = 400, seed: int = 7):
    """Percentile-bootstrap 95% CI for the q-quantile of x, resampling
    antithetic PAIRS together so the dependence inside a pair is kept."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    if antithetic:
        h = x.size // 2
        pairs = np.stack([x[:h], x[h:]], axis=1)
        idx = rng.integers(0, h, size=(n_boot, h))
        samples = pairs[idx].reshape(n_boot, -1)
    else:
        idx = rng.integers(0, x.size, size=(n_boot, x.size))
        samples = x[idx]
    qs = np.quantile(samples, q, axis=1)
    return float(np.quantile(qs, 0.025)), float(np.quantile(qs, 0.975))
