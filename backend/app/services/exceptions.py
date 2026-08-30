"""service 層の例外。API 層が HTTP status へ変換する。"""


class TutorServiceError(Exception):
    """Tutor ユースケースの失敗。"""


class TutorNotFoundError(TutorServiceError):
    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} が見つからない: id={entity_id}")


class TutorConflictError(TutorServiceError):
    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} は既に存在する: id={entity_id}")


class InvalidSourceRefError(TutorServiceError):
    """LearningItem が存在しない SourceDocument を参照している。"""

    def __init__(self, source_document_id: str) -> None:
        self.source_document_id = source_document_id
        super().__init__(
            f"存在しない SourceDocument を参照している: id={source_document_id}"
        )


class InvalidCandidateTransitionError(TutorServiceError):
    """Candidate の終端 status からの不正な遷移。"""

    def __init__(
        self,
        candidate_id: str,
        current_status: str,
        requested_status: str,
    ) -> None:
        self.candidate_id = candidate_id
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            f"LearningItemCandidate の status を {current_status} から "
            f"{requested_status} へは変更できない: id={candidate_id}"
        )


class TutorInvalidCandidateError(TutorServiceError):
    """evidence 不正など、採用できない Candidate。"""

    def __init__(self, candidate_id: str, reason: str) -> None:
        self.candidate_id = candidate_id
        self.reason = reason
        super().__init__(
            f"LearningItemCandidate を採用できない: id={candidate_id}: {reason}"
        )


class TutorUnsupportedExerciseError(TutorServiceError):
    """当該 LearningItem にその ExerciseType を出せない。"""

    def __init__(
        self,
        item_id: str,
        exercise_type: str,
        skip_reason: str,
        detail: str,
    ) -> None:
        self.item_id = item_id
        self.exercise_type = exercise_type
        self.skip_reason = skip_reason
        self.detail = detail
        super().__init__(f"{skip_reason}: {detail}")


class TutorMalformedAnswerError(TutorServiceError):
    """Exercise 回答の形が response_kind と合わない。"""


class InvalidPracticeFilterError(TutorServiceError):
    """source_id と item_ids の同時指定など、Practice Session 入力が不正。"""


class ExtractionError(TutorServiceError):
    """Source からの学習候補抽出に失敗した。

    retryable=True は timeout / network / rate limit などの一時障害。
    設定不備や structured output の validation 失敗は retryable=False。
    """

    retryable: bool = False

    def __init__(self, message: str, *, kind: str) -> None:
        self.kind = kind
        super().__init__(message)


class ExtractionConfigError(ExtractionError):
    """API key 未設定・無効など、設定の問題。retry しない。"""

    retryable = False


class ExtractionTransientError(ExtractionError):
    """timeout / network / rate limit。回数を限定した retry の対象。"""

    retryable = True


class ExtractionInvalidResponseError(ExtractionError):
    """structured output が不正、または空。retry しない。"""

    retryable = False
