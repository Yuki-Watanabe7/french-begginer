"""外部 Source の取得 adapter（Issue #190 / #191 / #192）。

domain はここを import しない。HTTP client は `stdlib_http` に閉じ、
PDF パーサは `pdf_parser` に閉じ、YouTube の字幕取得は `youtube_api` に閉じる。
service は各 Protocol だけに依存する。動画の音声は取得しない。
"""
