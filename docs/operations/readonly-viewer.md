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
- `npm run build:readonly` の出力は Git 管理外の `frontend/dist-readonly/`。中身は `index.html`、`assets/index-<hash>.js`、`snapshot.json`、`apple-touch-icon.png`、`favicon.png`、`icon-192.png`、`icon-512.png`、`manifest.webmanifest` の8ファイル。配布準備では空の `.nojekyll` を追加し、合計9ファイルにする。
- 教材は #221 の exporter と一致することをテスト済みの `docs/operations/public-snapshot.synthetic.json` に固定する。DB、実データの Snapshot、allowlist、環境変数を入力に取らない。通常の frontend の `public/` もコピーしない。
- ブラウザからの教材取得は、画面と同じ階層の `./snapshot.json` の GET だけ。Cookie は送らず、リダイレクトを拒否し、`cache: 'no-store'` で取得する。Service Worker やブラウザ保存領域は使わない。
- アイコンと manifest は閲覧専用の `frontend/readonly/public/` だけからコピーする。図案の元は `frontend/readonly/artwork/icon.svg`。青地の本と青・白・赤のしおりを図形だけで自作し、第三者の画像・フォントは使っていない。PNG 4種はこの SVG を各サイズに変換した、透過のない画像である。図案の元ファイルは配布しない。
- HTML のアイコン・manifest の参照、manifest のアイコン・起動先・対象範囲はすべて相対 URL にし、GitHub Pages の `/french-begginer/` 内で解決する。Content Security Policy は同一配信元の画像と manifest だけを許可する。
- root / card の未知のキー、未対応の版、重複 ID、件数・長さ・型・日時・公開テキストの制約を検査する。1 枚でも不正なら全体をエラーにし、部分的なカードを出さない。文字列は React の通常のテキストとして描画する。
- HTTP エラー、通信失敗、不正 JSON、不正形式、10 秒の取得タイムアウトは画面にエラーを出す。「再読み込み」で再取得できる。過去の成功データへのフォールバックはしない。

## GitHub Pages と同じサブパスで確認する

ビルドの `base` は `./`。スクリプト・教材・アイコン・manifest は `/french-begginer/` のようなサブパスからも、そのサブパス内で取得する。フォルダーの URL は末尾を `/` にする。

```bash
# リポジトリのルートから。合成教材だけのビルドを一時フォルダーに置く
preview_root=$(mktemp -d)
mkdir "$preview_root/french-begginer"
cp -R frontend/dist-readonly/. "$preview_root/french-begginer/"
python3 -m http.server 4175 --bind 127.0.0.1 --directory "$preview_root"
```

`http://127.0.0.1:4175/french-begginer/` を開き、スマホ幅でカード・答え・改行・日時が読めることを確かめる。ブラウザの通信一覧には、この階層内の静的ファイルだけが現れる。`snapshot.json` を一時フォルダー内で消したり、不正 JSON に差し替えて再読み込みすると、カードの代わりにエラーになる。

## ホーム画面への追加を確認する（Issue #235）

本人がスマホ実機で次を確認する。ローカルの画面確認だけでは、公開版のホーム画面の表示を確認したことにはしない。

