#!/usr/bin/env python3
"""
LLM-based French domain data review for PR diffs.

Extracts changed files in backend/app/domain/, calls the LLM API to review
French accuracy, and posts results as a PR comment (updating instead of
duplicating on re-runs).

Required env vars:
  GITHUB_TOKEN                   GitHub token (needs issues:write)
  GITHUB_REPOSITORY              "owner/repo"
  GITHUB_PR_NUMBER               PR number as string

API provider selection (default: openai):
  LLM_PROVIDER                   "openai" (default) or "anthropic"

For OpenAI (default):
  OPENAI_API_KEY                 OpenAI API key
  LLM_MODEL                      Model name (default: "gpt-4o-mini")

For Anthropic:
  ANTHROPIC_API_KEY              Anthropic API key
  LLM_MODEL                      Model name (default: "claude-sonnet-4-6")

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
フランス語として正確かどうかを検証してください。

【重要な前提】
- CONJUGATIONS の値は「活用形のみ」です（主語付き表現ではありません）
- 例: écouter/je = "écoute"（"j'écoute" ではない）
- elision は表示層で処理されます

【確認対象】
確認対象は「標準フランス語としての正誤」に限定する。
不規則活用・語幹変化・初学者に難しい活用形であること自体をwarningにしてはならない。
正しい活用であれば、初学者にとって難しい・混乱しやすいという理由で指摘しない。

確認観点:
- 動詞活用が標準フランス語として正しいか
- アクセント記号（é, è, ê, à, â, î, ô, û, ù, ç など）が正しいか
- 同じ概念に対する表記揺れがないか（特に il/elle, ils/elles の扱い）
- ç の使用（commençons など）が正しいか
- -ger 動詞の nous 形（mangeons など）が正しいか

【正しい標準形 — warning にしてはならない】
- commencer/nous = commençons（ç は標準綴り）
- manger/nous = mangeons（-ger 動詞の e 保持は標準綴り）
- 上の形が正しいと確認した事実や、地域差・文体差の確認だけを理由に warning にしない
- 活用スロットの expected には活用形を書く。不定詞（動詞名そのもの）を expected にしない
- 今回の diff に含まれない CONJUGATIONS 項目はレビュー対象外

【warningを出してよい条件】
- 標準形として複数の許容表記があり得る場合（具体的な代替形を expected に示すこと）
- 地域差・文体差として採用可否を確認すべき場合
- 辞書・文法書で確認すべき具体的な根拠がある場合

【warningとして禁止する条件 - 以下の理由だけではwarningにしないこと】
- 初学者が混乱する可能性がある
- 不規則活用である
- 語幹変化がある
- 見慣れない形である
- 「標準的でない」「使用されない」と主張するが、具体的な代替正答（expected）を提示できない
- partir→part、sortir→sort、dormir→dort など正しい不規則活用を疑問視する

出力形式（JSON のみ。説明文は不要）:
{
  "errors": [
    {
      "file": "ファイルパス",
      "verb": "動詞名",
      "pronoun": "人称",
      "value": "問題のある値",
      "expected": "正しいと考える形（必須）",
      "reason": "問題の説明（具体的な根拠を含むこと）",
      "suggestion": "修正案",
      "confidence": "high"
    }
  ],
  "warnings": [
    {
      "file": "ファイルパス",
      "verb": "動詞名",
      "pronoun": "人称（省略可）",
      "value": "疑義のある値（省略可）",
      "expected": "正しいと考える代替形（あれば必ず記入）",
      "reason": "疑義の説明（具体的な根拠を含むこと）",
      "action": "確認が必要な点",
      "confidence": "low|medium|high"
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

- error: マージ前に必ず修正すべき誤り（LLMの確信度が高い場合のみ。expected は必須）
- warning: 人間確認が必要な疑義（具体的な根拠と expected が必要。混乱・不規則のみを理由にしない）
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

{conjugations_section}
"""

MAX_DIFF_CHARS = 40_000

# Keywords that indicate a warning is only about beginner confusion, not correctness
_CONFUSION_KEYWORDS = frozenset(["混乱", "初学者", "初級", "初心者"])
# Keywords that indicate a warning claims a value is incorrect
_INCORRECTNESS_KEYWORDS = frozenset([
    "使用されない", "正しくない", "誤り", "間違い",
    "標準でない", "標準的でない", "存在しない", "使われない",
])

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"

