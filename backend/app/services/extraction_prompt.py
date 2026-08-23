"""学習候補抽出の prompt と version。

巨大な inline 文字列を service / extractor に散在させない。
prompt を変えるときは EXTRACTION_VERSION を更新し、Candidate と結び付ける。
"""

from app.domain.tutor import SourceDocument

EXTRACTION_VERSION = "extract-v1"
OPENAI_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
MAX_CANDIDATES = 20

EXTRACTION_SYSTEM_PROMPT = f"""\
あなたはフランス語学習用の教材抽出器です。
与えられたフランス語本文に実際に現れた根拠だけから、学習候補を抽出してください。

抽出対象の item_type は次の4種のみです。
- vocabulary: 語彙（単語・短い語）
- expression: 再利用価値の高い句・表現
- grammar: 文法事項
- conjugation: 動詞活用に関する学習対象

各候補には必ず次を含めてください。
- item_type
- canonical_form: 学習対象の正規形
- meaning_ja: 日本語の意味
- explanation_ja: 任意。短い日本語の説明
- level: 任意。A1 / A2 / B1 / B2 / C1 / C2 のいずれか
- evidence_span.start / evidence_span.end: 本文に対する 0-based の文字オフセット。
  Python の content[start:end] で根拠断片が切り出せること。バイトオフセットは使わない。
- confidence: 0.0 以上 1.0 以下

守ること:
- 本文に現れない学習項目を創作しない
- 同じ意味の細粒度候補を大量に作らない。近いものは1件にまとめる
- 初学者向けという理由だけで、本文に必要な知識を除外しない
- 語単体だけに偏らず、再利用価値の高い表現も拾う
- 候補は最大 {MAX_CANDIDATES} 件。優先度の高いものから返す
- evidence_span は本文の範囲内に収める
"""


def build_extraction_user_prompt(source: SourceDocument) -> str:
    """Extractor に渡すユーザーメッセージ。本文と文字数を明示する。"""
    return (
        f"title: {source.title}\n"
        f"language: {source.language}\n"
        f"content_length: {len(source.content)}\n"
        "content:\n"
        f"{source.content}\n"
    )
