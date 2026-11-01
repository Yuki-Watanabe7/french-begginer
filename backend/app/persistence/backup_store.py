"""私的な暗号化世代管理。鍵は復元時だけ読み、日次処理に復号鍵を置かない。"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.persistence.backup import sha256, unpack_verified, utc_now

BACKUP_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{32}")
REPOSITORY = Path(__file__).resolve().parents[3]


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return result.astimezone(UTC)


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private directory cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_mode & 0o077:
        raise ValueError("private directory requires mode 0700")


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class BackupConfig:
    local_dir: Path
    offhost_mount: Path
    device_id: str
    recipients_file: Path
    age_command: str = "age"

    @classmethod
    def load(cls, path: Path) -> BackupConfig:
        raw = json.loads(path.read_text())
        result = cls(
            local_dir=Path(raw["local_dir"]).expanduser().resolve(),
            offhost_mount=Path(raw["offhost_mount"]).expanduser().resolve(),
            device_id=raw["device_id"],
            recipients_file=Path(raw["recipients_file"]).expanduser().resolve(),
        )
        for location in (
            result.local_dir,
            result.offhost_mount,
            result.recipients_file,
        ):
            if location.is_relative_to(REPOSITORY):
                raise ValueError("backup data and keys must be outside the repository")
        if result.local_dir.is_relative_to(result.offhost_mount):
            raise ValueError("local backup directory must be on the host")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", result.device_id):
            raise ValueError("invalid device id")
        return result

    def offhost_directory(self, *, create: bool = True) -> Path:
        # 未接続時に /Volumes の空フォルダへ書き続けることを防ぐ。
        if not self.offhost_mount.is_mount():
            raise ValueError("off-host device is not mounted; RPO unverified")
        if self.offhost_mount.stat().st_dev == self.local_dir.stat().st_dev:
            raise ValueError("off-host device is on the host filesystem")
        marker = self.offhost_mount / ".french-tutor-backup-device"
        if marker.is_symlink() or marker.read_text().strip() != self.device_id:
            raise ValueError("off-host device id mismatch")
        directory = self.offhost_mount / "french-tutor-backups"
        if create:
            private_directory(directory)
        elif not directory.is_dir() or directory.is_symlink():
            raise ValueError("off-host backup directory missing")
        return directory


@contextmanager
def store_lock(config: BackupConfig) -> Iterator[None]:
    private_directory(config.local_dir)
    with (config.local_dir / ".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another backup/retention operation is running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_age(command: str, arguments: list[str]) -> None:
    try:
        subprocess.run(
            [command, *arguments],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=300,
        )
    except subprocess.CalledProcessError:
        # キーやパス等をログに展開しない。復号失敗を成功扱いしない。
        raise ValueError("age encryption/decryption failed") from None


def read_receipt(bundle: Path) -> dict:
    if bundle.is_symlink() or not BACKUP_ID.fullmatch(bundle.name):
        raise ValueError("invalid backup directory")
    if {p.name for p in bundle.iterdir()} != {"archive.age", "receipt.json"}:
        raise ValueError("incomplete backup generation")
    if any(p.is_symlink() or not p.is_file() for p in bundle.iterdir()):
        raise ValueError("invalid backup file")
    receipt = json.loads((bundle / "receipt.json").read_text())
    if receipt["format_version"] != 1 or receipt["backup_id"] != bundle.name:
        raise ValueError("backup receipt mismatch")
    if sha256(bundle / "archive.age") != receipt["ciphertext_sha256"]:
        raise ValueError("encrypted backup hash mismatch")
    timestamp(receipt["snapshot_started_at"])
    return receipt


def generations(directory: Path) -> list[tuple[Path, dict]]:
    result = []
    for path in directory.iterdir():
        if path.is_dir() and BACKUP_ID.fullmatch(path.name):
            result.append((path, read_receipt(path)))
    return sorted(
        result, key=lambda entry: entry[1]["snapshot_started_at"], reverse=True
    )


def retained_ids(receipts: list[dict]) -> set[str]:
    """最新の日次7日・週次4週・月次3月の和集合。upgrade前は自動削除しない。"""
    ordered = sorted(receipts, key=lambda r: r["snapshot_started_at"], reverse=True)
    keep = {r["backup_id"] for r in ordered if r["reason"] == "pre-upgrade"}
    for limit, key in (
        (7, lambda d: d.date()),
        (4, lambda d: d.isocalendar()[:2]),
        (3, lambda d: (d.year, d.month)),
    ):
        buckets = set()
        for receipt in ordered:
            bucket = key(timestamp(receipt["snapshot_started_at"]))
            if bucket not in buckets and len(buckets) < limit:
                buckets.add(bucket)
                keep.add(receipt["backup_id"])
    return keep


def prune(local_dir: Path, offhost_dir: Path) -> None:
    entries = generations(offhost_dir)  # 壊れた世代があれば削除に進まない。
    keep = retained_ids([receipt for _, receipt in entries])
    for bundle, _receipt in entries:
        if bundle.name in keep:
            continue
        # 既知2ファイルだけを削除。別のファイルが混じっていたら read_receipt が拒否。
        for location in (local_dir / bundle.name, bundle):
            if location.exists():
                read_receipt(location)
                (location / "archive.age").unlink()
                (location / "receipt.json").unlink()
                location.rmdir()
                sync_directory(location.parent)


def copy_encrypted_bundle(source: Path, destination: Path) -> None:
    for name in ("archive.age", "receipt.json"):
        with (source / name).open("rb") as src, (destination / name).open("xb") as dst:
            os.chmod(dst.name, 0o600)
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())


def backup(
    config: BackupConfig,
    provider: Callable[[Path], dict],
    *,
    reason: str,
    if_due: bool = False,
) -> dict:
    """provider は整合コピーを tar へ書く。実行成功は別機器への hash 一致後だけ。"""
    with store_lock(config):
        state_path = config.local_dir / "state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        try:
            offhost = config.offhost_directory()
            if if_due and state.get("last_success"):
                last = state["last_success"]
                remote = read_receipt(offhost / last["backup_id"])
                age = datetime.now(UTC) - timestamp(remote["snapshot_started_at"])
                if timedelta(0) <= age < timedelta(hours=20):
                    return {"status": "not-due", "backup_id": last["backup_id"]}
            with tempfile.TemporaryDirectory(
                prefix=".pending-", dir=config.local_dir
            ) as temp:
                work = Path(temp)
                plain = work / "backup.tar"
                metadata = provider(plain)
                check = work / "check"
                check.mkdir(mode=0o700)
                manifest = unpack_verified(plain, check)
                backup_id = manifest["backup_id"]
                if not BACKUP_ID.fullmatch(backup_id) or manifest["reason"] != reason:
                    raise ValueError("snapshot identity/reason mismatch")
                bundle = work / backup_id
                bundle.mkdir(mode=0o700)
                encrypted = bundle / "archive.age"
                run_age(
                    config.age_command,
                    [
                        "--encrypt",
                        "--recipients-file",
                        str(config.recipients_file),
                        "--output",
                        str(encrypted),
                        str(plain),
                    ],
                )
                encrypted.chmod(0o600)
                with encrypted.open("rb") as stream:
                    os.fsync(stream.fileno())
                receipt = {
                    "format_version": 1,
                    "backup_id": backup_id,
                    "snapshot_started_at": manifest["snapshot_started_at"],
                    "reason": reason,
                    "app_commit": manifest["app_commit"],
                    "app_dirty": manifest["app_dirty"],
                    "schema_version": manifest["schema_version"],
                    "ciphertext_sha256": sha256(encrypted),
                    "image_id": metadata.get("image_id"),
                }
                write_json(bundle / "receipt.json", receipt)
                local = config.local_dir / backup_id
                os.rename(bundle, local)
                sync_directory(config.local_dir)
                # 同じデバイスと接続状態をコピー直前・公開直前に再検査。
                if config.offhost_directory() != offhost:
                    raise ValueError("off-host device changed")
                with tempfile.TemporaryDirectory(
                    prefix=".pending-", dir=offhost
                ) as remote_temp:
                    remote_work = Path(remote_temp)
                    copy_encrypted_bundle(local, remote_work)
                    if (
                        sha256(remote_work / "archive.age")
                        != receipt["ciphertext_sha256"]
                    ):
                        raise ValueError("off-host copy hash mismatch")
                    if config.offhost_directory() != offhost:
                        raise ValueError("off-host device changed")
                    os.rename(remote_work, offhost / backup_id)
                    # TemporaryDirectory は rename 後の古いパスが無くても終了できる。
                sync_directory(offhost)
                read_receipt(offhost / backup_id)
                state = {
                    "status": "encrypted-offhost-copy-verified",
                    "last_attempt_at": utc_now(),
                    "last_success": {**receipt, "verified_at": utc_now()},
                    "restore_verified": False,
                }
                write_json(state_path, state)
            prune(config.local_dir, offhost)
            return state
        except Exception as exc:
            write_json(
                state_path,
                {
                    **state,
                    "status": "failed",
                    "last_attempt_at": utc_now(),
                    "failure_type": type(exc).__name__,
                },
            )
            raise


def backup_status(config: BackupConfig) -> dict:
    """offlineでも前回の成功時刻は示すが、現在の到達性・RPOを推測しない。"""
    state_path = config.local_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last = state.get("last_success")
    result = {
        "last_attempt_status": state.get("status", "never"),
        "rpo_met": False,
        "restore_verified": False,
    }
    if last:
        age = (
            datetime.now(UTC) - timestamp(last["snapshot_started_at"])
        ).total_seconds()
        result.update(backup_id=last["backup_id"], recovery_point_age_seconds=age)
        try:
            receipt = read_receipt(
                config.offhost_directory(create=False) / last["backup_id"]
            )
            result["rpo_met"] = (
                receipt
                == {key: value for key, value in last.items() if key != "verified_at"}
                and 0 <= age <= 86400
            )
            result["device"] = "connected-and-hash-verified"
        except (OSError, ValueError, KeyError):
            result["device"] = "unavailable-or-invalid"
    return result


def restore(
    bundle: Path,
    destination: Path,
    identity: Path,
    *,
    age_command: str = "age",
    recovery_point: str | None = None,
    recovery_started_at: str | None = None,
) -> dict:
    """新規ディレクトリだけへ復元。元 DB・既存 volume・復号鍵を変更しない。"""
    started = recovery_started_at or utc_now()
    point = recovery_point or started
    if destination.exists() or destination.is_symlink():
        raise ValueError("restore destination already exists; use a new directory")
    if destination.resolve().is_relative_to(REPOSITORY):
        raise ValueError("restore outside the repository")
    if not identity.is_file():
        raise ValueError("decryption identity missing")
    receipt = read_receipt(bundle)
    with tempfile.TemporaryDirectory(
        prefix=".restore-", dir=destination.parent
    ) as temp:
        work = Path(temp)
        plain = work / "backup.tar"
        run_age(
            age_command,
            [
                "--decrypt",
                "--identity",
                str(identity),
                "--output",
                str(plain),
                str(bundle / "archive.age"),
            ],
        )
        restored = work / "restored"
        restored.mkdir(mode=0o700)
        manifest = unpack_verified(plain, restored)
        for key in (
            "backup_id",
            "snapshot_started_at",
            "app_commit",
            "app_dirty",
            "schema_version",
            "reason",
        ):
            if manifest[key] != receipt[key]:
                raise ValueError("encrypted manifest and receipt differ")
        completed = utc_now()
        rpo = (
            timestamp(point) - timestamp(manifest["snapshot_started_at"])
        ).total_seconds()
        elapsed = (timestamp(completed) - timestamp(started)).total_seconds()
        if rpo < 0 or elapsed < 0:
            raise ValueError("recovery timestamps are in the future")
        record = {
            "backup_id": manifest["backup_id"],
            "app_commit": manifest["app_commit"],
            "image_id": receipt["image_id"],
            "schema_version": manifest["schema_version"],
            "started_at": started,
            "copy_verified_at": completed,
            "recovery_point_age_seconds": rpo,
            "rpo_met": rpo <= 86400,
            "copy_restore_seconds": elapsed,
            "application_answer_verified": False,
            "rto_met": False,
        }
        # DB コピーだけの時間をアプリ復旧の RTO と呼ばない。
        write_json(restored / "restore-record.json", record)
        for path in restored.iterdir():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        sync_directory(restored)
        os.rename(restored, destination)
        sync_directory(destination.parent)
    return record
