from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger

from src.application.common import FileDownloader, Interactor
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.application.use_cases.importer.dto import ExportedUserDto
from src.application.use_cases.importer.queries.filters import SplitExportedUsers
from src.application.use_cases.importer.queries.xui import ExportUsersFromXui


def _safe_tmp_path(directory: str, file_name: str) -> Path:
    safe_name = Path(file_name).name or "import.json"
    return Path(directory) / safe_name


@dataclass(frozen=True)
class ProcessImportFileDto:
    file_id: str
    file_name: str


@dataclass(frozen=True)
class ProcessImportFileResultDto:
    all_users: list[ExportedUserDto]
    active_users: list[ExportedUserDto]
    expired_users: list[ExportedUserDto]


class ProcessImportFile(Interactor[ProcessImportFileDto, ProcessImportFileResultDto]):
    required_permission = Permission.IMPORTER

    def __init__(
        self,
        export_users_from_xui: ExportUsersFromXui,
        split_exported_users: SplitExportedUsers,
        file_downloader: FileDownloader,
    ) -> None:
        self.export_users_from_xui = export_users_from_xui
        self.split_exported_users = split_exported_users
        self.file_downloader = file_downloader

    async def _execute(
        self,
        actor: UserDto,
        data: ProcessImportFileDto,
    ) -> ProcessImportFileResultDto:
        # A private random directory prevents filename collisions and symlink
        # attacks when multiple admins import identically named files.
        with TemporaryDirectory(prefix="remnashop_import_") as temp_directory:
            local_file_path = _safe_tmp_path(temp_directory, data.file_name)
            await self.file_downloader.download_to_path(data.file_id, local_file_path)
            logger.info(f"{actor.log} Downloaded file for processing: '{local_file_path}'")

            users = await self.export_users_from_xui(actor, local_file_path)

            if not users:
                return ProcessImportFileResultDto([], [], [])

            active, expired = await self.split_exported_users(actor, users)

            return ProcessImportFileResultDto(
                all_users=users,
                active_users=active,
                expired_users=expired,
            )
