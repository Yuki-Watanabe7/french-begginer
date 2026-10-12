"""字幕 cue を、時刻付きの plain text 断片へ揃える（Issue #192）。

YouTube transcript と SRT / VTT は、ここを通ってから共有の
`assemble_ingestion_result` へ渡す。各 cue は 1 segment のままにする。
隣接 cue は結合しない。入力順を維持し、時刻が重なっても並べ替えない。
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.source_ingestion import (
    SourceSegmentDraft,
    normalize_source_text,
)

_VOICE_TAG = re.compile(
    r"<v(?:\s+([^>]+?)|\.([^>\s]+))\s*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")
_MAX_SPEAKER_CHARS = 200


class TimedTextError(Exception):
    """cue 本文を plain text にできなかった。呼び出し側が公開エラーへ移す。"""


@dataclass(frozen=True)
class TimedCue:
    """1 cue。`text` は整形前でも整形後でもよい。"""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class TimedCueDrafts:
    drafts: tuple[SourceSegmentDraft, ...]
    empty_cue_count: int


def strip_cue_markup(text: str) -> tuple[str, str | None]:
    """装飾タグを除き、cue 全体が単一の話者ならその名前を返す。"""

    if "\x00" in text:
        raise TimedTextError("nul")
    unescaped = html.unescape(text)
    without_overrides = _ASS_OVERRIDE.sub("", unescaped)
    voices: list[str] = []

    def _remember_voice(match: re.Match[str]) -> str:
        raw_name = match.group(1) if match.group(1) is not None else match.group(2)
        name = _clean_speaker(raw_name or "")
        if name is not None:
            voices.append(name)
        return ""

    without_voice = _VOICE_TAG.sub(_remember_voice, without_overrides)
    plain = _TAG.sub("", without_voice)
    unique: list[str] = []
    for name in voices:
        if name not in unique:
            unique.append(name)
    speaker = unique[0] if len(unique) == 1 else None
    return plain, speaker


def normalize_cue_body(text: str) -> str:
    """cue 内の空白を畳む。アポストロフィと改行の有無は変えない。

    NFC は共有の `normalize_source_text` が一度だけ行う。
    """

    if "\x00" in text:
        raise TimedTextError("nul")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def cues_to_drafts(cues: Sequence[TimedCue]) -> TimedCueDrafts:
    """空 cue を除き、残った cue を入力順の segment 草案にする。"""

    drafts: list[SourceSegmentDraft] = []
    empty = 0
    for cue in cues:
        _require_cue_timing(cue)
        plain, tagged_speaker = strip_cue_markup(cue.text)
        body = normalize_cue_body(plain)
        if not normalize_source_text(body):
            empty += 1
            continue
        speaker = _explicit_speaker(cue.speaker) or tagged_speaker
        drafts.append(
            SourceSegmentDraft(
                text=body,
                start_seconds=cue.start_seconds,
                end_seconds=cue.end_seconds,
                speaker=speaker,
            )
        )
    return TimedCueDrafts(tuple(drafts), empty)


def _require_cue_timing(cue: TimedCue) -> None:
    start = cue.start_seconds
    end = cue.end_seconds
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise TimedTextError("timecode")


def _explicit_speaker(speaker: str | None) -> str | None:
    if speaker is None:
        return None
    return _clean_speaker(speaker)


def _clean_speaker(name: str) -> str | None:
    cleaned = " ".join(name.split())
    if not cleaned:
        return None
    if len(cleaned) > _MAX_SPEAKER_CHARS:
        cleaned = cleaned[:_MAX_SPEAKER_CHARS].rstrip()
    return cleaned or None