1. [配布手順の手順4](public-readonly-publishing.md#4-更新する)で、本人が承認した候補を公開する。教材を変えない更新では、公開前後の `snapshot.json` の sha256 が一致することを確認する。
2. iPhone の Safari で `https://yuki-watanabe7.github.io/french-begginer/` を開き、「共有」から「ホーム画面に追加」を選ぶ。
3. 青地の本と3色のしおりの専用アイコン、名前「フランス語教材」が出ることを確認して追加する。名前は Apple 用の設定 `apple-mobile-web-app-title` に指定している（[Apple の公式説明](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html)）。
4. 追加したアイコンから開き、3枚の教材と答えを読めることを確認する。manifest の `display: standalone` はブラウザのアドレス欄を隠す表示指定で、オフライン対応の指定ではない（[MDN の説明](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest/Reference/display)）。閲覧には通信が必要で、学習結果は保存しない。
5. 以前のアイコンが残る場合は、公開ファイルの更新を確認してから、以前のホーム画面のショートカットを削除し、Safari から追加し直す。Pages のキャッシュで公開直後は約10分、旧版が返る場合もある。

manifest の `name` は「フランス語練習・公開教材」、`short_name` は「フランス語教材」。iPhone 以外でもホーム画面への追加時には同じ図案の192px・512pxアイコンを参照する。Service Worker やオフライン保存は追加していない。

## 品質検査と公開の扱い

`bash scripts/quality-check.sh` と GitHub Actions の通常 CI は、既存の検査に加えて専用ビルドを実行する。`ReadonlyViewer.test.tsx` は合成 fixture の受理、不正形式の拒否、答えの開閉、通信先・取得オプション、保存しないこと、エラーからの再試行、タイムアウトを確認する。

専用ビルドはローカル検証用で、GitHub Pages の設定・デプロイ・実教材の送信は行わない。#223 の[配布準備と公開手順](public-readonly-publishing.md)で、指定した Snapshot を再検査し、ビューアーと教材だけを新しい配布フォルダーにまとめられる。実際の公開は、公開先と Snapshot の内容・sha256 を本人が確認してから行う。詳細は [教材契約](remote-readonly-contract.md) を参照。スマホ実機の使用感は人手で確認する。

### 2026-11-04 の確認結果

- `bash scripts/quality-check.sh` 成功。Backend 2,020 件成功・実 LLM 評価 1 件スキップ、Frontend 407 件成功（この画面の 37 件を含む）。lint・format 検査と通常／閲覧専用の両ビルドが成功。
- 生成物を検査し、HTML 1 件・独立 JS 1 件・合成 Snapshot 1 件だけであること、Snapshot が #221 の fixture と一致することを確認。
- Chrome で `/french-begginer/` 配下から表示。通信一覧は同じサブパス内の HTML・JS・`snapshot.json` の 3 件だけ。iPhone 16 相当（393px 幅）でカード・答えの開閉・スクロールを確認。
- 一時配布フォルダーで `snapshot.json` を欠落／不正 JSON にして画面を再読み込みし、各エラーを表示して以前のカードを表示しないことを確認。元の合成ファイルへ復旧。
- スマホ実機の使用感は未確認。本人による確認を経てからレビュー完了・マージする。

### 2026-11-08 のアイコン追加の検証結果（Issue #235）

- `bash scripts/quality-check.sh` 成功。Backend 2,052 件成功・実 LLM 評価1件スキップ、Frontend 407 件成功。lint・format 検査、通常／閲覧専用の両ビルド、合成教材での配布準備が成功した。
- 配布境界の32件が成功。アイコン・manifest を含む必要ファイルの欠落、指定外の画像・manifest・Service Worker・2つ目の JS、画像・manifest へのリンクを拒否した。梱包したファイルのバイト列も生成元と一致した。
- 配布候補をローカルの `/french-begginer/` 配下で Chrome により確認した。iPhone 13 相当の390px幅でカード3枚・答えの開閉・改行を確認し、横にはみ出さないことを確認した。これはスマホ実機や Safari の確認ではない。
- アイコン4種をブラウザで読み込み、180×180・32×32・192×192・512×512を確認した。Chrome が manifest をエラーなく受理し、名前が「フランス語教材」、起動先と対象範囲が同じサブパスになることを確認した。9配布ファイルが HTTP 200 で取得でき、候補とバイト列が一致した。ブラウザの通信はそのサブパス内だけで、ページエラー・CSP 違反・ブラウザ保存・Service Worker 登録はなかった。
- 現在の公開 URL から取得した `snapshot.json` と候補のバイト列が一致した。sha256 は `38f62357d9bf8c8c0bf8ad32e9fc9b3dde2df028f51b0536ae8d9a335eb5d600`。教材とビューアーの JS は変更していない。
- 公開サイトへの再配布と、本人によるホーム画面のアイコン・名前・起動の実機確認は未実施。配布候補の承認を得てから手順4で公開し、実機で確認する。Issue #235 は開いたままにする。
