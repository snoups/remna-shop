from enum import auto
from typing import Final

from src.application.dto import UserDto
from src.core.enums import Role, UpperStrEnum


class PermissionPolicy:
    @staticmethod
    def has_permission(actor: UserDto, permission: "Permission") -> bool:
        if permission is Permission.PUBLIC:
            return True

        if actor.role == Role.SYSTEM:
            return True

        permissions = ROLE_PERMISSIONS.get(actor.role, set())
        return permission in permissions


class Permission(UpperStrEnum):
    PUBLIC = auto()
    COMMAND_TEST = auto()
    USER_SEARCH = auto()
    MANAGE_ADMINS = auto()
    BROADCAST = auto()
    #
    VIEW_DASHBOARD = auto()
    VIEW_STATISTICS = auto()
    VIEW_USERS = auto()
    VIEW_BROADCAST = auto()
    VIEW_PROMOCODE = auto()
    MANAGE_PROMOCODE = auto()
    VIEW_ACCESS = auto()
    VIEW_REMNAWAVE = auto()
    VIEW_REMNASHOP = auto()
    VIEW_IMPORTER = auto()
    VIEW_ADMINS = auto()
    VIEW_GATEWAYS = auto()
    VIEW_REFERRAL = auto()
    VIEW_ADVERTISING = auto()
    VIEW_PLANS = auto()
    VIEW_NOTIFICATIONS = auto()
    VIEW_LOGS = auto()
    VIEW_AUDIT = auto()
    VIEW_MENU_EDITOR = auto()
    VIEW_BACKUP = auto()
    VIEW_EXTRA_SETTINGS = auto()
    VIEW_BLACKLIST = auto()
    #
    SETTINGS_REFERRAL = auto()
    SETTINGS_NOTIFICATIONS = auto()
    SETTINGS_REQUIREMENT = auto()
    SETTINGS_ACCESS = auto()
    SETTINGS_MENU = auto()
    SETTINGS_CURRENCY = auto()
    SETTINGS_BACKUP = auto()
    SETTINGS_EXTRA = auto()
    #
    REMNASHOP_GATEWAYS = auto()
    REMNASHOP_PLAN_EDITOR = auto()
    REMNASHOP_LOGS = auto()
    #
    USER_EDITOR = auto()
    USER_SUBSCRIPTION_EDITOR = auto()
    USER_SYNC = auto()
    USER_MERGE = auto()
    #
    IMPORTER = auto()
    ASSIGN_ROLE = auto()
    REVOKE_ROLE = auto()
    UNBLOCK_ALL = auto()
    BLACKLIST = auto()


ROLE_PERMISSIONS: Final[dict[Role, set[Permission]]] = {
    Role.SYSTEM: set(Permission),
    Role.OWNER: set(Permission),
    Role.DEV: set(Permission),
    Role.ADMIN: {
        # View
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_USERS,
        Permission.VIEW_PROMOCODE,
        Permission.MANAGE_PROMOCODE,
        Permission.VIEW_ACCESS,
        # Actions
        Permission.SETTINGS_ACCESS,
        Permission.USER_SEARCH,
        Permission.USER_EDITOR,
        Permission.USER_SUBSCRIPTION_EDITOR,
        Permission.USER_SYNC,
    },
    Role.PREVIEW: {  # TODO: Implement demo Bot instance
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_STATISTICS,
        Permission.VIEW_USERS,
        Permission.VIEW_BROADCAST,
        Permission.VIEW_PROMOCODE,
        Permission.VIEW_ACCESS,
        Permission.VIEW_REMNAWAVE,
        Permission.VIEW_REMNASHOP,
        Permission.VIEW_GATEWAYS,
        Permission.VIEW_REFERRAL,
        Permission.VIEW_ADVERTISING,
        Permission.VIEW_PLANS,
        Permission.VIEW_NOTIFICATIONS,
        Permission.VIEW_LOGS,
        Permission.VIEW_MENU_EDITOR,
        Permission.USER_SEARCH,
    },
    Role.USER: set(),
}
