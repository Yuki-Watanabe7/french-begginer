"""外部 Source の取得 adapter（Issue #190 / #191）。

domain はここを import しない。HTTP client は `stdlib_http` に閉じ、
PDF パーサは `pdf_parser` に閉じる。service は各 Protocol だけに依存する。
"""
