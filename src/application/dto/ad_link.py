from dataclasses import dataclass

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class AdLinkDto(BaseDto, TrackableMixin, TimestampMixin):
    name: str = ""
    code: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class AdLinkStatsDto:
    registrations: int
    trials: int
    buyers: int
    trial_buyers: int
    revenue: dict[str, float]
    first_purchase_revenue: dict[str, float]

    @property
    def reg_to_buy_rate(self) -> float:
        if not self.registrations:
            return 0.0
        return round(self.buyers / self.registrations * 100, 1)

    @property
    def trial_to_buy_rate(self) -> float:
        if not self.trials:
            return 0.0
        return round(self.trial_buyers / self.trials * 100, 1)
