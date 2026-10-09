"""外部 Source の取得 adapter（Issue #190 / #191 / #192 / #193）。

domain はここを import しない。HTTP client は `stdlib_http` に閉じ、
PDF パーサは `pdf_parser` に閉じ、YouTube の字幕取得は `youtube_api` に閉じ、
音声の文字起こし SDK は `audio_api` に閉じる。service は各 Protocol だけに依存する。
YouTube 取り込みは動画の音声を取得しない。音声アップロードの raw audio は保存しない。
"""
