# フロントエンド クイズセッションHook 共通化方針

## 概要

`useQuiz` / `useNounQuiz` / `useNounArticleQuiz` の3つのhookは、クイズセッションの状態管理を担当している。
いずれも同じフローを実装しているが、ドメイン固有の型（問題・回答・誤答）が異なるため、現在は別hookとして実装されている。
本文書では現状の差分と共通点を整理し、段階的な共通化方針を示す。

---

## 現状の3hook比較

### Phase定義

| フェーズ値 | useQuiz | useNounQuiz | useNounArticleQuiz |
|---|---|---|---|
| 初期フェーズ | `setup` | `noun-filter` | `noun-filter` |
| フィルター設定完了後 | `quiz-settings` | `quiz-settings` | `quiz-settings` |
| 問題取得中 | `loading` | `loading` | `loading` |
| 回答中 | `answering` | `answering` | `answering` |
| 結果表示 | `result` | `result` | `result` |
| セッション終了 | `session-result` | `session-result` | `session-result` |
| エラー | `error` | `error` | `error` |

`loading` 以降の6フェーズは3hookで完全に一致する。初期フェーズ名のみ異なる。

### State フィールド比較

| フィールド | useQuiz | useNounQuiz | useNounArticleQuiz | 備考 |
|---|---|---|---|---|
| `phase` | `Phase` | `NounPhase` | `NounArticlePhase` | 型名が違うが値は同構造 |
| `question` | `Question \| null` | `NounGenderQuestion \| null` | `NounArticleQuestion \| null` | ドメイン型が異なる |
| `result` | `AnswerResult \| null` | `NounGenderAnswerResult \| null` | `NounArticleAnswerResult \| null` | ドメイン型が異なる |
| `input` | `string` | なし | `string` | useNounQuizはボタン選択式 |
| `error` | `string \| null` | `string \| null` | `string \| null` | 完全一致 |
| `questionNum` | `number` | `number` | `number` | 完全一致 |
| `sessionTotal` | `number` | `number` | `number` | 完全一致 |
| `normalSessionTotal` | `number` | `number` | `number` | 完全一致 |
| `correctCount` | `number` | `number` | `number` | 完全一致 |
| `wrongAnswers` | `WrongAnswer[]` | `NounWrongAnswer[]` | `NounArticleWrongAnswer[]` | ドメイン型が異なる |
| `reviewQueue` | `Question[]` | `NounGenderQuestion[]` | `NounArticleQuestion[]` | ドメイン型が異なる |
| `isReviewPhase` | `boolean` | `boolean` | `boolean` | 完全一致 |
| `firstCorrectCount` | `number` | `number` | `number` | 完全一致 |
| `reviewCorrectCount` | `number` | `number` | `number` | 完全一致 |
| `sessionQueue` | `Question[]` | `NounGenderQuestion[]` | `NounArticleQuestion[]` | ドメイン型が異なる |
| フィルター | `group + level + pattern` | `filter: NounFilter` | `filter: NounFilter` | 型・構造が異なる |

### 公開インターフェース比較

| メソッド | useQuiz | useNounQuiz | useNounArticleQuiz |
|---|---|---|---|
| フィルター選択 | `selectGroup(filter: VerbFilter)` | `selectFilter(filter: NounFilter)` | `selectFilter(filter: NounFilter)` |
| セッション開始 | `startSession(n)` | `startSession(n)` | `startSession(n)` |
| 回答送信 | `submit()` ← inputを参照 | `submit(answer: NounGender)` ← 引数で受け取る | `submit()` ← inputを参照 |
| 次の問題 | `nextQuestion()` | `nextQuestion()` | `nextQuestion()` |
| 新セッション | `startNewSession()` | `startNewSession()` | `startNewSession()` |
| リトライ | `retryLoad()` | `retryLoad()` | `retryLoad()` |
| セットアップへ戻る | `backToSetup()` | `backToSetup()` | `backToSetup()` |
| フィルターへ戻る | なし | `backToFilter()` | `backToFilter()` |
| input更新 | `setInput(v)` | なし | `setInput(v)` |
| inputRef | あり | なし | あり |