CONJUGATION_SNAPSHOT_FILES = frozenset(
    {
        "backend/app/domain/conjugation.py",
        "backend/app/domain/french_reference/present_conjugations.json",
    }
)
"""活用表スナップショットを付けるのは、これらのファイルが変わったときだけ。"""

# 現在形が正しいと述べているだけの警告（PR #158 の false positive）
# 「正しい」単体は「正しくない」に部分一致するため使わない。
_AFFIRMATION_PHRASES = (
    "使用は正しい",
    "使用が正しい",
    "標準的であり",
    "標準的である",
    "とするのが標準",
)

_NO_CONJUGATION_SNAPSHOT_NOTE = (
    "今回の差分に活用データ（conjugation.py / "
    "present_conjugations.json）の変更はない。"
    "CONJUGATIONS 全体の再レビューは不要。"
    "diff に含まれるフランス語のみを対象にすること。"
)


def should_attach_conjugation_snapshot(changed_files: list[str]) -> bool:
    """活用データが変わっていない PR では CONJUGATIONS 全体を再レビューしない。"""
    return any(path in CONJUGATION_SNAPSHOT_FILES for path in changed_files)


def conjugation_section_for(changed_files: list[str]) -> str:
    """LLM に渡す活用表セクション。未変更ならスナップショットを付けない。"""
    if not should_attach_conjugation_snapshot(changed_files):
        return _NO_CONJUGATION_SNAPSHOT_NOTE
    return (
        "現在の CONJUGATIONS データ（変更後スナップショット）:\n"
        "```json\n"
        f"{load_conjugations_json()}\n"
        "```"
    )


def _normalize_form(text: str) -> str:
    return text.strip().casefold()


def _reason_affirms_current_form(reason: str) -> bool:
    return any(phrase in reason for phrase in _AFFIRMATION_PHRASES)


