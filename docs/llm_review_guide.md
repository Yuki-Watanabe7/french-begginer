# フランス語ドメインデータ LLMレビュー方針

## 概要

`backend/app/domain/` 配下のフランス語学習データは、学習者に提示する正解データであるため、品質保証が特に重要です。本ドキュメントでは、LLMによる自動レビューの導入方針・実装・運用手順を定義します。

## 品質ゲートの多層構造

```
Layer 1: 機械的構造検証 (pytest / CI)     ← 実装済み
  └─ tests/test_domain_validation.py
     - キー整合性チェック
     - 6人称の完全性チェック
     - Unicode NFC正規化チェック
     - golden fileとの照合

Layer 2: LLMによるフランス語正確性レビュー ← 実装済み（scripts/llm_domain_review.py）
  └─ PR差分に対してLLM APIを呼び出し
     - 活用形の言語的正確性
     - アクセント・表記の適切性
     - A1/A2レベルとしての妥当性

Layer 3: 人間によるネイティブレビュー    ← 必要に応じて実施
  └─ 疑義が生じた場合の最終判断
```

LLMレビューはLayer 1の通過後に実施し、LLMの判定単独でマージをブロックしない。
Layer 2で `error` が出た場合は人間によるLayer 3レビューを必須とする。

---

## elision・表記責務の分界

### ドメインデータの方針

`CONJUGATIONS` は **活用形のみ** を保持します。主語との結合（elision）は表示層の責務です。

| 動詞 | 人称 | CONJUGATIONS の値 | 表示層での結合例 |
|------|------|-------------------|-----------------|
| écouter | je | `écoute` | `j'écoute` |
| avoir | je | `ai` | `j'ai` |
| être | je | `suis` | `je suis` |
| aller | je | `vais` | `je vais` |

### elision規則（表示層実装時の参考）

1. `je` + 母音始まりの活用形 → `j'` + 活用形（例: `j'écoute`, `j'ai`）
2. `je` + 子音始まりの活用形 → `je ` + 活用形（例: `je suis`, `je vais`）
3. `me`, `te`, `se`, `le`, `la`, `de`, `ne`, `que` も同様にelision対象

### CI検証の注意

`test_domain_validation.py` はドメインデータ単体（活用形のみ）を検証します。
表示文生成（elision適用後）の正確性は別途テストすること。

---

## GitHub Actions 設定

### 必要なSecrets

| Secret名 | 内容 | 設定箇所 |
|----------|------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API キー | Repository Settings → Secrets and variables → Actions |

`GITHUB_TOKEN` はActionsが自動で提供するため設定不要。

### ワークフローファイルの追加

以下の内容で `.github/workflows/llm-domain-review.yml` を作成してください。

```yaml
name: LLM Domain Review

on:
  pull_request:
    branches: [main]
    paths:
      - "backend/app/domain/**"

jobs:
  backend-domain-llm-review:
    name: Backend domain LLM review
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install backend dependencies
        working-directory: backend
        run: uv sync --extra dev

      - name: Run existing pytest (Layer 1)
        working-directory: backend
        run: uv run pytest tests/test_domain_validation.py -v

      - name: Run LLM domain review (Layer 2)
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_PR_NUMBER: ${{ github.event.pull_request.number }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          LLM_DOMAIN_REVIEW_FAIL_ON_ERROR: "false"
        run: python scripts/llm_domain_review.py
```

### 設定パラメーター

| 環境変数 | デフォルト | 説明 |
|----------|-----------|------|
| `ANTHROPIC_API_KEY` | （必須） | 未設定の場合はLLMレビューをスキップ |
| `LLM_DOMAIN_REVIEW_FAIL_ON_ERROR` | `"false"` | `"true"` にすると `errors` 検出時にCI失敗 |
| `BASE_SHA` | `origin/main` | diff の起点コミット（Actions では自動設定） |

---

## CI失敗条件

| 状況 | デフォルト挙動 | `FAIL_ON_ERROR=true` 時 |
|------|--------------|------------------------|
| `errors` 検出 | CIは通過（PRコメントに記載） | CI失敗 |
| `warnings` 検出 | CIは通過（PRコメントに記載） | CIは通過 |
| `suggestions` のみ | CIは通過（PRコメントに記載） | CIは通過 |
| LLM出力がJSONでない | CIは通過（warningコメント） | CIは通過 |
| `ANTHROPIC_API_KEY` 未設定 | スキップ（CIは通過） | スキップ（CIは通過） |

初期段階では `FAIL_ON_ERROR=false` を推奨。LLMレビューが安定した後に `true` に変更する。

---

## PRコメント方針

- スクリプトは `<!-- llm-domain-review-v1 -->` マーカーを使い既存コメントを検索する
- 同一PRで再実行した場合、コメントは **増殖せず更新される**
- `errors` / `warnings` / `suggestions` の分類と、該当動詞・人称が明示される

---

## LLMレビュープロンプト雛形

`scripts/llm_domain_review.py` に組み込み済みです。詳細はスクリプト本体を参照。

### システムプロンプトの確認観点

- 動詞活用が標準フランス語として正しいか
- アクセント記号（é, è, ê, à, â, î, ô, û, ù, ç など）が正しいか
- 初級教材（A1/A2レベル）として適切な動詞・活用形か
- 同じ概念に対する表記揺れがないか（特に il/elle, ils/elles の扱い）
- ç の使用（commençons など）が正しいか
- -ger 動詞の nous 形（mangeons など）が正しいか

### ユーザープロンプト構成

1. 変更対象ファイルリスト
2. `git diff` の出力（40,000文字で切り捨て）
3. `french_reference/present_conjugations.json` の現在の内容

---

## golden file の更新手順

`backend/app/domain/french_reference/present_conjugations.json` は、
フランス語として正確であることが確認済みの活用形参照データです。

### 更新が必要な場合

1. 新しい動詞を追加する場合は、`CONJUGATIONS` と同時に golden file も更新する
2. 既存の活用形を修正する場合は、golden file の差分が PR 上で明示される
3. golden file の変更は **必ずネイティブまたは専門家によるレビューを受けること**

### 対象動詞の追加時のチェックリスト

- [ ] `VERB_METADATA` にlevel/patternを追加
- [ ] `VERB_GROUPS` にグループ（er/ir/irregular）を追加
- [ ] `CONJUGATIONS` に6人称の現在形を追加
- [ ] `french_reference/present_conjugations.json` に golden data を追加
- [ ] `uv run pytest` がすべて通ることを確認

---

## 実装ステップ（現在の状態）

### Phase 1（完了）: 機械的検証
- `tests/test_domain_validation.py` による構造検証
- `french_reference/present_conjugations.json` による golden file 照合
- 既存CIの `uv run pytest` に自動的に含まれる

### Phase 2（完了）: GitHub Actions での差分抽出 + LLMレビュー
- `scripts/llm_domain_review.py` を実装
- `.github/workflows/llm-domain-review.yml` を追加（上記「ワークフローファイルの追加」参照）
- `backend/app/domain/**` 変更時のみ動作するpath filterを設定

### Phase 3: required check化の検討
- LLMレビューが安定動作を確認後、`LLM_DOMAIN_REVIEW_FAIL_ON_ERROR=true` に変更
- `errors` 検出時のCI失敗を必須 check に昇格させることを検討
