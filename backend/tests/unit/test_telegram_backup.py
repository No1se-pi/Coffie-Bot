from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "telegram_backup.py"
SPEC = importlib.util.spec_from_file_location("telegram_backup", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
BACKUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKUP)


def snapshot(directory: Path) -> Path:
    directory.mkdir()
    (directory / "database.dump").write_bytes(b"customer balances and immutable operations")
    (directory / "media.tar.gz").write_bytes(b"menu photographs")
    (directory / "manifest.txt").write_text("database_format=postgresql_custom\n")
    (directory / ".env").write_text("BOT_TOKEN=must-not-leave-server")
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{BACKUP.file_sha256(directory / name)}  {name}\n"
            for name in ["database.dump", "media.tar.gz"]
        )
    )
    return directory


def test_archive_contains_restore_data_and_excludes_environment(tmp_path: Path) -> None:
    source = snapshot(tmp_path / "snapshot")
    archive_path = tmp_path / "backup.zip"
    BACKUP.build_archive(source, archive_path, b'{"menu": {"items": []}}')
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {
            *BACKUP.BACKUP_FILES,
            "settings.json",
            "RESTORE.txt",
        }
        assert b"must-not-leave-server" not in b"".join(
            archive.read(name) for name in archive.namelist()
        )
        assert archive.read("database.dump") == (source / "database.dump").read_bytes()


def test_corrupt_dump_is_rejected_before_packaging(tmp_path: Path) -> None:
    source = snapshot(tmp_path / "snapshot")
    (source / "database.dump").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="checksum mismatch"):
        BACKUP.build_archive(source, tmp_path / "backup.zip", b"{}")
    assert not (tmp_path / "backup.zip").exists()


def test_resume_sends_only_unacknowledged_parts(tmp_path: Path, monkeypatch) -> None:
    day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    directory = tmp_path / "backups" / "telegram-daily" / day
    directory.mkdir(parents=True)
    payload = b"0123456789abcdef"
    archive = directory / f"coffee-backup-{day}.zip"
    archive.write_bytes(payload)
    monkeypatch.setattr(BACKUP, "PART_BYTES", 8)
    monkeypatch.setattr(sys, "argv", ["backup", "--root", str(tmp_path), "--chat-id", "123"])
    monkeypatch.setattr(BACKUP.os, "umask", lambda _: None)
    attempts = []

    def send(command, *, input, **kwargs):
        attempts.append(input)
        if len(attempts) == 2:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, b'{"message_id": 5, "chat_id": 123}')

    monkeypatch.setattr(BACKUP.subprocess, "run", send)
    with pytest.raises(subprocess.CalledProcessError):
        BACKUP.main()
    state = json.loads((directory / "delivery.json").read_text())
    assert set(state["parts"]) == {"1"}
    BACKUP.main()
    BACKUP.main()
    assert attempts == [payload[:8], payload[8:], payload[8:]]
    assert "completed_at_utc" in json.loads((directory / "delivery.json").read_text())


def test_changed_recipient_cannot_reuse_delivery(tmp_path: Path, monkeypatch) -> None:
    day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    directory = tmp_path / "backups" / "telegram-daily" / day
    directory.mkdir(parents=True)
    (directory / f"coffee-backup-{day}.zip").write_bytes(b"archive")
    (directory / "delivery.json").write_text('{"chat_id": 999, "parts": {}}')
    monkeypatch.setattr(sys, "argv", ["backup", "--root", str(tmp_path), "--chat-id", "123"])
    monkeypatch.setattr(BACKUP.os, "umask", lambda _: None)
    with pytest.raises(ValueError, match="recipient"):
        BACKUP.main()
