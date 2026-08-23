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
