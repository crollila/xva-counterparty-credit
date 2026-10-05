"""Variation-margin (CSA) collateral simulation with a margin period of risk.

Timeline on each path (all on the simulation grid):

1. Margin call dates t_m occur every `margin_freq_steps` steps.
2. At a call date the required collateral (positive = held by us) is

       C_req = max(V - TH_cpty, 0) - max(-V - TH_own, 0)

   and a transfer is made only if |C_req - C_balance| >= MTA.
3. The transfer settles `settlement_lag_steps` later (collateral lag).
4. If the counterparty defaults at t, it stopped posting at t - MPoR: the
   collateral available at close-out is the balance settled by t - MPoR.

   Collateralised MtM:     V(t) - C(t - MPoR) - IA_received
   Positive exposure:      max(V(t) - C(t - MPoR) - IA_received, 0)

An independent amount (IA / static initial margin) received from the
counterparty is held on top of VM and is assumed segregated (never
rehypothecated), so it reduces our positive exposure but posting our own IA
does not create negative exposure. A one-way CSA (only the counterparty
posts) is obtained with `own_threshold=inf`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CSA:
    cpty_threshold: float = 0.0  # TH above which the counterparty must post
    own_threshold: float = 0.0  # TH above which we must post (inf => one-way CSA)
    mta: float = 0.0  # minimum transfer amount
    independent_amount: float = 0.0  # IA received from counterparty (static IM)
    margin_freq_steps: int = 1  # VM call every n grid steps
    mpor_steps: int = 2  # margin period of risk in grid steps
    settlement_lag_steps: int = 0  # call-to-settlement lag in grid steps

    def label(self) -> str:
        return (
            f"TH={self.cpty_threshold:,.0f} MTA={self.mta:,.0f} IA={self.independent_amount:,.0f} "
            f"freq={self.margin_freq_steps} MPoR={self.mpor_steps} lag={self.settlement_lag_steps}"
        )


def collateral_balance(V: np.ndarray, csa: CSA) -> np.ndarray:
    """Settled VM collateral balance C(t) held by us (negative = posted by us).

    V: (n_t, n_paths) netting-set MtM. Returns array of the same shape.
    """
    n_t, n = V.shape
    bal = np.zeros((n_t, n))
    agreed = np.zeros(n)  # balance after the last agreed call
    pending = {}  # settle index -> transfer amount array
    current = np.zeros(n)
    for k in range(n_t):
        if k in pending:
            current = current + pending.pop(k)
        if k % csa.margin_freq_steps == 0:
            v = V[k]
            req = np.maximum(v - csa.cpty_threshold, 0.0) - np.maximum(-v - csa.own_threshold, 0.0)
            if k == 0:
                # Seasoned CSA: today's balance already reflects today's MtM.
                agreed = req.copy()
                current = req.copy()
                bal[k] = current
                continue
            delta = req - agreed
            delta = np.where(np.abs(delta) >= csa.mta, delta, 0.0)
            # A zero MTA would still move tiny amounts; that is intended.
            agreed = agreed + delta
            if csa.settlement_lag_steps == 0:
                current = current + delta
            else:
                s = k + csa.settlement_lag_steps
                pending[s] = pending.get(s, 0.0) + delta
        bal[k] = current
    return bal


def collateralised_mtm(V: np.ndarray, csa: CSA) -> np.ndarray:
    """V(t) - C(t - MPoR) - IA. The collateral used is lagged by MPoR."""
    bal = collateral_balance(V, csa)
    m = csa.mpor_steps
    lagged = bal.copy()
    if m > 0:
        lagged[m:] = bal[:-m]
        lagged[:m] = bal[0]  # before t = MPoR the frozen balance is today's
    out = V - lagged
    pos = np.maximum(out - csa.independent_amount, 0.0)
    neg = np.minimum(out, 0.0)
    # Recombine so that max(.,0) gives IA-reduced positive exposure and
    # min(.,0) gives negative exposure unaffected by our own posted IA.
    return np.where(out > 0, pos, neg)
