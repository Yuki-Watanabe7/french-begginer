"""外部 Source の取得 adapter（Issue #190）。

domain はここを import しない。HTTP client は `stdlib_http` に閉じ、
service は `WebPageFetcher` だけに依存する。
"""
