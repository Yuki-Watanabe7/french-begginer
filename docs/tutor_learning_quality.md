# Tutor 学習品質の検証方針（Issue #206）

Phase 7 の admission、known skip、context rotation、弱点検出、負荷調整は、
個別テストでは正しくても、複数日つなぐと新規が止まらない、文脈が固定される、
弱い direction を広げて断定する、といった長期の悪化が起きうる。

それを **固定 clock の synthetic learner** で継続検証する。
推薦品質（[tutor_recommendation_quality.md](./tutor_recommendation_quality.md)）と同じく、
**LLM-as-judge を唯一の pass/fail 根拠にしない。**
主 gate は説明可能な不変条件である。

擬似データで「学習効果」の絶対値は証明しない。
score の絶対値を golden 固定しない。見るのは不変条件と、日次の傾向である。

HTTP API と SQLite で同じ policy を一本の学習フローに通す検証は
`backend/tests/test_tutor_phase7_vertical_slice.py` と
`frontend/src/test/TutorPhase7Flow.test.tsx`（Issue #207）。
完了条件と Phase 7 の次は `docs/tutor_architecture.md` の
「Phase 7 Exit Criteria」と「Phase 7 後」を正とする。

## 評価するもの / しないもの

評価する:

- due backlog が高い日は new 流入を抑えること。hard 閾値では止めること
- explicit known が new 枠を消費しないこと
- 1 Source の Item だけで new の admission 枠を占有し続けないこと
- 同じ表記の未学習を同日に複数 admit しないこと
- 複数文脈を持つ Item が、同じ Exercise で同じ出典に固定されないこと
- production だけが弱い pattern を、recognition の弱点にしないこと
- 閾値未満の少数誤答で WeaknessPattern を断定しないこと
- 難しい期間のあと max_new が下がり、状態が戻るとデフォルト件数へ戻れること
- due review が new より先で、入りきらない due がある日は new を入れないこと
- 同じシナリオなら同じ日次結果になること

評価しない（減点理由にしない）:

- 擬似データ上の正答率や定着そのもの
- score / 件数の絶対値の golden 一致
- LLM による「この数週間は自然か」という感想
- 実ユーザー効果の統計的証明、online A/B、automatic weight tuning、強化学習

## シミュレーション

定義: `backend/app/evaluation/learning_quality_fixtures.py`
実行: `backend/app/evaluation/learning_quality.py`

1日の組み立て順は `TodayLearningService._build_plan` に合わせる。

```text
その朝の Source / accepted Item
  -> signal / explicit known / auto-skip
  -> admission
  -> ranking / adaptive plan / Daily Learning Plan
  -> 答えた日だけ context を選び LearningEvent / State / Schedule を進める
```

時計はシナリオの start から日数だけ進む。`datetime.now` は使わない。
回答の正誤は item の behavior とその日の answer mode だけで決まる。
DB も OpenAI も呼ばない。

| ID | 日数 | 中身 |
|----|------|------|
| `combined-21d` | 21 | 毎日に近い新規 Source、1 Source に多数の Item、既知 Item、同じ表記の繰り返し、3 出典の表現、production だけ誤る代名動詞、2日の欠席、3日の全誤答、その後の回復 |
| `sparse-errors-3d` | 3 | 1 Item だけの短い誤答。横断の弱点にはしない |

`combined-21d` の production だけ弱い Item は、難しい期間でも recognition を誤答にしない。
「production だけ弱い」と「その期間は全体の誤答率が高い」を混ぜないためである。

## invariants

評価ハーネスが毎回見る。

- due が soft 閾値以上の日は admission budget と max_new を抑える。hard 閾値以上では新規を止める
- explicit known は admitted にも Plan の new にも入らない
- 同一 Source の admit は per-source cap まで。在庫が多くても他 Source が残る日がある
- 正規化後の同じ表記は同日に 1 件しか admit しない
- 複数文脈の連続選択は、直近と同じ出典にならない
- tracked pattern は、production attempt が閾値未満のあいだ弱点にしない。検出しても recognition は弱点にしない
- `sparse-errors-3d` は WeaknessPattern を 1 件も断定しない
- `RECENT_ERROR_RATE_HIGH` の日は max_new がデフォルト未満。そのあと `STABLE_PROGRESS` で 10 問・新規 3 件に戻れる
- Plan では review が new より前。deferred due がある日の new は 0。due がある日は review が 1 件以上
- レポートの policy version は各モジュールの定数と一致する

## metrics

日次で残す。傾向の比較用であり、絶対値の合否には使わない。

- admitted new count / day
- deferred new count
- due backlog
- overdue count
- repeated same-context rate
- known skip count（その朝、未回答のまま new から外れている既知 Item 数の日次和）
- weakness pattern count
- daily plan size / max_new
- direction balance（recognition / production の Plan 件数）

## policy snapshot

評価結果に残す:

- `feature_version`
- ranking `policy_version`
- plan `policy_version`
- admission `policy_version`
- adaptive load `policy_version`
- context `policy_version`
- weakness pattern `version`
- known-item `policy_version`
- scenario id
- 上記の日次メトリクス

weight や閾値を変えたときに「どの版の組み合わせか」を見比べるため。

## 実行方法

通常の unit test は API key なしで通る。CI の `pytest` が主ゲート。

任意でレポートを出す:

```bash
cd backend
uv run python ../scripts/evaluate_tutor_learning_quality.py
uv run python ../scripts/evaluate_tutor_learning_quality.py --scenario combined-21d --json
uv run python ../scripts/evaluate_tutor_learning_quality.py --strict
```

このスクリプトは LLM を呼ばない。`--strict` は不変条件の失敗で終了コード 1。
デフォルトの終了コードは「評価を実行できたか」であり、表示用。

## スコープ外

- 実ユーザー効果の統計的証明
- online A/B test
- automatic weight tuning
- reinforcement learning
- LLM-as-judge を唯一の gate にすること
