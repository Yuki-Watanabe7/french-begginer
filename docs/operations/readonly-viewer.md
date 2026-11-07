# 公開教材の静的ビューアー

Issue #222 の閲覧専用画面。`public-v1` の `snapshot.json` と静的な HTML / JS だけで動き、自宅 FastAPI、SQLite、TTS / LLM、外部フォント、解析サービスには接続しない。既存の学習アプリと起動・ビルド・配布先を分けている。

## 合成教材で確認する

```bash
cd frontend
npm ci --include=dev
npm run build:readonly
npm run preview:readonly
```

`http://127.0.0.1:4174/` を開く。各カードの「答えを見る・閉じる」をタップすると、日本語の意味と任意の説明が開閉する。カード順・種類・任意のレベルを表示する。答えの開閉はページ内だけの状態で、再読み込みすると閉じる。採点・保存・同期はしない。

日時は「教材の書き出し日時」として UTC を明記する。これは現在の DB の状態や最終更新日時ではない。教材の有効期限や「最新」の判定は設けていない。

## 配布物と入力の境界

- `frontend/readonly/index.html` が独立した入口で、`frontend/src/readonly/` だけをアプリの入口としてビルドする。通常の `src/main.tsx`、API client、TTS hook は取り込まない。
- `npm run build:readonly` の出力は Git 管理外の `frontend/dist-readonly/`。中身は `index.html`、`assets/*.js` と `snapshot.json` だけ。
- 教材は #221 の exporter と一致することをテスト済みの `docs/operations/public-snapshot.synthetic.json` に固定する。DB、実データの Snapshot、allowlist、環境変数を入力に取らない。通常の frontend の `public/` もコピーしない。
- ブラウザからの教材取得は、画面と同じ階層の `./snapshot.json` の GET だけ。Cookie は送らず、リダイレクトを拒否し、`cache: 'no-store'` で取得する。Service Worker やブラウザ保存領域は使わない。
- root / card の未知のキー、未対応の版、重複 ID、件数・長さ・型・日時・公開テキストの制約を検査する。1 枚でも不正なら全体をエラーにし、部分的なカードを出さない。文字列は React の通常のテキストとして描画する。
- HTTP エラー、通信失敗、不正 JSON、不正形式、10 秒の取得タイムアウトは画面にエラーを出す。「再読み込み」で再取得できる。過去の成功データへのフォールバックはしない。

## GitHub Pages と同じサブパスで確認する

ビルドの `base` は `./`。スクリプトと教材は `/french-begginer/` のようなサブパスからも、そのサブパス内で取得する。フォルダーの URL は末尾を `/` にする。

```bash
# リポジトリのルートから。合成教材だけのビルドを一時フォルダーに置く
preview_root=$(mktemp -d)
mkdir "$preview_root/french-begginer"
cp -R frontend/dist-readonly/. "$preview_root/french-begginer/"
python3 -m http.server 4175 --bind 127.0.0.1 --directory "$preview_root"
```

`http://127.0.0.1:4175/french-begginer/` を開き、スマホ幅でカード・答え・改行・日時が読めることを確かめる。ブラウザの通信一覧には、この階層内の静的ファイルだけが現れる。`snapshot.json` を一時フォルダー内で消したり、不正 JSON に差し替えて再読み込みすると、カードの代わりにエラーになる。

## 品質検査と公開の扱い

`bash scripts/quality-check.sh` と GitHub Actions の通常 CI は、既存の検査に加えて専用ビルドを実行する。`ReadonlyViewer.test.tsx` は合成 fixture の受理、不正形式の拒否、答えの開閉、通信先・取得オプション、保存しないこと、エラーからの再試行、タイムアウトを確認する。

専用ビルドはローカル検証用で、GitHub Pages の設定・デプロイ・実教材の送信は行わない。#223 の[配布準備と公開手順](public-readonly-publishing.md)で、指定した Snapshot を再検査し、ビューアーと教材だけを新しい配布フォルダーにまとめられる。実際の公開は、公開先と Snapshot の内容・sha256 を本人が確認してから行う。詳細は [教材契約](remote-readonly-contract.md) を参照。スマホ実機の使用感は人手で確認する。

### 2026-11-04 の確認結果

- `bash scripts/quality-check.sh` 成功。Backend 2,020 件成功・実 LLM 評価 1 件スキップ、Frontend 407 件成功（この画面の 37 件を含む）。lint・format 検査と通常／閲覧専用の両ビルドが成功。
- 生成物を検査し、HTML 1 件・独立 JS 1 件・合成 Snapshot 1 件だけであること、Snapshot が #221 の fixture と一致することを確認。
- Chrome で `/french-begginer/` 配下から表示。通信一覧は同じサブパス内の HTML・JS・`snapshot.json` の 3 件だけ。iPhone 16 相当（393px 幅）でカード・答えの開閉・スクロールを確認。
- 一時配布フォルダーで `snapshot.json` を欠落／不正 JSON にして画面を再読み込みし、各エラーを表示して以前のカードを表示しないことを確認。元の合成ファイルへ復旧。
- スマホ実機の使用感は未確認。本人による確認を経てからレビュー完了・マージする。
