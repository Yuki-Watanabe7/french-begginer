#!/usr/bin/env python3
"""家庭内本番のバックアップ・状態・復元。uv run --project backend python ... で実行。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.persistence.backup_store import (  # noqa: E402
    BackupConfig,
    backup,
    backup_status,
    restore,
)
from app.persistence.config import is_production_volume  # noqa: E402


def docker_output(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, timeout=30).strip()


def production_snapshot(output: Path, reason: str) -> dict:
    container = subprocess.check_output(
        [
            "bash",
            str(ROOT / "scripts/production_compose.sh"),
            "ps",
            "--all",
            "--quiet",
            "backend",
        ],
        text=True,
        timeout=30,
    ).strip()
    if not container or "\n" in container:
        raise ValueError("本番 backend コンテナを1つ特定できません")
    mounts = json.loads(
        docker_output("inspect", "--format", "{{json .Mounts}}", container)
    )
    if not any(
        m.get("Type") == "volume"
        and is_production_volume(m.get("Name", ""))
        and m.get("Destination") == "/var/lib/french-tutor"
        for m in mounts
    ):
        raise ValueError("本番専用 volume の mount が確認できません")
    image = docker_output("inspect", "--format", "{{.Image}}", container)
    # --volumes-from は元コンテナ消失時に失敗する。無い named volume を自動作成しない。
    with output.open("xb") as stream:
        output.chmod(0o600)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "10001:10001",
                "--volumes-from",
                container + ":ro",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,uid=10001,gid=10001,mode=0700",
                "--entrypoint",
                "python",
                image,
                "-m",
                "app.persistence.backup",
                "export",
                "--reason",
                reason,
            ],
            stdout=stream,
            check=True,
            timeout=180,
        )
    if reason == "pre-upgrade":
        # 同じタグの build で旧イメージを見失わないよう、ローカルに固定する。
        docker_output(
            "image",
            "tag",
            image,
            "french-production-backend:rollback-" + image.split(":")[-1][:12],
        )
    return {"image_id": image}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "status"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        if name == "backup":
            command.add_argument(
                "--reason", choices=["daily", "shutdown", "pre-upgrade"], required=True
            )
            command.add_argument("--if-due", action="store_true")
    command = sub.add_parser("restore")
    command.add_argument("--bundle", type=Path, required=True)
    command.add_argument("--destination", type=Path, required=True)
    command.add_argument("--identity", type=Path, required=True)
    command.add_argument("--recovery-point")
    command.add_argument("--recovery-started-at")
    command = sub.add_parser("verify-application")
    command.add_argument("--restored", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "verify-application":
            from app.persistence.recovery_drill import verify_application

            result = verify_application(args.restored.resolve())
        elif args.command == "restore":
            result = restore(
                args.bundle.resolve(),
                args.destination.absolute(),
                args.identity,
                recovery_point=args.recovery_point,
                recovery_started_at=args.recovery_started_at,
            )
        else:
            config = BackupConfig.load(args.config)
            if args.command == "status":
                result = backup_status(config)
            else:
                result = backup(
                    config,
                    lambda path: production_snapshot(path, args.reason),
                    reason=args.reason,
                    if_due=args.if_due,
                )
        print(json.dumps(result, indent=2))
        if args.command == "verify-application":
            return 0 if result["rpo_met"] and result["rto_met"] else 1
        return 1 if args.command == "status" and not result["rpo_met"] else 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"未達: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
