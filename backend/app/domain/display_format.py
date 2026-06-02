"""
主語付き表示文生成ユーティリティ。

責務: CONJUGATIONSから取得した活用形（子音/母音始まり）に主語を結合し、
フランス語として正しい表示文を返す。

elisionルール（présent現在形対象）:
  - je + 母音始まりの活用形 → j' + 活用形  （例: je + écoute → j'écoute）
  - je + 子音始まりの活用形 → je + スペース + 活用形（例: je + suis → je suis）
  - その他の主語 → 主語 + スペース + 活用形

将来拡張:
  - 無音h（heure など）と有音h（hibou など）の区別は未対応（Issue #88）
  - me/te/se/le/la/de/ne/que のelisionは別Issueで扱う
"""

# 母音（アクセント付き含む）— h の扱いは将来拡張（Issue #88）
_VOWELS: frozenset[str] = frozenset("aeéèêëiîïoôœuûüy")


def format_subject_verb(pronoun: str, conjugation: str) -> str:
    """主語と活用形を結合してelisionを適用した表示文を返す。

    Args:
        pronoun: 主語（例: "je", "tu", "il/elle"）
        conjugation: 活用形のみ（例: "écoute", "suis"）— 主語付きは渡さない

    Returns:
        表示文（例: "j'écoute", "je suis", "tu parles"）
    """
    if pronoun == "je" and conjugation and conjugation[0].lower() in _VOWELS:
        return f"j'{conjugation}"
    return f"{pronoun} {conjugation}"
