"""復元データをさらにコピーし、隔離したアプリで回答保存を実測する。"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.persistence.backup import inspect_database, sha256, snapshot, utc_now
from app.persistence.backup_store import timestamp, write_json
from app.persistence.config import is_production


def verify_application(restored: Path) -> dict:
    if is_production():
        raise ValueError("復元訓練は本番プロセス内で実行しないでください")
    # httpx は dev group のみ。ネットワーク socket は開かず ASGI 内で完結する。
    from fastapi.testclient import TestClient

    from app.api.deps import get_tutor_store
    from app.main import create_app
    from app.repositories.sqlite import TutorSqliteStore
    from app.runtime_settings import RuntimeSettings

    original = restored / "tutor.db"
    manifest = json.loads((restored / "manifest.json").read_text())
    metrics = inspect_database(original)
    if any(manifest.get(key) != value for key, value in metrics.items()):
        raise ValueError("復元後の DB が manifest から変わっています")
    record = json.loads((restored / "restore-record.json").read_text())
    with tempfile.TemporaryDirectory(
        prefix=".answer-drill-", dir=restored.parent
    ) as temp:
        trial = Path(temp) / "tutor.db"
        snapshot(original, trial)
        store = TutorSqliteStore(f"sqlite:///{trial}")
        try:
            app = create_app(RuntimeSettings())
            app.dependency_overrides[get_tutor_store] = lambda: store
            before = inspect_database(trial)["counts"]["learning_events"]
            with TestClient(app) as client:
                sources = client.get("/api/tutor/sources")
                items = client.get("/api/tutor/items")
                if sources.status_code != 200 or items.status_code != 200:
                    raise ValueError("復元した Source/Item をアプリで読めません")
                verified = False
                for item in items.json():
                    item_id = item["id"]
                    base = f"/api/tutor/items/{item_id}"
                    detail = client.get(base)
                    known = client.get(base + "/known")
                    if detail.status_code != 200 or known.status_code != 200:
                        raise ValueError("復元した State/Schedule/known を読めません")
                    exercise = base + "/exercises/meaning_recognition"
                    if client.get(exercise).status_code != 200:
                        continue
                    answer = client.post(
                        exercise + "/answer", json={"answer": "復元訓練"}
                    )
                    if answer.status_code != 201:
                        raise ValueError("復元コピーで回答を保存できません")
                    verified = True
                    break
                if not verified:
                    raise ValueError(
                        "回答検証可能な active Item がありません（RTO 未確認）"
                    )
            after = inspect_database(trial)
            if after["counts"]["learning_events"] != before + 1:
                raise ValueError("回答イベントの保存件数が一致しません")
        finally:
            store.engine.dispose()
    if sha256(original) != manifest["database_sha256"]:
        raise ValueError("未変更の復元 DB が書き換わりました")
    elapsed = (datetime.now(UTC) - timestamp(record["started_at"])).total_seconds()
    record.update(
        application_answer_verified=True,
        application_verified_at=utc_now(),
        recovery_seconds=elapsed,
        rto_met=0 <= elapsed <= 14400,
        validation_schema_version=after["schema_version"],
        pristine_database_sha256=manifest["database_sha256"],
        test_writes="isolated-copy-only",
    )
    write_json(restored / "restore-record.json", record)
    return record
