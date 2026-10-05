"""Exposure analytics from a matrix of simulated mark-to-market values.

Notation (V = MtM from our side on one path at time t):
    PE(t)  = max(V(t), 0)         positive exposure: what we lose if cpty defaults
    NE(t)  = min(V(t), 0)         negative exposure: what the cpty loses if WE default
    EE(t)  = E[PE(t)]             expected exposure
    ENE(t) = E[NE(t)]             expected negative exposure (<= 0)
    PFE_q(t) = q-quantile of PE(t)  potential future exposure
    EPE    = (1/T) int_0^T EE(t) dt   time-averaged EE
    EEPE   = Basel 'effective EPE': average over the first year of the
             running maximum of EE ('effective EE')

EE/ENE/PFE are reported undiscounted (future-value exposure). The
discounted versions EE*(t) = E[D(0,t) PE(t)] feed CVA/DVA/FVA.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .stats import Estimate, mean_estimate, pair_reduce

DEFAULT_QUANTILES = (0.90, 0.95, 0.975, 0.99)


def _trapz_avg(y: np.ndarray, t: np.ndarray, axis: int = 0) -> np.ndarray:
    if t[-1] <= 0:
        return np.take(y, 0, axis=axis)
    return np.trapezoid(y, t, axis=axis) / (t[-1] - t[0])


@dataclass
class ExposureProfile:
    times: np.ndarray
    ee: np.ndarray
    ene: np.ndarray
    ee_disc: np.ndarray
    ene_disc: np.ndarray
    ee_se: np.ndarray
    mean_mtm: np.ndarray
    pfe: dict  # quantile -> array
    epe: Estimate
    ene_avg: Estimate
    eepe_1y: float
    antithetic: bool

    @classmethod
    def from_mtm(cls, times, V, D, antithetic: bool, quantiles=DEFAULT_QUANTILES):
        return cls.from_parts(times, np.maximum(V, 0.0), np.minimum(V, 0.0), D, antithetic, quantiles)

    @classmethod
    def from_parts(cls, times, PE, NE, D, antithetic: bool, quantiles=DEFAULT_QUANTILES):
        """Build from positive/negative exposure arrays (needed for the
        un-netted case, where PE and NE are not the parts of one number).
        NE=None skips the negative side (treated as zero)."""
        times = np.asarray(times)
        skip_ne = NE is None
        if skip_ne:
            NE = np.zeros((len(times), 1))
        ee = PE.mean(axis=1)
        ene = NE.mean(axis=1)
        pe_pairs = pair_reduce(PE, antithetic)
        ee_se = pe_pairs.std(axis=1, ddof=1) / np.sqrt(pe_pairs.shape[1])
        pfe = {q: np.quantile(PE, q, axis=1) for q in quantiles}
        epe_path = _trapz_avg(PE, times, axis=0)
        ene_path = _trapz_avg(NE, times, axis=0)
        one_y = times <= 1.0 + 1e-12
        eff_ee = np.maximum.accumulate(ee[one_y])
        eepe = float(_trapz_avg(eff_ee, times[one_y])) if one_y.sum() > 1 else float(ee[0])
        return cls(
            times=times,
            ee=ee,
            ene=ene,
            ee_disc=(D * PE).mean(axis=1),
            ene_disc=(D * NE).mean(axis=1),
            ee_se=ee_se,
            mean_mtm=(PE + NE).mean(axis=1),
            pfe=pfe,
            epe=mean_estimate(epe_path, antithetic),
            ene_avg=Estimate(0.0, 0.0, 0) if skip_ne else mean_estimate(ene_path, antithetic),
            eepe_1y=eepe,
            antithetic=antithetic,
        )

    def peak_pfe(self, q: float) -> tuple[float, float]:
        k = int(np.argmax(self.pfe[q]))
        return float(self.pfe[q][k]), float(self.times[k])

    def summary(self) -> dict:
        out = {
            "EPE": self.epe.as_dict(),
            "ENE_avg": self.ene_avg.as_dict(),
            "EEPE_1y": self.eepe_1y,
            "peak_EE": float(self.ee.max()),
            "peak_EE_time": float(self.times[int(np.argmax(self.ee))]),
        }
        for q in self.pfe:
            v, t = self.peak_pfe(q)
            out[f"peak_PFE_{q:g}"] = v
            out[f"peak_PFE_{q:g}_time"] = t
        return out


def gross_parts(trade_mtms: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """No netting: PE = sum_i max(V_i, 0) and NE = sum_i min(V_i, 0)."""
    pe = sum(np.maximum(v, 0.0) for v in trade_mtms)
    ne = sum(np.minimum(v, 0.0) for v in trade_mtms)
    return pe, ne


def net_parts(V: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Full netting: PE = max(sum_i V_i, 0), NE = min(sum_i V_i, 0)."""
    return np.maximum(V, 0.0), np.minimum(V, 0.0)
