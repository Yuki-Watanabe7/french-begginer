# 外出先の読み取り専用教材契約（設計草案 v1）

[ADR 0001](../adr/0001-local-lan-and-remote-readonly-hosting.md) の抽出・閲覧・配布境界を定める。2026-10-20 時点では設計であり、以下の schema、exporter、静的 UI、公開処理は未実装。`public-v1` / `private-v1` は本プロジェクト内の配布形式名で、既存 API の型名ではない。

## 読者と情報分類

公開版は誰でも JS/JSON を直接取得・保存できる。private 版も本人認証後には内容を保存できる。既存の LearningItem 採用操作は学習対象の決定であって、公開・第三者配布の承認ではない。

| 元データ・項目の例 | public-v1 | private-v1（本人認証） | 根拠・処理 |
|---|---|---|---|
| LearningItem の `item_type`、`canonical_form`（`bonjour`）、`meaning_ja`（こんにちは） | 内容と権利の個別承認後に可 | 外部保存承認後に可 | 個人名や会話内容を含む例は一般教材として扱わない |
| `explanation_ja`、CEFR `level`、自作の一般例文 | 個別承認後に可 | 個別承認後に可 | LLM が生成しただけでは権利・個人情報の審査済みにならない |
| 元の `id`、`source_refs`、`created_at`、`status` | 不可 | 不可 | 配布内だけの `card_id` を新規採番。元 DB と結合できる ID はローカル監査へ |
| metadata、evidence_span/text、Source 本文・segments、元タイトル・URL・端末パス | 不可 | 不可 | 汎用 dict や原文を流用しない。出典表示は以下の限定 provenance へ再編集 |
| 公開可能な出典名・HTTPS URL・license/attribution | 確認後に可 | 確認後に可 | query/fragment、認証付 URL、私的な名前を含む URL は不可。権利不明は送信停止 |
| ReviewSchedule の `due_at`、`skill_direction` | 不可 | 任意の限定 `review_hint` だけ可 | `as_of` 時点の予定として表示し「今すぐ復習」の確定値にしない |
| 苦手パターン・LearnerState の習熟度 | 不可 | 任意の定型 `weakness` 区分だけ可 | 生 score/count/history を出さない。私的文章やプロフィールは含めない |
| LearningEvent、回答入力、response time、個人会話、私的プロフィール | 不可 | 不可 | private 配布も原本のバックアップや個人履歴 API ではない |
| API key、cookie/token、provider 生応答・prompt・診断 log、DB・暗号化 backup | 不可 | 不可 | クライアント同梱の鍵・認証情報も禁止 |
| TTS/取り込み音声・動画・PDF 原本 | 不可 | 不可 | v1 はテキストのみ。配布権と費用の別判断なしに追加しない |

秘密・私的原文が疑われる場合、正規表現で消したことだけを根拠に承認しない。schema 許可と内容・権利の人間審査を両方必要とする。

## 型とサイズの許可リスト

未知フィールドは全階層で拒否する（`additionalProperties: false` 相当）。`null` と省略を曖昧にせず、任意項目は省略する。HTML/Markdown を実行・描画せず plain text として表示する。配布 schema は DB/既存 API の全項目を serialize せず新しい DTO として実装する。

