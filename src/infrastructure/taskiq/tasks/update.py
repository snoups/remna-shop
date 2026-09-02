from typing import Final

import orjson
from adaptix import Retort
from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from packaging.version import InvalidVersion, Version
from redis.asyncio import Redis

from src.__version__ import __version__
from src.application.common import EventPublisher
from src.application.events import BotUpdateEvent
from src.core.config import AppConfig
from src.infrastructure.redis.keys import LatestNotifiedVersionKey
from src.infrastructure.taskiq.broker import broker

GITHUB_RELEASE_URL: Final[str] = "https://api.github.com/repos/snoups/remnashop/releases/latest"


def _parse_version_tag(value: str) -> tuple[str, Version] | None:
    normalized = value.removeprefix("v")
    try:
        return normalized, Version(normalized)
    except InvalidVersion:
        return None


def _resolve_local_version(build_tag: str) -> tuple[str, Version] | None:
    parsed = _parse_version_tag(build_tag)
    if parsed is not None:
        return parsed

    fallback = _parse_version_tag(__version__)
    if fallback is None:
        logger.warning("Local build tag and application version are invalid, skipping update check")
        return None

    logger.warning(
        "Local build tag is not a valid version, falling back to application version: "
        f"'{build_tag}' -> '{fallback[0]}'"
    )
    return fallback


@broker.task(schedule=[{"cron": "0 * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def check_bot_update(
    config: FromDishka[AppConfig],
    retort: FromDishka[Retort],
    redis: FromDishka[Redis],
    event_publisher: FromDishka[EventPublisher],
) -> None:
    if not config.build.tag or config.build.tag == "dev":
        logger.debug("Local version is a development build, skipping update check")
        return

    parsed_local = _resolve_local_version(config.build.tag)
    if parsed_local is None:
        return
    local_version, lv = parsed_local

    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=10.0,
                pool=5.0,
            )
        ) as client:
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = await client.get(GITHUB_RELEASE_URL, headers=headers)
            response.raise_for_status()

            data = orjson.loads(response.content)
            remote_tag = data.get("tag_name", "")

            if not remote_tag:
                logger.error("Remote version tag not found in GitHub API response")
                return
    except httpx.ConnectError as e:
        logger.warning(f"Failed to reach GitHub API (network issue): '{e}'")
        return
    except httpx.TimeoutException as e:
        logger.warning(f"GitHub API request timed out: '{e}'")
        return
    except httpx.HTTPStatusError as e:
        logger.warning(f"GitHub API returned error status: '{e}'")
        return

    parsed_remote = _parse_version_tag(remote_tag)
    if parsed_remote is None:
        logger.warning(
            f"Remote release tag is not a valid version, skipping update check: '{remote_tag}'"
        )
        return
    remote_version, rv = parsed_remote

    if rv <= lv:
        status = "up to date" if rv == lv else "ahead of remote"
        logger.debug(f"Project is '{status}': '{local_version}'")
        return

    key = retort.dump(LatestNotifiedVersionKey(version="*"))
    last_notified_version = await redis.get(key)

    logger.debug(
        f"Update check: key='{key}', cached={last_notified_version!r}, remote={remote_version!r}"
    )

    if last_notified_version == remote_version:
        logger.debug(f"Version '{remote_version}' already notified")
        return

    await redis.set(key, value=remote_version)
    logger.info(f"New version available: '{remote_version}' (local: '{local_version}')")

    event = BotUpdateEvent(local_version=local_version, remote_version=remote_version)
    await event_publisher.publish(event)
