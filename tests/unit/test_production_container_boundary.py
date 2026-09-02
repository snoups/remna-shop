from pathlib import Path

import pytest

COMPOSE_FILES = (
    "docker-compose.prod.internal.yml",
    "docker-compose.prod.external.yml",
    "docker-compose.local.yml",
)


def _service_lines(name: str, service_name: str) -> set[str]:
    lines = Path(name).read_text(encoding="utf-8").splitlines()
    marker = f"  {service_name}:"
    start = lines.index(marker) + 1
    service_lines: set[str] = set()
    for line in lines[start:]:
        if line.strip() and not line.startswith("    "):
            break
        service_lines.add(line.strip())
    return service_lines


def test_application_entrypoint_does_not_run_database_migrations() -> None:
    entrypoint = Path("docker-entrypoint.sh").read_text(encoding="utf-8")
    migration = Path("docker-migrate.sh").read_text(encoding="utf-8")

    assert "alembic" not in entrypoint
    assert "alembic -c src/infrastructure/database/alembic.ini upgrade head" in migration


def test_production_services_wait_for_one_shot_migration() -> None:
    for name in ("docker-compose.prod.internal.yml", "docker-compose.prod.external.yml"):
        compose = Path(name).read_text(encoding="utf-8")
        assert "remnashop-migration:" in compose
        assert 'restart: "no"' in compose
        assert 'command: ["./docker-migrate.sh"]' in compose
        assert compose.count("condition: service_completed_successfully") == 3


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_runtime_services_define_graceful_shutdown_contract(name: str) -> None:
    assert {
        "init: true",
        "stop_signal: SIGTERM",
        "stop_grace_period: 2m",
    } <= _service_lines(name, "remnashop")
    assert {
        "init: true",
        "stop_signal: SIGTERM",
        "stop_grace_period: 10m",
    } <= _service_lines(name, "remnashop-taskiq-worker")
    assert {
        "init: true",
        "stop_signal: SIGINT",
        "stop_grace_period: 30s",
    } <= _service_lines(name, "remnashop-taskiq-scheduler")
