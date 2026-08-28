from typing import Optional

from aiogram.fsm.state import State, StatesGroup


class MainMenu(StatesGroup):
    MAIN = State()
    DEVICES = State()
    DEVICE_CONFIRM_DELETE = State()
    DEVICE_CONFIRM_DELETE_ALL = State()
    DEVICE_CONFIRM_REISSUE = State()
    INVITE = State()
    INVITE_ABOUT = State()


class Notification(StatesGroup):
    CLOSE = State()


class Subscription(StatesGroup):
    MAIN = State()
    PROMOCODE = State()
    PLAN = State()
    PLANS = State()
    DURATION = State()
    PAYMENT_METHOD = State()
    CONFIRM = State()
    SUCCESS = State()
    FAILED = State()
    TRIAL = State()


class Dashboard(StatesGroup):
    MAIN = State()


class DashboardStatistics(StatesGroup):
    MAIN = State()
    USERS = State()
    SUBSCRIPTIONS = State()
    TRANSACTIONS = State()
    PROMOCODES = State()
    PROMOCODE_DETAIL = State()
    REFERRALS = State()


class DashboardBroadcast(StatesGroup):
    MAIN = State()
    LIST = State()
    VIEW = State()
    PLAN = State()
    SEND = State()
    CONTENT = State()
    BUTTONS = State()


class DashboardPromocodes(StatesGroup):
    MAIN = State()
    LIST = State()
    CONFIGURATOR = State()
    CODE = State()
    TYPE = State()
    AVAILABILITY = State()
    REWARD = State()
    PLAN = State()
    PLAN_DURATION = State()
    EXPIRES = State()
    MAX_ACTIVATIONS = State()


class DashboardAccess(StatesGroup):
    MAIN = State()
    CONDITIONS = State()
    RULES = State()
    CHANNEL = State()


class DashboardUsers(StatesGroup):
    MAIN = State()
    SEARCH = State()
    SEARCH_RESULTS = State()
    RECENT_REGISTERED = State()
    RECENT_ACTIVITY = State()
    BLACKLIST = State()
    BLACKLIST_USERS = State()
    BLACKLIST_BLOCK = State()
    BLACKLIST_SOURCES = State()


class DashboardUser(StatesGroup):
    MAIN = State()
    SUBSCRIPTION = State()
    TRAFFIC_LIMIT = State()
    DEVICE_LIMIT = State()
    EXPIRE_TIME = State()
    SQUADS = State()
    INTERNAL_SQUADS = State()
    EXTERNAL_SQUADS = State()
    DEVICES_LIST = State()
    DISCOUNT = State()
    PERSONAL_DISCOUNT = State()
    PURCHASE_DISCOUNT = State()
    POINTS = State()
    STATISTICS = State()
    REFERRALS = State()
    ROLE = State()
    TRANSACTIONS_LIST = State()
    TRANSACTION = State()
    GIVE_ACCESS = State()
    MESSAGE = State()
    SYNC = State()
    SYNC_WAITING = State()
    GIVE_SUBSCRIPTION = State()
    SUBSCRIPTION_DURATION = State()


class DashboardRemnashop(StatesGroup):
    MAIN = State()
    ADMINS = State()
    ADVERTISING = State()
    TRANSACTIONS = State()


class RemnashopBackup(StatesGroup):
    MAIN = State()
    INTERVAL = State()
    MAX_FILES = State()


class RemnashopExtra(StatesGroup):
    MAIN = State()
    DEVICE_SINGLE = State()
    DEVICE_ALL = State()
    LINK_RESET = State()
    REFERRAL_RESET = State()
    TRIAL_CHANNEL_GUARD = State()
    MINI_APP_RESERVE = State()
    STARS_PAID_REQUIREMENT = State()


class RemnashopGrace(StatesGroup):
    MAIN = State()
    TRAFFIC_INPUT = State()
    DURATION_INPUT = State()
    TAG_INPUT = State()
    STRATEGY = State()
    INTERNAL_SQUADS = State()
    EXTERNAL_SQUAD = State()


class RemnashopReferral(StatesGroup):
    MAIN = State()
    LEVEL = State()
    REWARD = State()
    REWARD_TYPE = State()
    ACCRUAL_STRATEGY = State()
    REWARD_STRATEGY = State()


class RemnashopAdvertising(StatesGroup):
    MAIN = State()
    CONFIGURATOR = State()
    NAME = State()
    CODE = State()
    STATS = State()


class RemnashopGateways(StatesGroup):
    MAIN = State()
    SETTINGS = State()
    FIELD = State()
    CURRENCY = State()
    PLACEMENT = State()


class RemnashopNotifications(StatesGroup):
    MAIN = State()
    USER = State()
    SYSTEM = State()
    SYSTEM_TYPE = State()
    SYSTEM_ROUTE = State()
    SYSTEM_ROUTE_CHAT_ID = State()
    SYSTEM_ROUTE_THREAD_ID = State()
    SYSTEM_DEFAULT_ROUTE = State()
    SYSTEM_DEFAULT_ROUTE_CHAT_ID = State()
    SYSTEM_DEFAULT_ROUTE_THREAD_ID = State()


class RemnashopPlans(StatesGroup):
    MAIN = State()
    IMPORT = State()
    EXPORT = State()
    CONFIGURATOR = State()
    NAME = State()
    DESCRIPTION = State()
    TAG = State()
    TYPE = State()
    AVAILABILITY = State()
    TRAFFIC = State()
    DEVICES = State()
    DURATIONS = State()
    DURATION_ADD = State()
    PRICES = State()
    PRICE = State()
    ALLOWED = State()
    SQUADS = State()
    INTERNAL_SQUADS = State()
    EXTERNAL_SQUADS = State()


class RemnashopMenuEditor(StatesGroup):
    MAIN = State()
    BUTTON = State()
    TEXT = State()
    AVAILABILITY = State()
    TYPE = State()
    PAYLOAD = State()
    COLOR = State()


class DashboardRemnawave(StatesGroup):
    MAIN = State()
    USERS = State()
    HOSTS = State()
    NODES = State()
    INBOUNDS = State()


class DashboardImporter(StatesGroup):
    MAIN = State()
    FROM_XUI = State()
    SYNC = State()
    SQUADS = State()
    IMPORT_COMPLETED = State()
    SYNC_PANEL = State()
    SYNC_PANEL_COMPLETED = State()
    SYNC_BOT = State()
    SYNC_BOT_COMPLETED = State()


def state_from_string(state_str: str, sep: Optional[str] = ":") -> Optional[State]:
    try:
        group_name, state_name = state_str.split(":")[:2]
        group_cls = globals().get(group_name)
        if group_cls is None:
            return None
        state_obj = getattr(group_cls, state_name, None)
        if not isinstance(state_obj, State):
            return None
        return state_obj
    except (ValueError, AttributeError):
        return None