### ロジックの差分詳細

#### submit

3hookともに同じ制御フロー:
1. 回答正解 → `isReviewPhase` に応じて `reviewCorrectCount` or `correctCount` をインクリメント
2. 回答不正解 → `isReviewPhase` に応じて `reviewQueue` に追加 or `wrongAnswers` に追加（重複チェック付き）

差分:
- **useNounQuiz** のみ `submit(answer: NounGender)` と引数で回答を受け取る（ボタン選択式UI）
- **useQuiz / useNounArticleQuiz** は `state.input` を参照してAPIに送る（テキスト入力式UI）
- 重複チェックのキー: useQuiz は `verb+tense+pronoun`、useNounQuiz / useNounArticleQuiz は `noun` のみ

#### nextQuestion

3hookで制御フローは完全に同一:
```
isReviewPhase=true:
  reviewQueue空? → session-result
  そうでなければ → 次のreviewQueue問題へ
isReviewPhase=false かつ sessionTotal到達:
  wrongAnswers > 0? → reviewPhaseへ遷移（firstCorrectCount保存）
  そうでなければ → session-result
通常継続:
  sessionQueueから次問題を取り出す
```

差分:
- **useNounQuiz** のみ `input: ''` リセットがない（`input` フィールドを持たないため）
- `inputRef.current?.focus()` の呼び出し: useQuiz / useNounArticleQuiz はあり、useNounQuiz はなし

#### startSession / startNewSession / retryLoad

パターンは3hookで完全に同一（リセット → API呼び出し → 最初の問題セット → error時遷移）。
差分はAPIクライアント関数名のみ:
- `fetchSessionQuestions` / `checkAnswer`
- `fetchNounSessionQuestions` / `checkNounAnswer`
- `fetchNounArticleSessionQuestions` / `checkNounArticleAnswer`

---

## 共通化の分類

### A. すぐに共通化してよいもの

#### A-1. 数値・boolean系のセッションカウンター

`questionNum`, `sessionTotal`, `normalSessionTotal`, `correctCount`, `isReviewPhase`, `firstCorrectCount`, `reviewCorrectCount`, `error` は型・初期値・更新ロジックが完全一致している。
これらを `BaseSessionState` として切り出すことは低リスクで価値がある。

```typescript
interface BaseSessionState {
  phase: string
  error: string | null
  questionNum: number
  sessionTotal: number
  normalSessionTotal: number
  correctCount: number
  isReviewPhase: boolean
  firstCorrectCount: number
  reviewCorrectCount: number
}
```

#### A-2. `DEFAULT_SESSION_SIZE = 10` 定数

3ファイルに重複している。共通ファイル（`src/hooks/sessionConstants.ts` など）に切り出すことができる。
ただし影響は小さいため、優先度は低い。

---

### B. 各hookに残すべきもの（現状維持推奨）

#### B-1. `submit` の引数・内部ロジック

useNounQuiz は `submit(answer: NounGender)` という引数を持ち、UIがボタン選択式である。
useQuiz / useNounArticleQuiz は `submit()` でinput stateを参照する。
この違いはUIアーキテクチャの差であり、強引に共通化すると各コンポーネントへの影響が大きい。現状維持が安全。

#### B-2. `input` / `setInput` / `inputRef`

テキスト入力式（useQuiz, useNounArticleQuiz）とボタン選択式（useNounQuiz）の差。
共通化するには入力モデルを統一する必要があり、UIレイヤーへの影響が大きい。現状維持。

#### B-3. フィルター型（`VerbFilter` vs `NounFilter`）

動詞フィルター（group/level/pattern）と名詞フィルター（level/category）は概念が異なり、共通化すると型安全性が低下する。

#### B-4. 誤答型（`WrongAnswer` / `NounWrongAnswer` / `NounArticleWrongAnswer`）

ドメインごとに保持するフィールドが異なる（verb+tense+pronoun / noun+gender / noun+article）。
型を無理に共通化すると必須でないフィールドが増え、型の表現力が落ちる。

