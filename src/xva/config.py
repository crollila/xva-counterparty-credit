"""Base experiment configuration.

EVERYTHING HERE IS SIMULATED / SYNTHETIC. The curve, volatilities, CDS
spreads, notionals and trades are illustrative inputs chosen to produce a
realistic-looking netting set; they are not market data and not a real
book. Amounts are in units of a generic domestic currency ("DOM").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .collateral import CSA
from .credit import CreditParty, HazardCurve
from .curves import NelsonSiegelCurve
from .hull_white import HullWhite1F
from .instruments import FXForward, InterestRateSwap
from .simulation import FXModel, TimeGrid

MM = 1_000_000.0
BP = 1e-4


@dataclass
class ExperimentConfig:
    seed: int = 20261004
    n_paths: int = 20_000
    antithetic: bool = True
    steps_per_year: int = 48  # ~1.1 weeks; MPoR of 2 steps ~ 10.5 business days
    horizon: float = 10.0

    # --- synthetic market ---
    curve: NelsonSiegelCurve = field(default_factory=lambda: NelsonSiegelCurve(0.040, -0.010, 0.005, 2.0))
    hw_a: float = 0.03
    hw_sigma: float = 0.0100  # 100bp/yr normal short-rate vol
    fx_spot: float = 1.10
    fx_vol: float = 0.10
    foreign_rate: float = 0.025
    corr_rates_fx: float = -0.25

    # --- synthetic credit (CDS spreads -> credit-triangle hazards) ---
    cds_tenors: tuple = (1.0, 3.0, 5.0, 7.0, 10.0)
    cpty_cds_bp: tuple = (100.0, 130.0, 160.0, 175.0, 190.0)
    cpty_recovery: float = 0.40
    own_cds_bp: tuple = (50.0, 60.0, 70.0, 80.0, 90.0)
    own_recovery: float = 0.40
    funding_spread_borrow: float = 60 * BP
    funding_spread_lend: float = 60 * BP

    # --- base CSA (two-way) ---
    csa: CSA = field(
        default_factory=lambda: CSA(
            cpty_threshold=2 * MM,
            own_threshold=2 * MM,
            mta=0.25 * MM,
            independent_amount=0.0,
            margin_freq_steps=1,
            mpor_steps=2,
            settlement_lag_steps=0,
        )
    )

    @property
    def grid(self) -> TimeGrid:
        return TimeGrid(self.horizon, self.steps_per_year)

    @property
    def model(self) -> HullWhite1F:
        return HullWhite1F(self.hw_a, self.hw_sigma, self.curve)

    @property
    def fx_model(self) -> FXModel:
        return FXModel(self.fx_spot, self.fx_vol, self.foreign_rate, self.corr_rates_fx)

    @property
    def counterparty(self) -> CreditParty:
        hz = HazardCurve.from_cds_spreads(self.cds_tenors, [s * BP for s in self.cpty_cds_bp], self.cpty_recovery)
        return CreditParty("Counterparty C (synthetic)", hz, self.cpty_recovery)

    @property
    def own(self) -> CreditParty:
        hz = HazardCurve.from_cds_spreads(self.cds_tenors, [s * BP for s in self.own_cds_bp], self.own_recovery)
        return CreditParty("Bank B (us, synthetic)", hz, self.own_recovery)

    def portfolio(self) -> list:
        """SIMULATED netting set with one counterparty. Fixed rates/strikes are
        set relative to today's par/forward so some trades start in/out of the money."""
        c = self.curve
        fx = self.fx_model

        def irs(name, notional, maturity, pay_fixed, offset_bp, start=0.0):
            proto = InterestRateSwap(name, notional, 0.0, maturity, pay_fixed, start)
            par = proto.par_rate(c)
            return InterestRateSwap(name, notional, par + offset_bp * BP, maturity, pay_fixed, start)

        def fwd(name, notional_for, maturity, long, strike_mult):
            proto = FXForward(name, notional_for, 0.0, maturity, long)
            return FXForward(name, notional_for, proto.forward_rate(fx, c) * strike_mult, maturity, long)

        return [
            irs("IRS1 pay-fixed 10Y", 100 * MM, 10.0, True, -20),
            irs("IRS2 rec-fixed 5Y", 60 * MM, 5.0, False, +10),
            irs("IRS3 pay-fixed 1Yx7Y fwd-start", 50 * MM, 8.0, True, 0, start=1.0),
            irs("IRS4 rec-fixed 3Y", 40 * MM, 3.0, False, -15),
            fwd("FXF1 buy FOR 2Y", 40 * MM, 2.0, True, 1.00),
            fwd("FXF2 sell FOR 1Y", 25 * MM, 1.0, False, 0.98),
        ]