| 階層 | 許可するキーと制約 |
|---|---|
| manifest 共通 | `schema_version` = `public-v1` または `private-v1`、`classification` = `public` または `authenticated-private`（対応を固定）、`snapshot_id` = 内容 hash と同じ 64 桁 lowercase hex、`as_of` / `generated_at` / `expires_at` = UTC RFC3339、`content_sha256` = 64 桁 lowercase hex、`card_count` = 1–500、`content_bytes` = UTF-8 実 byte 数 |
| content root | `cards` 配列のみ。`card_id` 昇順、重複不可 |
| card 共通 | `card_id` = 配布内の opaque ID（1–64 ASCII 英数・`-`・`_`）、`item_type` = `vocabulary` / `expression` / `conjugation` / `grammar`、`canonical_form` ≤ 200 文字、`meaning_ja` ≤ 500、任意 `explanation_ja` ≤ 2,000、任意 `level` = A1–C2、`examples` = 0–3 件、`provenance` 必須 |
| example | `fr` ≤ 500 文字、`ja` ≤ 500 文字だけ。匿名化した未審査の元会話を例文にしない |
| provenance | `kind` = `original` / `licensed` / `public-domain`、`attribution` ≤ 300 文字、任意 `url` = 公開承認した HTTPS URL ≤ 2,048、任意 `license` ≤ 100。再配布根拠の詳細と元 ID はローカル監査で管理 |
| private-v1 の card にのみ追加可 | 任意 `review_hint` = `due_at`（UTC RFC3339）と `skill_direction`（recognition/production）の組を 1–2 件、方向重複不可。任意 `weakness` = `recognition` / `production` / `both`。値は承認した定型変換で算出し、自由入力不可 |

`item_type` は [現行 domain](../../backend/app/domain/tutor.py) の対象を v1 として限定する。将来の型追加は自動許可しない。公開版は全カード集合の選択自体にも個人の苦手傾向を反映させず、一般教材として編集する。

1 回の出力全体は 10 MiB 以下、content JSON は 5 MiB 以下、manifest は 16 KiB 以下、カード 500 枚まで。画像・音声・外部 font は含めない。文字列長と byte 数を両方検査し、超過・0 枚なら失敗させる。これらは provider の上限ではなく本プロジェクトの初期制限である。

### 合成データの例

次は実データを含まない public-v1 の **content** 例。manifest の hash/byte 数は実装時にこの実 byte 列から計算し、説明用のダミー hash を配布しない。

```json
{
  "cards": [
    {
      "card_id": "card-001",
      "item_type": "vocabulary",
      "canonical_form": "bonjour",
      "meaning_ja": "こんにちは",
      "explanation_ja": "日中の一般的なあいさつ。",
      "level": "A1",
      "examples": [{"fr": "Bonjour !", "ja": "こんにちは！"}],
      "provenance": {"kind": "original", "attribution": "自作の一般教材"}
    }
  ]
}
```

private-v1 では同じカードに、たとえば `review_hint: [{"due_at":"2026-10-21T00:00:00Z","skill_direction":"production"}]` と `weakness: "production"` を追加できる。public-v1 に同じキーが存在したら値にかかわらず拒否する。これは架空の日時であり本人の予定ではない。

## 一貫した抽出、hash、古さ

1. 整合した DB コピーまたは一つの読取 transaction から、承認対象だけを抽出する。`as_of` はその読取時点、`generated_at` は生成時点で、`as_of <= generated_at <= expires_at` とする。公開版の `as_of` は個人の最終学習時刻ではなく編集集合の取得時刻である。
2. UTF-8・BOM なし・Unicode NFC、キー sort、不要空白なし、NaN/Infinity 不可、カードと各配列の順序を規定して content を生成する。`content_sha256` は **content ファイルの実 byte 列**の SHA-256、`snapshot_id` はその hash。manifest を hash の対象へ含めず、循環を避ける。
3. ファイル名を `content.<snapshot_id>.json` に固定する。同じ内容から同じ byte 列と hash が出ることを試験する。manifest の日時は変化し得るため、完全な配布物の識別には別の bundle manifest hash を使う。
4. `expires_at` の初期規則は public = `as_of + 30日`、private = `as_of + 7日`。再配布だけで `as_of` を更新しない。未来の `as_of` が閲覧時計より 5 分超、時刻順序違反、不正 hash/サイズ/型なら新しい版の表示へ切り替えない。
5. UI は取得時点・生成時点・期限・配布版を表示する。期限超過や再取得失敗は古い版と明示し、public は最終正常教材を継続表示可。private の期限超過では `review_hint` と `weakness` を隠し、静的教材だけ表示する。期限は秘密の回収機構ではない。

## ローカル検査と公開承認

