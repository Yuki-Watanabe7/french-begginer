#!/usr/bin/env python3
"""
LLM-based French domain data review for PR diffs.

Extracts changed files in backend/app/domain/, calls the Claude API to review
French accuracy, and posts results as a PR comment (updating instead of
duplicating on re-runs).

Required env vars:
  ANTHROPIC_API_KEY              Anthropic API key
  GITHUB_TOKEN                   GitHub token (needs issues:write)
  GITHUB_REPOSITORY              "owner/repo"
  GITHUB_PR_NUMBER               PR number as string

Optional env vars:
  BASE_SHA                       Base commit SHA for diff (default: origin/main)
  LLM_DOMAIN_REVIEW_FAIL_ON_ERROR  "true" to exit 1 when errors found (default: "false")
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Unique marker embedded in the PR comment body to find and update it
COMMENT_MARKER = "<!-- llm-domain-review-v1 -->"

DOMAIN_PATH = "backend/app/domain"

SYSTEM_PROMPT = """\
あなたは厳格なフランス語ネイティブ校正者です。
このPRで変更された backend/app/domain 配下のフランス語学習データについて、
初級学習者向けアプリの正解データとして不適切な点を検出してください。

【重要な前提】
- CONJUGATIONS の値は「活用形のみ」です（主語付き表現ではありません）
- 例: écouter/je = "écoute"（"j'écoute" ではない）
- elision は表示層で処理されます

確認観点:
- 動詞活用が標準フランス語として正しいか
- アクセント記号（é, è, ê, à, â, î, ô, û, ù, ç など）が正しいか
- 初級教材（A1/A2レベル）として適切な動詞・活用形か
- 同じ概念に対する表記揺れがないか（特に il/elle, ils/elles の扱い）
- データ構造上は正しくても、学習者が混乱する活用形でないか
- ç の使用（commençons など）が正しいか
- -ger 動詞の nous 形（mangeons など）が正しいか

出力形式（JSON のみ。説明文は不要）:
{
  "errors": [
    {
      "file": "ファイルパス",
      "verb": "動詞名",
      "pronoun": "人称",
      "value": "問題のある値",
      "reason": "問題の説明",
      "suggestion": "修正案"
    }
  ],
  "warnings": [
    {
      "file": "ファイルパス",
      "verb": "動詞名",
      "pronoun": "人称（省略可）",
      "reason": "疑義の説明",
      "action": "確認が必要な点"
    }
  ],
  "suggestions": [
    {
      "file": "ファイルパス（省略可）",
      "verb": "動詞名（省略可）",
      "reason": "改善提案の説明"
    }
  ]
}

- error: マージ前に必ず修正すべき誤り（LLMの確信度が高い場合のみ）
- warning: 人間確認が必要な疑義（LLMが確信を持てない場合はこちら）
- suggestion: 改善提案（必須ではない）

LLMの判断は Layer 2 の参考情報です。error であっても人間レビューを経てください。
"""

USER_PROMPT_TEMPLATE = """\
以下はPRで変更された backend/app/domain 配下のファイルのdiffです。
フランス語として正確かどうかを検証してください。

変更対象ファイル: {changed_files}

diff:
```
{git_diff}
```

