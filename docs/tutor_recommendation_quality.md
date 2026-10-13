# Tutor 推薦品質の検証方針（Issue #180）

Tutor ranking / Daily Learning Plan が「もっともらしく見える」だけでなく、
入力 signal が変わったときに期待方向へ順位・配分が変わることを、
固定 fixture で継続検証する。

抽出品質（[tutor_extraction_quality.md](./tutor_extraction_quality.md)）と同じく、
**LLM-as-judge を唯一の pass/fail 根拠にしない。**
Phase 5 では反実仮想（counterfactual）テストを中心にする。

score の絶対値を大量に golden 固定しない。見るのは **順位・reason・制約の不変条件**。

## 評価するもの / しないもの

評価する:

- overdue review が interest / recency の新規より優先されること
- recognition / production の imbalance が弱い方向を上げること
- 直近誤答が同条件 Item の優先度を上げること
- CEFR level fit が補助 signal として働くこと（遠い level を自動排除しない）
- due overload / under capacity の件数配分
- reason code が実 signal と矛盾しないこと
- inactive / mastered / Exercise 生成不能を公開 plan に入れないこと

評価しない（減点理由にしない）:

- score の絶対値そのもの
- LLM による「この推薦は自然か」という感想
- 大規模ユーザー実験 / online A/B / FSRS 評価

## 固定 fixture

定義: `backend/app/evaluation/recommendation_fixtures.py`

複数 LearningItem を持つ synthetic learner。実利用データは使わない。

| ID | 目的 | 構成 | 期待 |
|----|------|------|------|
| A | overdue vs recent new | 3日 overdue の復習 + 今日追加の高 interest 新規 | overdue が上位。interest だけで due を押しのけない |
| B | recognition / production | 同一 Item で recognition 高・production 低 + 直近誤答 | production が上位。`PRODUCTION_WEAKER` / `RECENT_ERROR` |
| C | recent error | ほぼ同条件の 2 Item。一方だけ直近誤答 | 誤答側の優先度が上がる |
| D | level fit | A1 learner に A1 / A2 / B2 / unknown | level fit は補助。B2 を排除しない。unknown を極端に罰しない |
| E | due overload | due 15 / capacity 10 / new 複数 | review 10、new 0、`deferred_due_count=5` |
| F | due under capacity | due 4 / capacity 10 / max new 3 | due 4 + new 最大 3。同一 Item で水増ししない |
| INV | 除外 | suspended / mastered / 生成不能 conjugation | plan に入らず skip 理由付き |

## counterfactual

同じ baseline から signal を 1 つだけ変える。実装:
`COUNTERFACTUAL_CASES`（`recommendation_fixtures.py`）。

| ID | 変更 | 期待方向 |
|----|------|----------|
| `interest-neutral-to-high` | interest 1.0 → 3.0 | 当該 new item の順位が上がる |
| `error-none-to-recent` | 直近誤答なし → あり | 当該 review の順位が上がる |
| `future-to-overdue` | future → overdue | review として現れ、新規より上 |
| `production-mastery-drop` | production mastery 0.8 → 0.3 | production が recognition より上がる |
| `high-interest-still-below-overdue` | 新規の interest を最大 | それでも overdue review より下 |

## invariants

評価ハーネス（`recommendation_quality.py`）が毎回見る。

- 同じ snapshot / 同じ now なら同順位
- due review が new_practice より後ろに来ない
- `max_new_count` と plan capacity
- `deferred_due_count` と件数期待値
- unseen を `LOW_MASTERY` にしない
- reason code が実 signal と矛盾しない
- neutral interest で `HIGH_INTEREST` を出さない
- recognition の誤答で production の `RECENT_ERROR` を捏造しない
- inactive / mastered を plan に入れない
- Exercise 生成不能は skip 理由付き

## policy snapshot

評価結果に残す:

- `feature_version`（signal-v2。横断苦手 hint を足した版。空なら従来の特徴量）
- ranking `policy_version`（ranking-v2。`pattern_weakness` は独立 component）
- plan `policy_version`（plan-v1）
- fixture name
- ranked IDs / reason codes（必要なら plan entries）

将来 weight を変えたときに「何が変わったか」を見比べるため。
テストは絶対 score を golden 固定しない。

## 実行方法

通常の unit test は API key なしで通る。CI の `pytest` が主ゲート。

任意でレポートを出す:

```bash
cd backend
uv run python ../scripts/evaluate_tutor_recommendations.py
uv run python ../scripts/evaluate_tutor_recommendations.py --fixture A --json
uv run python ../scripts/evaluate_tutor_recommendations.py --strict
```

このスクリプトは LLM を呼ばない。`--strict` は不変条件失敗で終了コード 1。
デフォルトの終了コードは「評価を実行できたか」であり、表示用。

実利用データを匿名化した offline evaluation や LLM-as-judge は将来拡張できるが、
Phase 5 では非対象。pass/fail の唯一の根拠にはしない。
