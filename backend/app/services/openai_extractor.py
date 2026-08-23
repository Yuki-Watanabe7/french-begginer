"""OpenAI structured output による LearningItemExtractor 実装。

OpenAI SDK はこのモジュールに閉じる。retry は一時障害のみ、回数上限付き。
"""

from __future__ import annotations

import os

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from app.domain.tutor import SourceDocument
from app.services.exceptions import (
    ExtractionConfigError,
    ExtractionInvalidResponseError,
    ExtractionTransientError,
)
from app.services.extraction_prompt import (
    DEFAULT_OPENAI_MODEL,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_VERSION,
    OPENAI_PROVIDER,
    build_extraction_user_prompt,
)
from app.services.extraction_schema import ExtractionLlmOutput
from app.services.extractors import ExtractorResult

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_ATTEMPTS = 3


class OpenAILearningItemExtractor:
    """OpenAI chat.completions.parse による抽出。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_OPENAI_MODEL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        client: OpenAI | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._client = client

    def extract(self, source: SourceDocument) -> ExtractorResult:
        client = self._require_client()
        last_transient: ExtractionTransientError | None = None
        for attempt in range(self._max_attempts):
            try:
                return self._extract_once(client, source)
            except ExtractionTransientError as exc:
                last_transient = exc
                if attempt + 1 >= self._max_attempts:
                    raise
        raise last_transient  # pragma: no cover

    def _require_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        api_key = (
            self._api_key
            if self._api_key is not None
            else os.environ.get("OPENAI_API_KEY")
        )
        if not api_key or not api_key.strip():
            raise ExtractionConfigError(
                "OPENAI_API_KEY が設定されていない",
                kind="api_key_missing",
            )
        return OpenAI(
            api_key=api_key,
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    def _extract_once(self, client: OpenAI, source: SourceDocument) -> ExtractorResult:
        try:
            completion = client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_extraction_user_prompt(source),
                    },
                ],
                response_format=ExtractionLlmOutput,
                temperature=0,
                timeout=self._timeout_seconds,
            )
        except RateLimitError as exc:
            raise ExtractionTransientError(
                "抽出 provider が rate limit を返した",
                kind="rate_limit",
            ) from exc
        except APITimeoutError as exc:
            raise ExtractionTransientError(
                "抽出 provider が timeout した",
                kind="timeout",
            ) from exc
        except APIConnectionError as exc:
            raise ExtractionTransientError(
                "抽出 provider への接続に失敗した",
                kind="network",
            ) from exc
        except InternalServerError as exc:
            raise ExtractionTransientError(
                "抽出 provider が一時的な障害を返した",
                kind="provider_error",
            ) from exc
        except AuthenticationError as exc:
            raise ExtractionConfigError(
                "OPENAI_API_KEY が無効",
                kind="api_key_invalid",
            ) from exc
        except (
            LengthFinishReasonError,
            ContentFilterFinishReasonError,
            BadRequestError,
            ValidationError,
        ) as exc:
            raise ExtractionInvalidResponseError(
                "抽出 provider の structured output が不正だった",
                kind="invalid_structured_response",
            ) from exc
        except APIStatusError as exc:
            if exc.status_code is not None and exc.status_code >= 500:
                raise ExtractionTransientError(
                    "抽出 provider が一時的な障害を返した",
                    kind="provider_error",
                ) from exc
            raise ExtractionInvalidResponseError(
                "抽出 provider の応答を解釈できなかった",
                kind="invalid_structured_response",
            ) from exc

        if not completion.choices:
            raise ExtractionInvalidResponseError(
                "抽出 provider の応答が空だった",
                kind="empty_response",
            )

        message = completion.choices[0].message
        if message.refusal:
            raise ExtractionInvalidResponseError(
                "抽出 provider が structured output を拒否した",
                kind="invalid_structured_response",
            )
        parsed = message.parsed
        if parsed is None:
            raise ExtractionInvalidResponseError(
                "抽出 provider の応答が空だった",
                kind="empty_response",
            )
        if not isinstance(parsed, ExtractionLlmOutput):
            raise ExtractionInvalidResponseError(
                "抽出 provider の structured output が schema に合わない",
                kind="invalid_structured_response",
            )

        return ExtractorResult(
            candidates=tuple(parsed.candidates),
            provider=OPENAI_PROVIDER,
            model=self._model,
            extraction_version=EXTRACTION_VERSION,
        )
