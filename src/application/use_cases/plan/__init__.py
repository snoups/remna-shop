from typing import Final

from src.application.common import Interactor

from .commands.access import AddAllowedUserToPlan, ToggleUserPlanAccess
from .commands.commit import CommitPlan, CommitPlansBatch
from .commands.durations import AddPlanDuration, RemovePlanDuration
from .commands.edit import (
    UpdatePlanDescription,
    UpdatePlanDevice,
    UpdatePlanName,
    UpdatePlanPrice,
    UpdatePlanTag,
    UpdatePlanTraffic,
    UpdatePlanType,
)
from .commands.order import DeletePlan, MoveDurationUp, MovePlanUp
from .commands.squads import SanitizePlanSquads
from .exchange import ExportPlans, ParsePlansImport
from .queries.match import MatchPlan
from .queries.renewal import GetRenewalPlanContext
from .queries.squads import CheckSquadsAvailable

PLAN_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    AddAllowedUserToPlan,
    AddPlanDuration,
    CommitPlan,
    CommitPlansBatch,
    DeletePlan,
    MovePlanUp,
    RemovePlanDuration,
    UpdatePlanDescription,
    UpdatePlanDevice,
    UpdatePlanName,
    UpdatePlanPrice,
    UpdatePlanTag,
    UpdatePlanTraffic,
    UpdatePlanType,
    ParsePlansImport,
    ExportPlans,
    GetRenewalPlanContext,
    MatchPlan,
    ToggleUserPlanAccess,
    MoveDurationUp,
    CheckSquadsAvailable,
    SanitizePlanSquads,
)
