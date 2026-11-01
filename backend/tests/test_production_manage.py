"""停止・更新時の backup 失敗が build を許可しないことを、外部変更なしで検証。"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("action", "fail", "expected_code", "expected"),
    [
        ("upgrade", True, 1, ["compose stop web backend", "backup pre-upgrade"]),
        ("stop", True, 1, ["compose stop web backend", "backup shutdown"]),
        ("start", True, 0, ["backup daily", "compose up -d --wait"]),
        (
            "upgrade",
            False,
            0,
            [
                "compose stop web backend",
                "backup pre-upgrade",
                "compose up -d --build --wait",
                "compose exec -T backend python -m app.persistence.readiness",
            ],
        ),
    ],
)
def test_operation_order_and_failure_boundary(
    tmp_path, action, fail, expected_code, expected
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        ROOT / "scripts/production_manage.sh", scripts / "production_manage.sh"
    )
    compose = scripts / "production_compose.sh"
    compose.write_text('#!/bin/bash\nprintf "compose %s\\n" "$*" >> "$TEST_LOG"\n')
    uv = tmp_path / "uv"
    uv.write_text("""#!/bin/bash
while [[ "$1" != --reason ]]; do shift; done
printf 'backup %s\n' "$2" >> "$TEST_LOG"
exit "$TEST_BACKUP_FAILURE"
""")
    uv.chmod(0o700)
    log = tmp_path / "actions"
    result = subprocess.run(
        ["bash", str(scripts / "production_manage.sh"), action],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "TEST_LOG": str(log),
            "TEST_BACKUP_FAILURE": "1" if fail else "0",
            "FRENCH_BACKUP_CONFIG": str(tmp_path / "private-config.json"),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected_code, result.stderr
    assert log.read_text().splitlines() == expected
    if action == "start" and fail:
        assert "バックアップ未達" in result.stderr
