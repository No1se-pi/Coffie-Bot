"""Daily database/media backup delivery through the existing backend bot environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PART_BYTES = 45 * 1024 * 1024
BACKUP_FILES = ("database.dump", "media.tar.gz", "manifest.txt", "SHA256SUMS")

EXPORT_SETTINGS = """
import asyncio, json
from app.core.config import get_settings
from app.db.session import create_database
from app.repositories.bootstrap import BootstrapRepository
from app.services.seed import SeedService
async def main():
    db = create_database(get_settings())
    try:
        async with db.session_factory() as session:
            print(json.dumps(await SeedService(BootstrapRepository(session)).export()))
    finally:
        await db.engine.dispose()
asyncio.run(main())
"""

SEND_DOCUMENT = """
import asyncio, json, os, sys
from aiogram import Bot
from aiogram.types import BufferedInputFile
async def main():
    bot = Bot(os.environ['BOT_TOKEN'])
    try:
        chat_id = int(sys.argv[1])
        chat = await bot.get_chat(chat_id)
        if chat.type != 'private' or chat.id != chat_id:
            raise RuntimeError('A private backup recipient is required')
        message = await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(sys.stdin.buffer.read(), filename=sys.argv[2]),
            caption=sys.argv[3], request_timeout=300,
        )
        print(json.dumps({'message_id': message.message_id, 'chat_id': message.chat.id}))
    except Exception as exc:  # noqa: BLE001 -- never expose secrets through exception payloads
        # Do not print request URLs, bot tokens or exception payloads.
        print('Telegram backup delivery failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
    finally:
        await bot.session.close()
asyncio.run(main())
"""

RESTORE_NOTE = """Coffie Bot backup

database.dump: complete PostgreSQL custom dump, including customers, balances,
immutable loyalty operations, menu, staff and application settings.
media.tar.gz: complete persistent media storage, including menu photographs.
settings.json: readable export of current application/menu settings (not a seed).
SHA256SUMS: checksums for database.dump and media.tar.gz.
No bot tokens, .env files or application source are included.

Verify: sha256sum -c SHA256SUMS
Restore with the matching repository version and scripts/restore.sh --from DIRECTORY --yes.
Restoring replaces data; back up the current installation first.
Provide environment secrets separately; they are intentionally excluded.

If delivered in parts, first join all .zip.partNNN files in ascending order:
Linux: cat coffee-backup-*.zip.part* > backup.zip
Windows: copy /b file.zip.part001+file.zip.part002 backup.zip
Then extract backup.zip. Keep all parts of one dated backup together.
"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_snapshot(directory: Path) -> None:
    expected = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name not in {"database.dump", "media.tar.gz"} or name in expected:
            raise ValueError("Unexpected checksum manifest entry")
        expected[name] = digest
    if set(expected) != {"database.dump", "media.tar.gz"}:
        raise ValueError("Incomplete checksum manifest")
    for name, digest in expected.items():
        if file_sha256(directory / name) != digest:
            raise ValueError("Backup checksum mismatch")


def build_archive(snapshot: Path, destination: Path, settings: bytes) -> None:
    verify_snapshot(snapshot)
    json.loads(settings)
    temporary = destination.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in BACKUP_FILES:
            archive.write(snapshot / name, name)
        archive.writestr("settings.json", settings)
        archive.writestr("RESTORE.txt", RESTORE_NOTE)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive verification failed")
    temporary.replace(destination)


def save_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    if args.chat_id <= 0:
        raise ValueError("A private Telegram chat ID is required")
    os.umask(0o077)
    root = args.root.resolve()
    day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    directory = root / "backups" / "telegram-daily" / day
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "delivery.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"parts": {}}
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(root / ".env"),
        "-f",
        str(root / "compose.prod.yaml"),
    ]
    archive_path = directory / f"coffee-backup-{day}.zip"
    if not archive_path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot = directory / f"snapshot-{stamp}"
        environment = dict(
            os.environ,
            ENV_FILE=str(root / ".env"),
            COMPOSE_FILE=str(root / "compose.prod.yaml"),
        )
        subprocess.run(
            ["sh", str(root / "scripts/backup.sh"), "--output", str(snapshot)],
            cwd=root,
            env=environment,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        exported = subprocess.run(
            [*compose, "exec", "-T", "backend", "python", "-c", EXPORT_SETTINGS],
            check=True,
            capture_output=True,
        )
        build_archive(snapshot, archive_path, exported.stdout)
    digest = file_sha256(archive_path)
    if (
        state.get("sha256", digest) != digest
        or state.get("chat_id", args.chat_id) != args.chat_id
    ):
        raise ValueError(
            "Existing delivery belongs to a different archive or recipient"
        )
    state.update(sha256=digest, chat_id=args.chat_id)
    save_state(state_path, state)
    size = archive_path.stat().st_size
    total = (size + PART_BYTES - 1) // PART_BYTES
    with archive_path.open("rb") as stream:
        for index in range(1, total + 1):
            content = stream.read(PART_BYTES)
            key = str(index)
            if key in state["parts"]:
                continue
            filename = (
                archive_path.name
                if total == 1
                else f"{archive_path.name}.part{index:03d}"
            )
            caption = (
                f"Coffie Bot: резервная копия за {day}. БД клиентов и баллов, меню, фото. "
                f"Часть {index}/{total}. SHA256 архива: {digest}"
            )
            result = subprocess.run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "backend",
                    "python",
                    "-c",
                    SEND_DOCUMENT,
                    str(args.chat_id),
                    filename,
                    caption,
                ],
                input=content,
                capture_output=True,
                check=True,
            )
            receipt = json.loads(result.stdout)
            if receipt["chat_id"] != args.chat_id:
                raise ValueError("Unexpected delivery recipient")
            state["parts"][key] = receipt
            save_state(state_path, state)
    state["completed_at_utc"] = datetime.now(UTC).isoformat()
    save_state(state_path, state)
    print(
        json.dumps(
            {
                "event": "backup.telegram_delivered",
                "day": day,
                "chat_id": args.chat_id,
                "parts": total,
                "bytes": size,
                "sha256": digest,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- log only the error type, never secrets
        print(
            json.dumps({"event": "backup.failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