現在の CONJUGATIONS データ（変更後スナップショット）:
```json
{conjugations_json}
```
"""

MAX_DIFF_CHARS = 40_000


def run(cmd: list[str], **kwargs: object) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.stdout


def get_changed_domain_files(base_sha: str) -> list[str]:
    output = run(["git", "diff", "--name-only", f"{base_sha}...HEAD", "--", DOMAIN_PATH])
    return [f for f in output.strip().splitlines() if f]


def get_domain_diff(base_sha: str) -> str:
    diff = run(["git", "diff", f"{base_sha}...HEAD", "--", DOMAIN_PATH])
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n... (truncated)"
    return diff


def load_conjugations_json() -> str:
    json_path = Path(DOMAIN_PATH) / "french_reference" / "present_conjugations.json"
    if json_path.exists():
        return json_path.read_text(encoding="utf-8")
    return "{}"


def call_anthropic(api_key: str, system: str, user: str) -> dict:
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return body


def extract_json_from_response(body: dict) -> dict | None:
    text = body.get("content", [{}])[0].get("text", "")
    # Strip markdown code fences if present
    stripped = text.strip()
    for fence in ("```json", "```"):
        if stripped.startswith(fence):
            stripped = stripped[len(fence):]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
            stripped = stripped.strip()
            break
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def format_markdown(review: dict, changed_files: list[str]) -> str:
    lines = [
        COMMENT_MARKER,
        "## フランス語ドメインデータ LLMレビュー結果",
        "",
        f"**対象ファイル**: {', '.join(f'`{f}`' for f in changed_files)}",
        "",
    ]

    errors = review.get("errors", [])
    warnings = review.get("warnings", [])
    suggestions = review.get("suggestions", [])

    lines.append("### errors")
    if errors:
        for e in errors:
            verb = e.get("verb", "")
            pronoun = e.get("pronoun", "")
            value = e.get("value", "")
            reason = e.get("reason", "")
            suggestion = e.get("suggestion", "")
            location = " / ".join(p for p in [verb, pronoun] if p)
            lines.append(f"- **`{location}`** (`{value}`): {reason}")
            if suggestion:
                lines.append(f"  - 修正案: `{suggestion}`")
    else:
        lines.append("なし")

    lines.append("")
    lines.append("### warnings")
    if warnings:
        for w in warnings:
            verb = w.get("verb", "")
            pronoun = w.get("pronoun", "")
            reason = w.get("reason", "")
            action = w.get("action", "")
            location = " / ".join(p for p in [verb, pronoun] if p)
            label = f"`{location}`" if location else "(全般)"
            lines.append(f"- {label}: {reason}")
            if action:
                lines.append(f"  - 要確認: {action}")
    else:
        lines.append("なし")

    lines.append("")
    lines.append("### suggestions")
    if suggestions:
        for s in suggestions:
            verb = s.get("verb", "")
            reason = s.get("reason", "")
            label = f"`{verb}`" if verb else "(全般)"
            lines.append(f"- {label}: {reason}")
    else:
        lines.append("なし")

    lines.append("")
    lines.append(
        "> LLMレビューは Layer 2 の参考情報です。error があっても人間レビューを経てください。"
    )

    return "\n".join(lines)


def format_unparseable_warning(changed_files: list[str]) -> str:
    return "\n".join([
        COMMENT_MARKER,
        "## フランス語ドメインデータ LLMレビュー結果",
        "",
        f"**対象ファイル**: {', '.join(f'`{f}`' for f in changed_files)}",
        "",
        "> ⚠️ LLMレビューの出力をJSONとして解析できませんでした。レビュー不能です。",
        "> 手動で確認してください。",
    ])


def github_api(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} → {exc.code}: {body}") from exc


def find_existing_comment(repo: str, pr_number: int, token: str) -> int | None:
    page = 1
    while True:
        comments = github_api(
            "GET",
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}",
            token,
        )
        if not isinstance(comments, list) or not comments:
            return None
        for comment in comments:
            if COMMENT_MARKER in comment.get("body", ""):
                return comment["id"]
        if len(comments) < 100:
            return None
        page += 1


def post_or_update_comment(repo: str, pr_number: int, token: str, body: str) -> None:
    existing_id = find_existing_comment(repo, pr_number, token)
    if existing_id:
        github_api(
            "PATCH",
            f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}",
            token,
            {"body": body},
        )
        print(f"Updated existing PR comment #{existing_id}")
    else:
        github_api(
            "POST",
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
            token,
            {"body": body},
        )
        print("Created new PR comment")


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number_str = os.environ.get("GITHUB_PR_NUMBER", "")
    base_sha = os.environ.get("BASE_SHA", "origin/main")
    fail_on_error = os.environ.get("LLM_DOMAIN_REVIEW_FAIL_ON_ERROR", "false").lower() == "true"

    if not api_key:
        print("ANTHROPIC_API_KEY is not set — skipping LLM domain review.")
        return 0

    # Resolve base SHA if symbolic
    try:
        base_sha = run(["git", "rev-parse", base_sha]).strip()
    except RuntimeError:
        print(f"Cannot resolve base SHA '{base_sha}' — skipping.")
        return 0

    changed_files = get_changed_domain_files(base_sha)
    if not changed_files:
        print("No domain files changed — skipping LLM review.")
        return 0

    print(f"Domain files changed: {changed_files}")

    diff = get_domain_diff(base_sha)
    conjugations_json = load_conjugations_json()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        changed_files=", ".join(changed_files),
        git_diff=diff,
        conjugations_json=conjugations_json,
    )

    print("Calling Anthropic API...")
    try:
        response_body = call_anthropic(api_key, SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        print(f"Anthropic API call failed: {exc}")
        comment_body = format_unparseable_warning(changed_files)
        if github_token and repository and pr_number_str:
            post_or_update_comment(repository, int(pr_number_str), github_token, comment_body)
        return 0  # API failure is not a blocking error

    review = extract_json_from_response(response_body)
    if review is None:
        print("Failed to parse LLM response as JSON.")
        comment_body = format_unparseable_warning(changed_files)
        if github_token and repository and pr_number_str:
            post_or_update_comment(repository, int(pr_number_str), github_token, comment_body)
        return 0

    errors = review.get("errors", [])
    warnings = review.get("warnings", [])
    suggestions = review.get("suggestions", [])
    print(f"Review: {len(errors)} error(s), {len(warnings)} warning(s), {len(suggestions)} suggestion(s)")

    comment_body = format_markdown(review, changed_files)
    if github_token and repository and pr_number_str:
        post_or_update_comment(repository, int(pr_number_str), github_token, comment_body)
    else:
        print("GitHub env vars not set — printing comment to stdout:")
        print(comment_body)

    if fail_on_error and errors:
        print(f"Failing CI: {len(errors)} error(s) found and LLM_DOMAIN_REVIEW_FAIL_ON_ERROR=true")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