#### B-5. reviewQueueからの問題復元ロジック

`wrongAnswers` から `reviewQueue` を再構築する際のフィールドマッピングは各ドメインに依存する。ここは各hookに残す。

---

### C. 型設計を変えないと共通化しにくいもの

#### C-1. `nextQuestion` の本体ロジック

制御フローは完全に同一だが、`question`, `reviewQueue`, `sessionQueue` の型がドメインごとに異なるため、TypeScriptのジェネリクスを使わないと共通化できない。

共通化候補:

```typescript
// 汎用型制約の例
interface QuizItem {
  // ドメイン共通の最小インターフェース
}

function createNextQuestionHandler<Q extends QuizItem, W>(
  stateRef: RefObject<BaseSessionState & { reviewQueue: Q[]; sessionQueue: Q[]; wrongAnswers: W[] }>,
  setState: Dispatch<SetStateAction<...>>,
  buildReviewQueue: (wrongs: W[]) => Q[],
  inputRef?: RefObject<HTMLInputElement>,
): () => void
```

ただしこのアプローチはジェネリクスの複雑さを持ち込むため、**将来の学習モード追加が2件以上確定した時点** で検討すべき。

#### C-2. `startSession` / `startNewSession` / `retryLoad` のパターン

構造は同一だがAPIコールが異なる。高階関数やファクトリー関数で抽象化できるが、
現時点では読みやすさの観点から各hookの実装のほうがわかりやすい。

---

## 段階的な移行方針

### Phase 1（今すぐ実施可能）: ドキュメント整備のみ

本ドキュメントの追加。コードへの影響なし。

### Phase 2（低リスク）: 定数の共通化

`DEFAULT_SESSION_SIZE` を共通ファイルに切り出す。影響範囲は3ファイルのimport追加のみ。

対象ファイル:
- `src/hooks/sessionConstants.ts` を新規作成
- `useQuiz.ts` / `useNounQuiz.ts` / `useNounArticleQuiz.ts` からimport

### Phase 3（中リスク）: `BaseSessionState` の切り出し

数値カウンター群（`questionNum`, `sessionTotal`, `correctCount`, `isReviewPhase` 等）を `BaseSessionState` として定義する。
各hookの型が `extends BaseSessionState` を持つことで、将来の新hookでの再利用が容易になる。

影響: 型定義のみの変更。既存の動作ロジックには影響しない。

### Phase 4（要検討）: `nextQuestion` のロジック共通化

ジェネリクスを用いた `createNextQuestionHandler` ファクトリー関数の導入。
学習モードが4種類以上になった時点で検討する（3種類では早すぎる抽象化になる恐れがある）。

---

## 後続Issueの提案

| Issue案 | 分類 | 優先度 | 備考 |
|---|---|---|---|
| `DEFAULT_SESSION_SIZE` 定数の共通化 | Phase 2 | 低 | 影響小、いつでも実施可能 |
| `BaseSessionState` 型の切り出し | Phase 3 | 中 | 型のみ変更、動作変更なし |
| `nextQuestion` ロジックの共通化 | Phase 4 | 低 | 学習モードが増えてから検討 |
| `startSession` パターンの共通化 | Phase 4 | 低 | Phase 4と同時に検討 |
| セッション結果ラベル計算の共通化 | Phase 3 | 中 | `firstCorrectCount / normalSessionTotal` の計算が各ResultコンポーネントまたはhookにあればそこもPhase 3と合わせて対象になる |

---

## まとめ

- **コードの動作変更は現時点では不要**。既存の3hookは独立して安全に動作しており、早期の強制共通化は読みやすさを損なうリスクがある。
- **型レベルの `BaseSessionState` 切り出し（Phase 3）** が最も対費用効果の高い次のステップ。
- **`nextQuestion` など制御フローの共通化（Phase 4）** は新しい学習モードが追加される時点まで温存する。
- **`submit` の共通化は現状スコープ外**。UIの入力モデル（テキスト入力 vs ボタン選択）に依存するため、UI設計を変えない限り共通化しにくい。
