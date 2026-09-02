from pydantic import BaseModel, Field


class ReferralRewardLevelResponse(BaseModel):
    level: int
    value: int


class ReferralProgramResponse(BaseModel):
    enabled: bool
    referral_code: str
    web_referral_url: str = Field(min_length=1, pattern=r"^https?://")
    invited_count: int
    invited_with_payment_count: int
    points_balance: int
    total_points_issued: int
    total_days_issued: int
    reward_type: str
    reward_strategy: str
    accrual_strategy: str
    max_level: int
    reward_levels: list[ReferralRewardLevelResponse]
