import gzip
import logging
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.core import logger as logger_module
from src.core.logger import (
    LOG_FILENAME,
    ConcurrentRetentionRotatingFileHandler,
    _parse_duration,
    _parse_size,
    sanitize_log_text,
    setup_logger,
)


def _write_concurrent_log_records(path: str, worker_id: int) -> None:
    handler = ConcurrentRetentionRotatingFileHandler(
        Path(path),
        max_bytes=512,
        retention_seconds=60 * 60,
        use_gzip=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    for record_id in range(80):
        handler.emit(
            logging.LogRecord(
                name="concurrency-test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg=f"worker={worker_id} record={record_id}",
                args=(),
                exc_info=None,
            )
        )
    handler.close()


def test_sanitize_log_text_redacts_email_and_credentials() -> None:
    message = (
        "delivery to person@example.com failed; "
        "password=hunter2 token='abc.def' Authorization: Bearer bearer-secret "
        'signature="signed-value"'
    )

    sanitized = sanitize_log_text(message)

    assert "person@example.com" not in sanitized
    assert "hunter2" not in sanitized
    assert "abc.def" not in sanitized
    assert "bearer-secret" not in sanitized
    assert "signed-value" not in sanitized
    assert sanitized.count("[REDACTED]") >= 4


def test_sanitize_log_text_keeps_human_readable_context() -> None:
    assert sanitize_log_text("Payment processing failed for gateway yookassa") == (
        "Payment processing failed for gateway yookassa"
    )


def test_log_size_and_retention_defaults_are_parsed() -> None:
    assert _parse_size("100 MB") == 100_000_000
    assert _parse_duration("3 days") == 3 * 24 * 60 * 60


def test_setup_logger_keeps_single_multiprocess_safe_bot_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    added_sinks: list[object] = []
    monkeypatch.setattr(logger_module, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_module.logger, "remove", Mock())
    monkeypatch.setattr(
        logger_module.logger,
        "add",
        lambda sink, **_: added_sinks.append(sink),
    )
    monkeypatch.setattr(logger_module.logging, "basicConfig", Mock())
    config = SimpleNamespace(
        log=SimpleNamespace(
            to_file=True,
            level="DEBUG",
            rotation="100 MB",
            retention="3 days",
            compression="zip",
        )
    )

    setup_logger(config)

    file_sinks = [
        sink
        for sink in added_sinks
        if isinstance(sink, ConcurrentRetentionRotatingFileHandler)
    ]
    assert len(file_sinks) == 1
    assert Path(file_sinks[0].baseFilename) == tmp_path / LOG_FILENAME
    file_sinks[0].close()


def test_concurrent_rotation_preserves_every_record_in_one_log(tmp_path: Path) -> None:
    log_path = tmp_path / LOG_FILENAME
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_write_concurrent_log_records, args=(str(log_path), worker_id))
        for worker_id in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    records: set[str] = set()
    for candidate in tmp_path.glob(f"{LOG_FILENAME}*"):
        if not candidate.is_file() or candidate.suffix == ".lock":
            continue
        if candidate.suffix == ".gz":
            with gzip.open(candidate, mode="rt", encoding="utf-8") as archive:
                records.update(archive.read().splitlines())
        else:
            records.update(candidate.read_text(encoding="utf-8").splitlines())
    expected = {
        f"worker={worker_id} record={record_id}"
        for worker_id in range(4)
        for record_id in range(80)
    }
    assert records == expected
