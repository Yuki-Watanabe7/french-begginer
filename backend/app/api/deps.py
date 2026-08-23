"""Tutor API の依存性注入。

router は TutorService だけを受け取り、SQLite を直接見ない。
テストは `get_tutor_store` を in-memory store に差し替える。
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.repositories.sqlite import TutorSqliteStore
from app.services.tutor_service import TutorService, build_tutor_service


@lru_cache(maxsize=1)
def get_tutor_store() -> TutorSqliteStore:
    return TutorSqliteStore.from_env()


def get_tutor_service(
    store: Annotated[TutorSqliteStore, Depends(get_tutor_store)],
) -> TutorService:
    return build_tutor_service(store)
