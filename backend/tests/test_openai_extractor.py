"""OpenAILearningItemExtractor の境界テスト（Issue #132）。

実通信はしない。client を差し替え、エラー分類と retry 上限を確認する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app.domain.tutor import SourceDocument
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
)
from app.services.extraction_prompt import (
    DEFAULT_OPENAI_MODEL,
    EXTRACTION_VERSION,
    MAX_CANDIDATES,
    OPENAI_PROVIDER,
    build_extraction_user_prompt,
)
from app.services.extraction_schema import (
    ExtractedCandidate,
    ExtractedEvidenceSpan,
    ExtractionLlmOutput,
)
from app.services.openai_extractor import OpenAILearningItemExtractor

CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."


def _source() -> SourceDocument:
    return SourceDocument(title="記事", content=CONTENT)


def _llm_output() -> ExtractionLlmOutput:
    start = CONTENT.index("stratégie")
    return ExtractionLlmOutput(
        candidates=[
            ExtractedCandidate(
                item_type="vocabulary",
                canonical_form="stratégie",
                meaning_ja="戦略",
                evidence_span=ExtractedEvidenceSpan(
                    start=start, end=start + len("stratégie")
                ),
                confidence=0.9,
            )
        ]
    )


def _completion(
    parsed: object,
    *,
    refusal: str | None = None,
    empty_choices: bool = False,
):
    completion = MagicMock()
    if empty_choices:
        completion.choices = []
        return completion
    message = MagicMock()
    message.parsed = parsed
    message.refusal = refusal
    choice = MagicMock()
    choice.message = message
    completion.choices = [choice]
    return completion


def _client_returning(completion) -> MagicMock:
    client = MagicMock()
    client.chat.completions.parse.return_value = completion
    return client


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


def test_extract_returns_structured_candidates_with_metadata():
    client = _client_returning(_completion(_llm_output()))
    extractor = OpenAILearningItemExtractor(client=client, model=DEFAULT_OPENAI_MODEL)
    source = _source()

    result = extractor.extract(source)

    assert result.provider == OPENAI_PROVIDER
    assert result.model == DEFAULT_OPENAI_MODEL
    assert result.extraction_version == EXTRACTION_VERSION
    assert len(result.candidates) == 1
    assert result.candidates[0].canonical_form == "stratégie"

    client.chat.completions.parse.assert_called_once()
    kwargs = client.chat.completions.parse.call_args.kwargs
    assert kwargs["model"] == DEFAULT_OPENAI_MODEL
    assert kwargs["response_format"] is ExtractionLlmOutput
    user_content = kwargs["messages"][1]["content"]
    assert CONTENT in user_content
    assert user_content == build_extraction_user_prompt(source)
    assert f"最大 {MAX_CANDIDATES} 件" in kwargs["messages"][0]["content"]


def test_missing_api_key_is_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    extractor = OpenAILearningItemExtractor(api_key="")
    with pytest.raises(ExtractionConfigError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "api_key_missing"
    assert exc_info.value.retryable is False


def test_timeout_is_transient_and_retries_until_limit():
    client = MagicMock()
    client.chat.completions.parse.side_effect = APITimeoutError(_request())
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=3)

    with pytest.raises(ExtractionTransientError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "timeout"
    assert exc_info.value.retryable is True
    assert client.chat.completions.parse.call_count == 3


def test_network_error_is_transient():
    client = MagicMock()
    client.chat.completions.parse.side_effect = APIConnectionError(request=_request())
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=1)

    with pytest.raises(ExtractionTransientError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "network"


def test_rate_limit_is_transient_and_does_not_retry_forever():
    client = MagicMock()
    client.chat.completions.parse.side_effect = RateLimitError(
        "rate limited",
        response=_response(429),
        body=None,
    )
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=2)

    with pytest.raises(ExtractionTransientError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "rate_limit"
    assert client.chat.completions.parse.call_count == 2


def test_retries_transient_then_succeeds():
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        APITimeoutError(_request()),
        _completion(_llm_output()),
    ]
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=3)

    result = extractor.extract(_source())
    assert len(result.candidates) == 1
    assert client.chat.completions.parse.call_count == 2


def test_invalid_api_key_is_config_error_and_not_retried():
    client = MagicMock()
    client.chat.completions.parse.side_effect = AuthenticationError(
        "invalid",
        response=_response(401),
        body=None,
    )
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=3)

    with pytest.raises(ExtractionConfigError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "api_key_invalid"
    assert client.chat.completions.parse.call_count == 1


def test_empty_parsed_response_is_invalid():
    client = _client_returning(_completion(None))
    extractor = OpenAILearningItemExtractor(client=client, max_attempts=3)

    with pytest.raises(ExtractionInvalidResponseError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "empty_response"
    assert exc_info.value.retryable is False
    assert client.chat.completions.parse.call_count == 1


def test_empty_choices_is_invalid():
    client = _client_returning(_completion(None, empty_choices=True))
    extractor = OpenAILearningItemExtractor(client=client)

    with pytest.raises(ExtractionInvalidResponseError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "empty_response"


def test_refusal_is_invalid_structured_response():
    client = _client_returning(_completion(_llm_output(), refusal="no"))
    extractor = OpenAILearningItemExtractor(client=client)

    with pytest.raises(ExtractionInvalidResponseError) as exc_info:
        extractor.extract(_source())
    assert exc_info.value.kind == "invalid_structured_response"
    assert client.chat.completions.parse.call_count == 1
