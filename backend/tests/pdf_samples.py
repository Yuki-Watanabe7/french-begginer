"""テキスト PDF の固定バイト列（Issue #191）。

WinAnsi の 8 進エスケープでフランス語のアクセントを書く。
pypdf の plain 抽出がページ順の text layer を返すことを、テストが検証する。
"""

from __future__ import annotations


def build_pdf(page_contents: list[bytes], *, comment: str | None = None) -> bytes:
    """ページ本文（content stream）から、xref 付きの PDF を組み立てる。"""

    count = len(page_contents)
    if count == 0:
        raise ValueError("page が空")
    font_id = 3 + 2 * count
    stream_ids = range(3 + count, 3 + 2 * count)
    kids = " ".join(f"{page_id} 0 R" for page_id in range(3, 3 + count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
    ]
    for stream_id in stream_ids:
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {stream_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode()
        )
    objects.extend(_stream(payload) for payload in page_contents)
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    return _serialize(objects, comment=comment)


def text_page(*lines: str) -> bytes:
    """PDF 文字列としてそのまま書く行。`\\n` は段落用のエスケープ。"""

    commands = ["BT", "/F1 12 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -18 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    return ("\n".join(commands) + "\n").encode("ascii")


def lesson_pdf(*, comment: str | None = None) -> bytes:
    """3 ページ。アクセント、アポストロフィ、段落、ページ境界を含む。"""

    return build_pdf(
        [
            text_page(
                r"Le\347on 1",
                r"Aujourd'hui, l'\351l\350ve prend un caf\351."
                r"\n\nIl n'est pas trop tard pour apprendre le fran\347ais.",
            ),
            text_page(
                r"Le\347on 1",
                r"C'est l'heure du petit d\351jeuner.",
                r"L'\351cole ouvre \340 huit heures.",
            ),
            text_page(
                r"Le\347on 1",
                r"Bon courage, et \340 demain.",
            ),
        ],
        comment=comment,
    )


def _stream(payload: bytes) -> bytes:
    return f"<< /Length {len(payload)} >>\nstream\n".encode() + payload + b"\nendstream"


def _serialize(objects: list[bytes], *, comment: str | None) -> bytes:
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    if comment is not None:
        header += f"% {comment}\n".encode("ascii")
    chunks = [header]
    offsets: list[int] = []
    cursor = len(header)
    for index, body in enumerate(objects, start=1):
        offsets.append(cursor)
        piece = f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        chunks.append(piece)
        cursor += len(piece)
    xref = [f"xref\n0 {len(objects) + 1}\n".encode(), b"0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    xref.append(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{cursor}\n%%EOF\n"
        ).encode()
    )
    return b"".join(chunks + xref)
