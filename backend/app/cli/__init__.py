"""Administrative command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_database
from app.repositories.bootstrap import BootstrapRepository
from app.services.owner import OwnerService
from app.services.seed import SeedConfigurationError, SeedDocument, SeedService

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coffie Bot administrative commands")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="Load validated installation data")
    seed.add_argument("--file", type=Path, required=True)

    create_owner = commands.add_parser("create-owner", help="Create or promote the first owner")
    create_owner.add_argument("--telegram-id", type=int, required=True)
    create_owner.add_argument("--display-name")

    export_settings = commands.add_parser(
        "export-settings", help="Export non-secret database configuration"
    )
    export_settings.add_argument("--output", type=Path, required=True)
    return parser


async def run_command(args: argparse.Namespace, settings: Settings) -> int:
    database = create_database(settings)
    try:
        async with database.session_factory() as session:
            repository = BootstrapRepository(session)
            if args.command == "seed":
                path = _path_argument(args.file)
                document = SeedDocument.from_file(path)
                report = await SeedService(repository).apply(
                    document,
                    environment=settings.app_env,
                )
                print(
                    "Seed applied: "
                    f"{report.locations} locations, "
                    f"{report.reward_templates} rewards, "
                    f"{report.menu_items} menu items, "
                    f"{report.promotions} promotions, "
                    f"{report.development_staff} development staff."
                )
                return 0
            if args.command == "create-owner":
                result = await OwnerService(repository).create_or_promote(
                    telegram_id=int(args.telegram_id),
                    display_name=args.display_name,
                )
                action = "updated" if result.changed else "already up to date"
                print(f"Owner {action}: staff_member_id={result.staff_member_id}")
                return 0
            if args.command == "export-settings":
                output = _path_argument(args.output)
                payload = await SeedService(repository).export()
                _atomic_json_write(output, payload)
                print(f"Configuration exported to {output}")
                return 0
        raise ValueError(f"Unknown command: {args.command}")
    finally:
        await database.engine.dispose()


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    try:
        return asyncio.run(run_command(args, settings))
    except (OSError, ValueError, ValidationError, SeedConfigurationError) as exc:
        logger.error("cli_command_rejected", command=args.command, reason=str(exc))
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception("cli_command_failed", command=args.command)
        return 1


def _path_argument(value: Any) -> Path:
    if not isinstance(value, Path):
        raise ValueError("Expected a filesystem path")
    return value


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()
