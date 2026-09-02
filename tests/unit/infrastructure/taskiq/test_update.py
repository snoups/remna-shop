from packaging.version import Version

from src.infrastructure.taskiq.tasks.update import _parse_version_tag, _resolve_local_version


def test_parse_version_tag_accepts_release_prefix() -> None:
    assert _parse_version_tag("v0.8.3") == ("0.8.3", Version("0.8.3"))


def test_parse_version_tag_rejects_docker_image_tag() -> None:
    assert _parse_version_tag("clean-pay-prod-27a6d80") is None


def test_resolve_local_version_falls_back_to_application_version() -> None:
    assert _resolve_local_version("clean-pay-prod-27a6d80") == ("0.8.3", Version("0.8.3"))
