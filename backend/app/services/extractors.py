"""学習候補抽出の provider 境界。

OpenAI SDK はこのモジュールには置かない。
service / domain は LearningItemExtractor Protocol にだけ依存する。
実装は `openai_extractor` など provider モジュールが担う。
"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.tutor import SourceDocument
from app.services.extraction_schema import ExtractedCandidate


@dataclass(frozen=True)
class ExtractorResult:
    """Extractor が返す structured 抽出結果。まだ LearningItem ではない。"""

    candidates: tuple[ExtractedCandidate, ...]
    provider: str
    model: str
    extraction_version: str


class LearningItemExtractor(Protocol):
    """SourceDocument から学習候補の structured 結果を返す。"""

    def extract(self, source: SourceDocument) -> ExtractorResult: ...
