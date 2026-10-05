"""Simplified, discretised XVA charges (educational, not production).

All charges are computed per path and then averaged, so each comes with a
Monte Carlo standard error. On grid t_0 = 0 < t_1 < ... < t_n:

  CVA = LGD_C * sum_k E[D(t_k) PE(t_k)] * PD_C(t_{k-1}, t_k)
        (unilateral: our own default is ignored)
  DVA = LGD_B * sum_k E[D(t_k) |NE(t_k)|] * PD_B(t_{k-1}, t_k)
        (reported as a positive number = benefit to us)
  FCA = sum_k s_borrow * E[D(t_k) PE(t_k)] * S_C(t_k) S_B(t_k) * dt_k
  FBA = sum_k s_lend   * E[D(t_k) |NE(t_k)|] * S_C(t_k) S_B(t_k) * dt_k
  FVA = FCA - FBA   (net funding cost)

Optional 'first-to-default' bilateral variants multiply the CVA term by our
survival S_B(t_k) and the DVA term by S_C(t_k) (independence assumed).

Exposure, default and funding are assumed independent unless a per-path
default-probability matrix is passed (see wwr.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .credit import CreditParty
from .stats import Estimate, mean_estimate


@dataclass
class Charge:
    name: str
    estimate: Estimate
    bucket_contrib: np.ndarray  # contribution of each interval (t_{k-1}, t_k]

    @property
    def value(self) -> float:
        return self.estimate.value

    def as_dict(self) -> dict:
        return {"name": self.name, **self.estimate.as_dict()}


def _charge(name, weights, D, X, antithetic, pd_paths=None) -> Charge:
    """Generic sum_k w_k E[D_k X_k (pd_k)] over k = 1..n with per-path output."""
    DX = D[1:] * X[1:]
    if pd_paths is not None:
        DX = DX * pd_paths
    per_path = np.einsum("k,kn->n", weights, DX)
    buckets = weights * DX.mean(axis=1)
    return Charge(name, mean_estimate(per_path, antithetic), buckets)


def cva(times, PE, D, cpty: CreditParty, antithetic: bool, own: CreditParty | None = None, pd_paths=None) -> Charge:
    """Unilateral CVA (own=None) or first-to-default CVA (own given).

    pd_paths: optional (n-1, n_paths) per-path marginal default probabilities
    replacing the deterministic PD (wrong-way risk)."""
    if pd_paths is None:
        w = cpty.lgd * cpty.hazard.marginal_pd(times)
    else:
        w = np.full(len(times) - 1, cpty.lgd)
    if own is not None:
        w = w * own.hazard.survival(times[1:])
    return _charge("CVA" if own is None else "CVA_bilateral", w, D, PE, antithetic, pd_paths)


def dva(times, NE, D, own: CreditParty, antithetic: bool, cpty: CreditParty | None = None) -> Charge:
    w = own.lgd * own.hazard.marginal_pd(times)
    if cpty is not None:
        w = w * cpty.hazard.survival(times[1:])
    return _charge("DVA" if cpty is None else "DVA_bilateral", w, D, -NE, antithetic)


def fva(times, PE, NE, D, cpty: CreditParty, own: CreditParty, s_borrow: float, s_lend: float, antithetic: bool):
    dt = np.diff(times)
    surv = cpty.hazard.survival(times[1:]) * own.hazard.survival(times[1:])
    fca = _charge("FCA", s_borrow * surv * dt, D, PE, antithetic)
    fba = _charge("FBA", s_lend * surv * dt, D, -NE, antithetic)
    net_w_pe = s_borrow * surv * dt
    net_w_ne = s_lend * surv * dt
    per_path_net = np.einsum("k,kn->n", net_w_pe, D[1:] * PE[1:]) - np.einsum("k,kn->n", net_w_ne, D[1:] * (-NE[1:]))
    fva_net = Charge("FVA", mean_estimate(per_path_net, antithetic), fca.bucket_contrib - fba.bucket_contrib)
    return fca, fba, fva_net
