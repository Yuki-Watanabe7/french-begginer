"""外出先 Read-Only 向けの公開 Snapshot（Issue #221）。

本人が一般公開してよいと選んだ LearningItem だけを、閲覧に必要な最小項目の
新しい DTO に詰め替える。DB 行や API 応答を丸ごと JSON 化しない。

- 入力: allowlist（item_id と取り違え防止の canonical_form）と LearningItem
- 出力: `public-v1` の JSON 1 ファイル。カードは allowlist の順に `card-001` から
  採番し、元 DB の id・source_refs・metadata・status・作成日時は持たない
- LearningEvent / LearnerState / ReviewSchedule / Source 本文は入力にも取らない
- どの階層も未知のキーを拒否する。項目を足すときはこのモジュールの型を変える

文字列の決定的検査は公開事故への最低限の歯止めであって、公開の承認ではない。
公開する内容は本人が生成物を読んで確認する
（docs/operations/remote-readonly-contract.md）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.domain.tutor import CefrLevel, LearningItem, LearningItemType, UtcDatetime

PUBLIC_SNAPSHOT_SCHEMA_VERSION = "public-v1"
MAX_PUBLIC_CARDS = 500

_HTML_TAG = re.compile(r"<[A-Za-z!/?]")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# API キー・hash・UUID など。フランス語の単語や活用表（je/tu/...）は当たらない長さ。
_SECRET_LIKE = re.compile(r"[A-Za-z0-9_+=-]{32,}")


class PublicSnapshotError(ValueError):
    """公開 Snapshot を作れない。部分的なファイルは出さない。"""


def _check_public_text(value: str) -> str:
    if any(unicodedata.category(ch) == "Cc" and ch != "\n" for ch in value):
        raise ValueError("改行以外の制御文字を含む")
    if _HTML_TAG.search(value):
        raise ValueError("HTML のタグらしい記述を含む")
    if _URL.search(value):
        raise ValueError("URL を含む")
    if _EMAIL.search(value):
        raise ValueError("メールアドレスらしい文字列を含む")
    if _SECRET_LIKE.search(value):
        raise ValueError("API キーや ID らしい長い英数字列を含む")
    return value


_PUBLIC_TEXT = AfterValidator(_check_public_text)


class PublicSnapshotAllowlistEntry(BaseModel):
    """公開を許可する LearningItem 1件。canonical_form は DB との一致確認に使う。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    canonical_form: str = Field(min_length=1)


class PublicSnapshotAllowlist(BaseModel):
    """本人が作る許可リスト。並び順がそのままカードの順になる。"""

    model_config = ConfigDict(extra="forbid")

    items: list[PublicSnapshotAllowlistEntry] = Field(
        min_length=1, max_length=MAX_PUBLIC_CARDS
    )

    @model_validator(mode="after")
    def _check_unique_items(self) -> PublicSnapshotAllowlist:
        ids = [entry.item_id for entry in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item_id が重複している")
        return self


class PublicCard(BaseModel):
    """公開版のカード1枚。問いは canonical_form、答えは meaning_ja。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    card_id: str = Field(pattern=r"^card-[0-9]{3}$")
    item_type: LearningItemType
    canonical_form: Annotated[str, Field(min_length=1, max_length=200), _PUBLIC_TEXT]
    meaning_ja: Annotated[str, Field(min_length=1, max_length=500), _PUBLIC_TEXT]
    explanation_ja: (
        Annotated[str, Field(min_length=1, max_length=2000), _PUBLIC_TEXT] | None
    ) = None
    level: CefrLevel | None = None


class PublicSnapshot(BaseModel):
    """`public-v1` の Snapshot。#222 の静的ビューアーはこの形だけを読む。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["public-v1"]
    generated_at: UtcDatetime
    cards: list[PublicCard] = Field(min_length=1, max_length=MAX_PUBLIC_CARDS)

    @model_validator(mode="after")
    def _check_unique_card_ids(self) -> PublicSnapshot:
        ids = [card.card_id for card in self.cards]
        if len(set(ids)) != len(ids):
            raise ValueError("card_id が重複している")
        return self


def describe_validation_error(exc: ValidationError) -> str:
    """入力値を出さずに場所と理由だけを並べる。秘密らしい値を端末へ写さない。"""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)
    )


def build_public_snapshot(
    allowlist: PublicSnapshotAllowlist,
    items: Iterable[LearningItem],
    *,
    generated_at: datetime,
) -> PublicSnapshot:
    """allowlist の Item だけを公開カードにする。1件でも不正なら全体を失敗にする。"""
    by_id = {item.id: item for item in items}
    cards: list[PublicCard] = []
    for number, entry in enumerate(allowlist.items, start=1):
        where = f"allowlist の {number} 件目（item_id={entry.item_id}）"
        item = by_id.get(entry.item_id)
        if item is None:
            raise PublicSnapshotError(f"{where}: DB にない")
        if item.canonical_form != entry.canonical_form:
            raise PublicSnapshotError(f"{where}: canonical_form が DB と一致しない")
        try:
            cards.append(
                PublicCard(
                    card_id=f"card-{number:03d}",
                    item_type=item.item_type,
                    canonical_form=item.canonical_form,
                    meaning_ja=item.meaning_ja,
                    explanation_ja=item.explanation_ja or None,
                    level=item.level,
                )
            )
        except ValidationError as exc:
            raise PublicSnapshotError(
                f"{where}: {describe_validation_error(exc)}"
            ) from None
    return PublicSnapshot(
        schema_version=PUBLIC_SNAPSHOT_SCHEMA_VERSION,
        generated_at=generated_at.replace(microsecond=0),
        cards=cards,
    )


def render_public_snapshot(snapshot: PublicSnapshot) -> str:
    """人が読んで確認できるよう、整形した UTF-8 の JSON にする。任意項目は省く。"""
    payload = snapshot.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_allowlist_draft(items: Iterable[LearningItem]) -> str:
    """suspended 以外の Item を並べた allowlist の下書き。

    下書きは公開の判断ではない。本人が一般公開してよいものだけを残す。
    """
    entries = [
        PublicSnapshotAllowlistEntry(
            item_id=item.id, canonical_form=item.canonical_form
        ).model_dump()
        for item in items
        if item.status != "suspended"
    ]
    return json.dumps({"items": entries}, ensure_ascii=False, indent=2) + "\n"
