# フランス語ドメインデータ LLMレビュー方針

## 概要

`backend/app/domain/` 配下のフランス語学習データは、学習者に提示する正解データであるため、品質保証が特に重要です。本ドキュメントでは、LLMによる自動レビューの導入方針を定義します。

## LLMレビューの基本方針

LLM Domain Review は **「標準フランス語としての正誤」** を主対象とする。

- **正しい不規則活用は学習対象であり、避ける対象ではない。**
  `partir → il/elle part`、`sortir → il/elle sort`、`dormir → il/elle dort` のような
  語幹変化を伴う活用は正しいフランス語であり、指摘してはならない。
- 初学者に難しい、不規則である、混乱し得る、という理由だけではwarningにしない。
- warningには具体的な根拠・代替案（expected）・確認観点が必要である。

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
     - 活用形の言語的正確性（標準フランス語としての正誤）
     - アクセント・表記の適切性

Layer 3: 人間によるネイティブレビュー    ← 必要に応じて実施
  └─ 疑義が生じた場合の最終判断
```

LLMレビューはLayer 1の通過後に実施し、LLMの判定単独でマージをブロックしない。
Layer 2で `error` が出た場合は人間によるLayer 3レビューを必須とする。

## warning基準

### warningを出してよい条件

- 標準形として複数の許容表記があり得る場合（具体的な代替形を `expected` に示すこと）
- 地域差・文体差として採用可否を確認すべき場合
- 辞書・文法書等で確認すべき具体的な根拠がある場合

### warningとして禁止する条件

以下の理由のみではwarningにしない:

| 禁止理由 | 例 |
|----------|-----|
| 初学者が混乱する可能性 | "A1/A2レベルには難しい" |
| 不規則活用である | "不規則な語幹変化がある" |
| 語幹変化がある | "見慣れない形" |
| 根拠のない標準性疑義 | "標準的でない可能性がある" + expected なし |

### 後処理フィルタリング

`scripts/llm_domain_review.py` の `filter_warnings()` が以下を自動除外する:

1. reason に「混乱」「初学者」「初級」「初心者」を含み、`expected` がない警告
2. `value` を指定し「使用されない」「正しくない」等を主張するが `expected` がない警告
3. `value == expected` の無意味な警告
4. `confidence: low` の警告（suggestions に降格）
5. `expected` が不定詞（`verb` 名そのもの）の警告（活用形の代替になっていない）
6. 現在形が標準・正しいと述べるだけで、別の活用形を示さない警告

活用データ（`conjugation.py` / `present_conjugations.json`）が変わっていない PR では、
CONJUGATIONS 全体のスナップショットを LLM に渡さない。diff 外の動詞を再レビューさせない。

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

## LLMレビュープロンプト（現行）

実際のプロンプトは `scripts/llm_domain_review.py` の `SYSTEM_PROMPT` を参照してください。
以下は概要です。

### 確認観点（正誤のみ）

- 動詞活用が標準フランス語として正しいか
- アクセント記号（é, è, ê, à, â, î, ô, û, ù, ç など）が正しいか
- 同じ概念に対する表記揺れがないか
- ç の使用（commençons など）が正しいか
- -ger 動詞の nous 形（mangeons など）が正しいか

`commençons` / `mangeons` は標準形である。正しいと確認した事実や
地域差確認だけを理由に warning にしない。活用スロットの `expected` に
不定詞を書かない。diff に含まれない CONJUGATIONS 項目は対象外。

### JSON出力スキーマ

```json
{
  "errors": [
    {
      "verb": "動詞名",
      "pronoun": "人称",
      "value": "問題のある値",
      "expected": "正しいと考える形（必須）",
      "reason": "問題の説明",
      "suggestion": "修正案",
      "confidence": "high"
    }
  ],
  "warnings": [
    {
      "verb": "動詞名",
      "pronoun": "人称（省略可）",
      "value": "疑義のある値（省略可）",
      "expected": "正しいと考える代替形（あれば必ず記入）",
      "reason": "疑義の説明",
      "action": "確認が必要な点",
      "confidence": "low|medium|high"
    }
  ],
  "suggestions": [
    {
      "verb": "動詞名（省略可）",
      "reason": "改善提案の説明"
    }
  ]
}
```

### ユーザープロンプトテンプレート

```
以下はPRで変更された backend/app/domain/conjugation.py のdiff（present_conjugations.json を含む）です。
フランス語として正確かどうかを検証してください。

変更対象ファイル: {changed_files}

diff:
{git_diff}

{conjugations_section}
```

`conjugations_section` は活用データが変わったときだけ JSON スナップショット。
未変更なら「CONJUGATIONS 全体の再レビューは不要」と明記する。

---

## 実装状況

### Phase 1（実装済み）: 機械的検証

- `tests/test_domain_validation.py` による構造検証
- `french_reference/present_conjugations.json` による golden file 照合
- 既存CIの `uv run pytest` に自動的に含まれる

### Phase 2（実装済み）: LLM API レビュースクリプト

`scripts/llm_domain_review.py` が実装済みです。

#### 必要な Secrets

| Secret | 用途 |
|--------|------|
| `OPENAI_API_KEY` | OpenAI API使用時（デフォルト） |
| `ANTHROPIC_API_KEY` | Anthropic API使用時 |
| `GITHUB_TOKEN` | PRコメント投稿（GitHub Actionsが自動提供） |

#### 環境変数（設定オプション）

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `LLM_PROVIDER` | `openai` | `openai` または `anthropic` |
| `LLM_MODEL` | `gpt-4o-mini`（OpenAI）/ `claude-sonnet-4-6`（Anthropic） | 使用するモデル |
| `BASE_SHA` | `origin/main` | 差分の起点コミット |
| `LLM_DOMAIN_REVIEW_FAIL_ON_ERROR` | `false` | `true` にすると errors 検出時にCI失敗 |

#### CI失敗条件

| 状況 | 挙動 |
|------|------|
| APIキー未設定 | スキップ（CIは成功） |
| domain変更なし | スキップ（LLM APIを呼ばない） |
| LLM出力がJSON不正 | warningコメント投稿、CIは成功 |
| `errors` あり + `FAIL_ON_ERROR=false` | コメント投稿、CIは成功 |
| `errors` あり + `FAIL_ON_ERROR=true` | コメント投稿、CIは失敗 |
| `warnings` / `suggestions` のみ | コメント投稿、CIは成功 |

#### PRコメント再利用方針

コメント本文に `<!-- llm-domain-review-v1 -->` マーカーを埋め込み、同一PRでの再実行時は既存コメントを更新します（コメント増殖なし）。


### Phase 3: ネイティブ人間レビュー（別Issue）

LLM レビューは Layer 2 の参考情報であり、最終判断は人間レビューです。
`error` が検出された場合は Layer 3 のネイティブレビューを推奨します。

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
