# フランス語ドメインデータ LLMレビュー方針

## 概要

`backend/app/domain/` 配下のフランス語学習データは、学習者に提示する正解データであるため、品質保証が特に重要です。本ドキュメントでは、LLMによる自動レビューの導入方針と、将来的な実装に向けたプロンプト雛形を定義します。

## 品質ゲートの多層構造

```
Layer 1: 機械的構造検証 (pytest / CI)     ← 現在実装済み
  └─ tests/test_domain_validation.py
     - キー整合性チェック
     - 6人称の完全性チェック
     - Unicode NFC正規化チェック
     - golden fileとの照合

Layer 2: LLMによるフランス語正確性レビュー ← 本ドキュメントで設計
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

## LLMレビュープロンプト雛形

将来的に GitHub Actions からLLM APIを呼び出す際に使用するプロンプトです。

### システムプロンプト

```
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

出力形式（JSON）:
{
  "errors": [
    {
      "verb": "動詞名",
      "pronoun": "人称",
      "value": "問題のある値",
      "reason": "問題の説明",
      "suggestion": "修正案"
    }
  ],
  "warnings": [
    {
      "verb": "動詞名",
      "pronoun": "人称（省略可）",
      "reason": "疑義の説明",
      "action": "確認が必要な点"
    }
  ],
  "suggestions": [
    {
      "verb": "動詞名（省略可）",
      "reason": "改善提案の説明"
    }
  ]
}

- error: マージ前に必ず修正すべき誤り（LLMの確信度が高い場合のみ）
- warning: 人間確認が必要な疑義（LLMが確信を持てない場合はこちら）
- suggestion: 改善提案（必須ではない）

LLMの判断は Layer 2 の参考情報です。error であっても人間レビューを経てください。
```

### ユーザープロンプトテンプレート

```
以下はPRで変更された backend/app/domain/conjugation.py のdiff（present_conjugations.json を含む）です。
フランス語として正確かどうかを検証してください。

変更対象ファイル: {changed_files}

diff:
{git_diff}

現在の CONJUGATIONS データ（変更後）:
{conjugations_json}
```

---

## 将来の実装ステップ

### Phase 1（現在）: 機械的検証のみ
- `tests/test_domain_validation.py` による構造検証
- `french_reference/present_conjugations.json` による golden file 照合
- 既存CIの `uv run pytest` に自動的に含まれる

### Phase 2: GitHub Actions での差分抽出
```yaml
# .github/workflows/ci.yml に追加予定（要権限）
- name: Backend domain data validation
  if: contains(github.event.pull_request.labels.*.name, 'domain-change')
  run: |
    git diff origin/main...HEAD -- backend/app/domain/ > /tmp/domain_diff.txt
    uv run pytest tests/test_domain_validation.py -v
```

または path filter を使用:
```yaml
jobs:
  domain-validation:
    name: Backend domain data validation
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    # path filtering は paths-filter action などで実現
```

### Phase 3: LLM API 呼び出し

```python
# scripts/llm_domain_review.py（設計メモ）
#
# 1. git diff で backend/app/domain/ の変更を取得
# 2. 上記プロンプトテンプレートに差分を埋め込む
# 3. Anthropic API (Claude) を呼び出す
# 4. errors があればCI失敗・PR コメントで報告
# 5. warnings はPRコメントで報告（CIは通過させる）
#
# 注意:
# - LLM単独でのマージブロックは行わない
# - Layer 1（pytest）が通過している前提で実行
# - API呼び出しコストを考慮し、domain変更がある場合のみ実行
```

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
