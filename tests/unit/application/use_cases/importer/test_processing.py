from pathlib import Path

from src.application.use_cases.importer.commands.processing import _safe_tmp_path


def test_import_path_stays_inside_private_directory(tmp_path: Path) -> None:
    result = _safe_tmp_path(str(tmp_path), "../../shared-name.json")

    assert result.parent == tmp_path
    assert result.name == "shared-name.json"
