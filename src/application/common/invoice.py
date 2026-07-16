from src.application.common.translator import TranslatorRunner
from src.application.dto.plan import PlanSnapshotDto
from src.core.enums import PurchaseType
from src.core.utils.i18n_helpers import i18n_format_days


def build_invoice_description(
    i18n: TranslatorRunner,
    purchase_type: PurchaseType,
    plan_snapshot: PlanSnapshotDto,
) -> str:
    """Render the human-readable payment description shown on the invoice/receipt."""
    key, kw = i18n_format_days(plan_snapshot.duration)
    return i18n.get(
        "payment-invoice-description",
        purchase_type=purchase_type,
        name=i18n.get(plan_snapshot.name),
        duration=i18n.get(key, **kw),
    )