def filter_warnings(warnings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter low-quality LLM warnings.

    Returns (kept_warnings, demoted_to_suggestions).

    Removes:
    - Warnings whose reason only cites beginner confusion (not a correctness issue)
    - Warnings that claim a specific value is incorrect without providing an expected form
    - Warnings where value == expected (nonsensical)
    - Low-confidence warnings (moved to suggestions)
    - Warnings whose expected is the infinitive (verb name), not a conjugated form
    - Warnings that affirm the current form is standard/correct without an alternative
    """
    kept: list[dict] = []
    demoted: list[dict] = []

    for w in warnings:
        reason = w.get("reason", "")
        value = w.get("value", "")
        expected = w.get("expected", "")
        verb = w.get("verb", "")
        confidence = w.get("confidence", "medium")

        # Filter 1: reason only mentions beginner confusion — not a French correctness issue
        if any(kw in reason for kw in _CONFUSION_KEYWORDS):
            demoted.append(w)
            continue

        # Filter 2: claims a specific value is incorrect but provides no alternative
        if value and not expected and any(kw in reason for kw in _INCORRECTNESS_KEYWORDS):
            demoted.append(w)
            continue

        # Filter 3: value and expected are identical — nonsensical warning
        if value and expected and _normalize_form(value) == _normalize_form(expected):
            demoted.append(w)
            continue

        # Filter 4: low confidence — demote to suggestion
        if confidence == "low":
            demoted.append(w)
            continue

        # Filter 5: expected is the infinitive, not an alternative conjugated form
        if (
            verb
            and expected
            and _normalize_form(expected) == _normalize_form(verb)
        ):
            demoted.append(w)
            continue

        # Filter 6: affirms the current form is correct without a real alternative
        if value and _reason_affirms_current_form(reason):
            alternatives = {_normalize_form(value)}
            if verb:
                alternatives.add(_normalize_form(verb))
            if not expected or _normalize_form(expected) in alternatives:
                demoted.append(w)
                continue

        kept.append(w)

    return kept, demoted


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


def _http_post(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def call_openai(api_key: str, model: str, system: str, user: str) -> dict:
    return _http_post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload={
            "model": model,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )


def call_anthropic(api_key: str, model: str, system: str, user: str) -> dict:
    return _http_post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        payload={
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    )


def extract_text_from_openai(body: dict) -> str:
    return body.get("choices", [{}])[0].get("message", {}).get("content", "")


def extract_text_from_anthropic(body: dict) -> str:
    return body.get("content", [{}])[0].get("text", "")


def extract_json_from_text(text: str) -> dict | None:
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
            expected = e.get("expected", "")
            reason = e.get("reason", "")
            suggestion = e.get("suggestion", "")
            location = " / ".join(p for p in [verb, pronoun] if p)
            lines.append(f"- **`{location}`** (`{value}`): {reason}")
            if expected and expected != value:
                lines.append(f"  - 期待される形: `{expected}`")
            elif suggestion:
                lines.append(f"  - 修正案: `{suggestion}`")
    else:
        lines.append("なし")

    lines.append("")
    lines.append("### warnings")
    if warnings:
        for w in warnings:
            verb = w.get("verb", "")
            pronoun = w.get("pronoun", "")
            value = w.get("value", "")
            expected = w.get("expected", "")
            reason = w.get("reason", "")
            action = w.get("action", "")
            confidence = w.get("confidence", "")
            location = " / ".join(p for p in [verb, pronoun] if p)
            label = f"`{location}`" if location else "(全般)"
            val_part = f" (`{value}`)" if value else ""
            lines.append(f"- {label}{val_part}: {reason}")
            if expected and expected != value:
                lines.append(f"  - 期待される形: `{expected}`")
            if action:
                lines.append(f"  - 要確認: {action}")
            if confidence and confidence != "medium":
                lines.append(f"  - 確信度: {confidence}")
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
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number_str = os.environ.get("GITHUB_PR_NUMBER", "")
    base_sha = os.environ.get("BASE_SHA", "origin/main")
    fail_on_error = os.environ.get("LLM_DOMAIN_REVIEW_FAIL_ON_ERROR", "false").lower() == "true"

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        key_name = "ANTHROPIC_API_KEY"
        default_model = DEFAULT_ANTHROPIC_MODEL
    else:
        # Default: openai
        provider = "openai"
        api_key = os.environ.get("OPENAI_API_KEY", "")
        key_name = "OPENAI_API_KEY"
        default_model = DEFAULT_OPENAI_MODEL

    model = os.environ.get("LLM_MODEL", default_model)

    if not api_key:
        print(f"{key_name} is not set — skipping LLM domain review.")
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
    print(f"LLM provider: {provider}, model: {model}")

    diff = get_domain_diff(base_sha)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        changed_files=", ".join(changed_files),
        git_diff=diff,
        conjugations_section=conjugation_section_for(changed_files),
    )

    print(f"Calling {provider} API...")
    try:
        if provider == "anthropic":
            response_body = call_anthropic(api_key, model, SYSTEM_PROMPT, user_prompt)
            response_text = extract_text_from_anthropic(response_body)
        else:
            response_body = call_openai(api_key, model, SYSTEM_PROMPT, user_prompt)
            response_text = extract_text_from_openai(response_body)
    except Exception as exc:
        print(f"{provider} API call failed: {exc}")
        comment_body = format_unparseable_warning(changed_files)
        if github_token and repository and pr_number_str:
            post_or_update_comment(repository, int(pr_number_str), github_token, comment_body)
        return 0  # API failure is not a blocking error

    review = extract_json_from_text(response_text)
    if review is None:
        print("Failed to parse LLM response as JSON.")
        comment_body = format_unparseable_warning(changed_files)
        if github_token and repository and pr_number_str:
            post_or_update_comment(repository, int(pr_number_str), github_token, comment_body)
        return 0

    errors = review.get("errors", [])
    raw_warnings = review.get("warnings", [])
    suggestions = review.get("suggestions", [])

    kept_warnings, demoted = filter_warnings(raw_warnings)
    if demoted:
        print(f"Filtered {len(demoted)} low-quality warning(s) → moved to suggestions")
    demoted_suggestions = [
        {**w, "reason": f"[参考] {w.get('reason', '')}"}
        for w in demoted
    ]
    review["warnings"] = kept_warnings
    review["suggestions"] = suggestions + demoted_suggestions

    warnings = kept_warnings
    suggestions = review["suggestions"]
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