生成先は Git 作業ツリー外の専用 staging ディレクトリとし、実装時に無視設定と送信前の検査も加える。元 DB、承認前 Snapshot、個人 Snapshot は Git、PR、CI log、公開 artifact に入れない。public 用 CI でも審査前の実データは渡さず、合成 fixture だけを使う。

ローカル検査は許可キー、型、文字列長、byte 数、ID 重複、日時、hash、HTML/制御文字、禁止キーと秘密らしい文字列、URL の scheme/query/fragment・私的 host/path を決定的に検証する。LLM に秘匿化判断を任せない。ファイル一覧は正規化した相対パスで比較し、symlink、`..`、余分な拡張子、`.env`、DB、source map、log、`.git`、backup、runtime/server code を拒否する。違反時は送信前に止め、警告だけで続行しない。

人間の承認記録には、読者、送信先 project/domain、許可する分類・項目、配布全ファイル一覧と hash をまとめた **bundle manifest hash**、schema、出典・再配布権、承認者、承認時刻、期限、巻戻し先を含める。private では本人限定であっても外部保存と due/weakness の必要性を承認する。個人データや本人メールを一般公開の承認 Issue 本文へ書かず、アクセス制限された記録への参照を使う。

PCP #51 の方針に沿い、一般公開は内容と送信先を確認できる人間の明示承認を必要とする。内容・読者・項目・送信先の変更後は旧承認を流用しない。workflow の実行可否、必要な人間承認、配布 token の権限は別の制御である。自動 push から無承認で公開しない。

## 配布、失敗、巻戻し

