# Tutor LLM抽出の品質検証方針（Issue #136）

LLM抽出の品質を「その時の目視」だけに依存させない。
固定 Source fixture と deterministic なチェックを主、実 LLM 実行を補助とする。

既存のフランス語 domain 品質方針（[llm_review_guide.md](./llm_review_guide.md)）と同じく、
**LLM-as-judge を唯一の pass/fail 根拠にしない。**

## 評価するもの / しないもの

評価する:

- 原文忠実性（evidence が本文から復元できること）
- 学習対象としての再利用価値（must-have の phrase / lemma）
- 構造化契約（item_type、必須フィールド、件数上限）
- evidence 整合性
- 重複抑止
- 明白な hallucination（本文にない表現の創作）
- 過剰抽出（特に初級の短文）

評価しない（減点理由にしない）:

- 「初学者には混乱する」
- 「不規則活用である」
- 「A1 には難しい」
- prompt の文体や説明の上手さそのもの

## 固定 fixture

定義: `backend/app/evaluation/extraction_fixtures.py`

期待値は完全一致リストではない。must-include / must-not-hallucinate /
acceptable variants を分けて持つ。

| ID | 目的 | Source | must-have 例 | 見てほしい失敗 |
|----|------|--------|--------------|----------------|
| A | 表現 + 文法 + 語彙 | `Je me suis rendu compte qu'il fallait changer de stratégie.` | `se rendre compte de`（expression、`se rendre compte` も可） / `il faut` または `falloir`（grammar or conjugation） / `stratégie`（vocabulary） | 本文にない `bonjour` 等の創作 |
| B | 初級の短文 | `Je mange une pomme.` | `pomme` / `manger` | 4語から候補を大量に作る、本文にない表現の持ち込み。上限 6 件 |
| C | 複数の再利用表現 | `Il s'agit de prendre rendez-vous. Il vaut mieux y aller tout de suite.` | `il s'agit de` / `prendre rendez-vous` / `il vaut mieux` | `rendez-vous` を語彙として拾うだけで phrase を落とす |
| D | 不規則活用・文法 | `Je suis allé à Paris et j'ai fait un gâteau.` | `aller` / `faire`（conjugation） / `passé composé`（grammar） | `allé` を vocabulary の表層形としてだけ拾う。正しい不規則活用を減点しない |

## deterministic checks

実装: `backend/app/evaluation/extraction_quality.py`

抽出結果に対して次を機械的に検証する。同じ入力からは常に同じレポートになる。

| チェック | 内容 |
|----------|------|
| evidence span が原文範囲内 | `0 <= start < end <= len(content)` |
| evidence が原文から復元可能 | `content[start:end]` と一致し、空白のみではない |
| unknown item_type なし | `vocabulary` / `expression` / `grammar` / `conjugation` のみ |
| required fields | `canonical_form` / `meaning_ja` / `extraction_version` / `evidence_span` |
| duplicate key なし | `item_normalization_key` が kept 候補で一意 |
| 件数上限 | `MAX_CANDIDATES`（20）以内。fixture ごとの過剰抽出上限は別 |
| 明白な hallucination | fixture の must-not に一致、または複数語で本文と語が重ならない |

単一 lemma（`être` / `aller` / `faire` 等）は表層形と一致しないことがある。
これを hallucination にはしない。fixture の must-have / must-not で見る。

## 実 LLM 評価の実行方法

通常の unit test は API key なしで通る。実 LLM は次のいずれかに分離する。

```bash
cd backend
uv run python ../scripts/evaluate_tutor_extraction.py
uv run python ../scripts/evaluate_tutor_extraction.py --fixture A --json
uv run python ../scripts/evaluate_tutor_extraction.py --strict
RUN_LIVE_LLM=1 uv run pytest -m live_llm
```

`--json` は `provider` / `model` / `extraction_version`（prompt version）を残す。
`--strict` は contract 失敗または must-have 欠落で終了コード 1。
デフォルトの終了コードは「評価を実行できたか」であり、品質スコアそのものでは落さない。

`OPENAI_API_KEY` が無い場合は実行できない旨を出して終了する。
CI の `pytest` はこのスクリプトを呼ばない。

## 回帰保護

過去の LLM Domain Review で、正しい不規則活用が「初学者には混乱する」として
誤警告されたことがある。抽出品質でも同じ基準を品質ゲートにしない。
