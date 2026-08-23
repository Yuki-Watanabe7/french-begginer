"""repository 層の例外。service が捕捉してユースケースの失敗に変換する。"""


class RepositoryError(Exception):
    """永続化操作の失敗。"""


class DuplicateEntityError(RepositoryError):
    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} は既に存在する: id={entity_id}")


class ReferentialIntegrityError(RepositoryError):
    """存在しない LearningItem / SourceDocument を参照した場合など。"""
