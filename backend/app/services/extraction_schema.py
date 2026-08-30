"""LLM structured output 用の schema。

LearningItemCandidate そのものではない。LLM 出力は id / status / source 参照を
持たず、service が domain モデルへ写す。未知 enum・必須欠落・confidence 範囲・
span 形状・件数上限はここで reject する。
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.tutor import CefrLevel, LearningItemType
from app.services.extraction_prompt import MAX_CANDIDATES


class ExtractedEvidenceSpan(BaseModel):
    """LLM が返す根拠位置。text は要求しない（本文から再構成する）。"""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "ExtractedEvidenceSpan":
        if self.end <= self.start:
            raise ValueError(
                f"evidence spanのendはstartより大きい必要がある: "
                f"start={self.start}, end={self.end}"
            )
        return self


class ExtractedCandidate(BaseModel):
    """LLM が返す学習候補1件。"""

    model_config = ConfigDict(extra="forbid")

    item_type: LearningItemType
    canonical_form: str = Field(min_length=1)
    meaning_ja: str = Field(min_length=1)
    explanation_ja: str | None = None
    level: CefrLevel | None = None
    tense: str | None = None
    mood: str | None = None
    evidence_span: ExtractedEvidenceSpan
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _blank_grammar_labels_are_none(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        updated = dict(data)
        for key in ("tense", "mood"):
            value = updated.get(key)
            if isinstance(value, str):
                updated[key] = value.strip() or None
        return updated


class ExtractionLlmOutput(BaseModel):
    """structured output のルート。"""

    model_config = ConfigDict(extra="forbid")

    candidates: list[ExtractedCandidate] = Field(max_length=MAX_CANDIDATES)