1. クリーンな出力ディレクトリに閲覧専用の HTML/JS/CSS、manifest、指定 content だけを作り、全ファイルの byte hash を bundle manifest に記録する。最終 build 後の bundle を審査し、承認後に再 build しない。
2. GitHub Pages は承認済み artifact だけの deploy を候補とする。ソース repo の丸ごと upload、個人 JSON の commit、公開前の unreviewed artifact 保存を禁止する。必要な repo プラン、Actions 保存の読者・保持期間を配布前に確定する。
3. Cloudflare は専用 Direct Upload project を候補とする。**空または合成のデータで**、本番 `project.pages.dev`、`*.project.pages.dev` の preview/hash/branch alias、custom domain があればその全パスを Access で保護する。独立した検査で未認証 JSON 直アクセスを拒否できた後に個人データを upload する。保護が未確認なら送らない。
4. provider の完成した deployment 単位で切り替え、固定 URL をファイル単位で上書きしない。manifest と内容は同一 deployment に含める。ブラウザは manifest と content の hash が一致する完全な版だけへ切替し、CDN で旧新が混ざったら再取得または前の正常版を表示する。
5. upload が途中失敗したら現在の正常 deployment を維持し、失敗版を正常として記録しない。成功後は本番 URL から manifest/hash、個人版の認証境界、禁止ファイル・API 非存在を再検査し、provider deployment ID、bundle hash、操作者・時刻を私的台帳へ残す。
6. 巻戻しは直近の承認済み bundle を Pages へ再 deploy、Cloudflare は成功した production deployment への [rollback](https://developers.cloudflare.com/pages/configuration/rollbacks/)とする。preview を rollback 対象にしない。旧版に失効・権利問題があれば戻さず、個人データを含まない停止案内に切り替える。
7. 誤公開時は配布停止と認証/公開設定の是正、問題の deployment・preview・artifact の削除、保持版と cache の点検を行う。rollback は漏えい取消しではない。外部ブラウザや検索 cache に保存された内容を回収できると報告しない。

初期保持は承認済み正常 bundle 2 世代をローカルで保護し、CI artifact は必要最短（目標 1 日、利用可能な設定を導入時に確認）、private staging は完了/失敗後に削除する。provider 上の旧 deployment は目標 7 日以内に整理するが、公開 URL と個人版 Access の保護は削除まで継続する。期限付きの承認を保持数で上書きしない。

## 認証、cache、オフライン

private 版の Access は本人に限定した IdP/メール OTP を使い、Everyone/Bypass・ブラウザ同梱の service token を禁止する。セッション期限の初期目安は 24 時間以内。別ユーザー・未認証・期限切れで production/preview/alias/古い deployment/JSON を拒否する。ログイン画面が出ることだけでは検証完了ではない。

public 版は hash ファイルの cache を利用できる。private 版は初期には service worker を登録せず、Cache API/localStorage/IndexedDB へ内容を永続保存しない。`Cache-Control: private, no-store` を明示し、CDN の共有 cache/bypass rule を点検する。HTTP cache を使わなくても認証済み端末からの保存・撮影までは防げない。ログアウト後の新規取得を拒否し、開いていた画面も内容を消す。IdP の認証ページを JSON と誤解して表示しない。

LAN 事前保存 PWA を追加する場合は、HTTPS と端末の証明書信頼、明示的な保存完了と容量、機内モード、Safari の cache 消去、更新失敗時の旧正常版維持を検証する。端末が最新データを知らないときは同期済みと表示しない。private の永続オフライン利用はリスク受入と別の設計レビューを要する。オフラインで認証失効を即反映できるとは約束しない。

## 静的 UI の読み取り専用条件

- 既存 TutorFlow や API client を再利用した全機能 bundle を配らない。独立 entry から同一配布内の manifest/content/静的 asset だけを GET/HEAD する。許可した Access のログイン遷移以外、LAN、OpenAI、解析・広告、外部 font に接続しない。
- カード表示と答えの開閉はメモリ内の UI 状態だけ。採点の送信、LearningEvent、LearnerState、ReviewSchedule の更新、復習 session 作成、TTS GET、sync queue、後日の回答同期を作らない。
- serverless の書込 endpoint、DB、LLM/API キー、`functions/`、`_worker.js` を配布しない。UI のボタン非表示だけで境界を実装しない。
- JSON、JS、asset の URL を直接列挙・取得しても、許可データだけであることを確認する。GET だけの検査ではなく URL/宛先と配布ファイルも検査する。
- GitHub project Pages のサブパスと Cloudflare の root path の両方で asset を正しく取得する。CSP 等は各 provider で利用できる設定方法を Phase 3b/4 で検証し、設定ファイルを置いただけで有効としない。

## 後続実装の検証計画

| 対象 | 必須の確認（いずれも現時点では未実施） |
|---|---|
| exporter | public へ review_hint/weakness、未知 metadata、secret、私的 Source、権利不明、巨大 payload、パストラバーサルを渡すと拒否。同じ入力の byte/hash 再現。DB を変更しない |
| 契約 | public/private 正常 fixture、不正 schema/時刻/hash、UTF-8 byte 超過、0 枚、重複 ID、余分なファイルを検出 |
| viewer | browser の全 network を捕捉し、許可した同一配布の GET/HEAD 以外が 0。答え開閉・再読込後も学習 API と永続書込が 0 |
| Pages | 審査済み一般教材を未認証で取得できる想定を確認。個人項目・秘密・未承認データが存在しない |
| Pages + Access | 新規セッション/別アカウント/期限切れで本番、JSON、preview、branch alias、旧 URL を拒否。許可本人だけ成功し、logout 後の再取得と cache を検査 |
| 配布失敗・rollback | 中断 upload、manifest/content 不一致で部分版を出さず、承認済み旧版へ復旧し、撤回版を再公開しない |
| 外出先・host off | iPhone 携帯回線で自宅 PC を止めても最終教材を閲覧可。期限切れ・更新失敗を明示し、個人の古い予定を隠す |
| offline 代替 | 事前保存済み/未保存/容量不足/cache 削除/再起動を区別。保存未確認を閲覧可能と表示しない |

受入結果と公開承認、実際の配布 URL、費用・復元記録の所在は親 #209 から参照する。現時点で外部公開した教材・確認済みのアクセス制御はない。
