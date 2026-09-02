from dishka import Provider, Scope, provide_all

from src.application.use_cases.access import ACCESS_USE_CASES
from src.application.use_cases.ad_link import AD_LINK_USE_CASES
from src.application.use_cases.auth import AUTH_USE_CASES
from src.application.use_cases.backup import BACKUP_USE_CASES
from src.application.use_cases.blacklist import BLACKLIST_USE_CASES
from src.application.use_cases.broadcast import BROADCAST_USE_CASES
from src.application.use_cases.gateways import GATEWAYS_USE_CASES
from src.application.use_cases.importer import IMPORTER_USE_CASES
from src.application.use_cases.misc import MISC_USE_CASES
from src.application.use_cases.notification import NOTIFICATION_USE_CASES
from src.application.use_cases.plan import PLAN_USE_CASES
from src.application.use_cases.promocode import PROMOCODE_USE_CASES
from src.application.use_cases.referral import REFERRAL_USE_CASES
from src.application.use_cases.remnawave import REMNAWAVE_USE_CASES
from src.application.use_cases.settings import SETTINGS_USE_CASES
from src.application.use_cases.statistics import STATISTICS_USE_CASES
from src.application.use_cases.subscription import SUBSCRIPTION_USE_CASES
from src.application.use_cases.user import USER_USE_CASES


class UseCasesProvider(Provider):
    scope = Scope.REQUEST

    use_cases = provide_all(
        *ACCESS_USE_CASES,
        *AD_LINK_USE_CASES,
        *AUTH_USE_CASES,
        *BACKUP_USE_CASES,
        *BLACKLIST_USE_CASES,
        *BROADCAST_USE_CASES,
        *GATEWAYS_USE_CASES,
        *IMPORTER_USE_CASES,
        *MISC_USE_CASES,
        *NOTIFICATION_USE_CASES,
        *PLAN_USE_CASES,
        *PROMOCODE_USE_CASES,
        *REFERRAL_USE_CASES,
        *REMNAWAVE_USE_CASES,
        *SETTINGS_USE_CASES,
        *SUBSCRIPTION_USE_CASES,
        *USER_USE_CASES,
        *STATISTICS_USE_CASES,
    )
