# 公開教材の配布・更新・停止（Issue #223）

本人が内容と公開先を承認した一般教材だけを GitHub Pages で配布する。ローカルで専用ビューアーをビルドし、検査したファイルを手動で配布する。自宅の FastAPI / SQLite、学習履歴、有料 API、常時稼働クラウドは使わない。

## 現在の契約と公開候補（2026-11-05 確認）

- アカウントの [Billing](https://github.com/settings/billing) は **GitHub Free**。アプリの `Yuki-Watanabe7/french-begginer` は **private**。
- 対象の [Settings → Pages](https://github.com/Yuki-Watanabe7/french-begginer/settings/pages) は「Upgrade or make this repository public to enable Pages」と表示。Pages API の取得は 404。現在の契約では、この private repo からの Pages 公開は利用できない。
- 推奨候補は **配布専用の公開 repo `Yuki-Watanabe7/french-beginner-materials`** と `https://yuki-watanabe7.github.io/french-beginner-materials/`。この名前の repo は API で確認できず、まだ作成していない。アプリ repo の可視性と契約は変更しない。
- 初回教材の候補は [合成教材3枚](public-snapshot.synthetic.json)：`bonjour`（こんにちは）、`s'il vous plaît`（お願いします）、`nous parlons`（私たちは話す）。実 DB は使わない。生成する `snapshot.json` の全文と sha256 を本人が確認して承認する。別の教材を使う場合は [#221 の書き出し手順](remote-readonly-contract.md) で作る。

**公開は未承認・未実施。** この手順や実装のマージ、Issue の対応依頼は、公開 repo 作成・教材送信・Pages 有効化の承認に代わらない。

[公式の利用条件](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)では Free は公開 repo、Pro 等は private repo でも Pages を使える。Free の公開 repo で静的配布する案には追加契約・ドメイン購入は不要。標準 runner の公開 repo / Pages 用実行は無料扱いだが、元の private repo の通常 CI や artifact / cache の利用は別に確認する（[Actions 課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)）。配布 repo には独自の build workflow、cache、保存 artifact を追加しない。サイト上限 1 GB・帯域 soft limit 月 100 GB 内で使い、制限超過時は更新を止めて確認する。自動アップグレードしない。

## 1. ローカルで公開候補を作る（外部変更なし）

リポジトリのルートから実行する。実教材では `--snapshot` を書き出したファイルに置き換える。出力先は Git 作業ツリーの外の**新しい**ディレクトリにする。

```bash
cd frontend
npm ci --include=dev
npm run build:readonly
cd ../backend
uv run python ../scripts/prepare_public_readonly.py \
  --snapshot ../docs/operations/public-snapshot.synthetic.json \
  --out /tmp/french-public-review/site
```

出力は `index.html`、`assets/index-<hash>.js`、指定した `snapshot.json`、空の `.nojekyll` だけ。通常アプリの `dist/` や `public/` は使わない。教材の形式・禁止文字列は #221 の型で再検査し、未知のキー・null の任意項目・UTC 秒単位でない日時を拒否する。元の教材のバイト列をそのままコピーするため、表示された sha256 は入力と一致する。生成元に余分なファイル・ソースマップ・DB・`.env`・リンクがあれば停止する。コピー失敗時は配布フォルダーを作らず、既存版も上書きしない。

自動検査だけでは人名・私的な文・権利・教材の誤りを判定できない。**本人は `snapshot.json` の全文、sha256、配布先 repo と URL、誰でも保存できることを確認する。** 承認はこの内容と公開先に対して得る。内容が変われば再確認する。アプリのソースや個人 Snapshot を commit しない。承認済みの公開教材は、配布専用 repo の公開履歴に残す方式である。

[サブパスでの表示確認](readonly-viewer.md)と同様に、配布フォルダーを `french-beginner-materials/` の下に置いてローカルで開く。画面・カード・答え・書き出し日時、同じ階層の静的ファイル以外への通信がないことを確認する。承認した配布フォルダーは、次の更新時にも前の版に戻せるよう手元に残す。

## 2. 承認後だけ初回公開する（外部変更あり）

この節は、配布専用の **public repo と GitHub Pages の新規作成**を伴う。repo も配布ファイルも誰でも取得・保存できる。既存のアプリ repo の可視性は変更しない。承認がなければここから先を実行しない。

以下の `bundle` には、本人が確認した生成済みフォルダーを指定する。元アプリの Git 履歴・remote・ファイルをコピーせず、空の一時 Git repo を用意する。

```bash
distribution_repo=Yuki-Watanabe7/french-beginner-materials
bundle=/tmp/french-public-review/site
shasum -a 256 "$bundle/snapshot.json"  # 本人が承認した値と照合する
deploy_checkout=$(mktemp -d)
git -C "$deploy_checkout" init -b gh-pages
git -C "$deploy_checkout" remote add origin "https://github.com/$distribution_repo.git"
cp -R "$bundle/." "$deploy_checkout/"
git -C "$deploy_checkout" add -- .nojekyll index.html assets snapshot.json
git -C "$deploy_checkout" diff --cached --stat
git -C "$deploy_checkout" diff --cached -- snapshot.json
git -C "$deploy_checkout" commit -m "Publish approved public learning materials"

# ここから外部変更。repo 作成の時点で public になる。
gh repo create "$distribution_repo" --public \
  --description "Approved public French learning cards and a static read-only viewer"
git -C "$deploy_checkout" push -u origin gh-pages
gh api --method POST "repos/$distribution_repo/pages" \
  -f build_type=legacy -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

`gh-pages` は配布ファイル用ブランチの名前。Pages の Source は **Deploy from a branch / gh-pages / /(root)**。`.nojekyll` は Jekyll による加工を省く指定で、GitHub の配布処理だけが走る（[公式のブランチ配布手順](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)）。GitHub トークンをファイルや公開 repo へ保存しない。

```bash
gh api "repos/$distribution_repo/pages" --jq '{html_url,status,source,https_enforced}'
gh api "repos/$distribution_repo/pages/builds/latest" --jq '{status,error,commit}'
```

配布成功の commit と URL を確かめ、公開 URL の `snapshot.json` を取得して、承認したファイルと sha256 を照合する。スマホの携帯回線からカードと答えを開き、自宅 PC が停止中でも読めることを本人が確認する。公開を試していない段階で実施済みと記録しない。#223 は公開・実機確認と関連 PR のレビュー／マージを確認するまで閉じない。

## 3. 更新する

まず品質検査と手順1で、新しい候補を**別フォルダー**へ作る。本人が新しい教材の全文・sha256 と同じ公開先を承認してから、次を行う。

```bash
distribution_repo=Yuki-Watanabe7/french-beginner-materials
bundle=/tmp/french-public-next/site
shasum -a 256 "$bundle/snapshot.json"  # 今回承認した値と照合する
update_root=$(mktemp -d)
git clone --branch gh-pages "https://github.com/$distribution_repo.git" "$update_root/repo"
git -C "$update_root/repo" rev-parse HEAD  # 前の公開版の commit を控える
git -C "$update_root/repo" rm -r --ignore-unmatch .
cp -R "$bundle/." "$update_root/repo/"
git -C "$update_root/repo" add -- .nojekyll index.html assets snapshot.json
git -C "$update_root/repo" diff --cached --stat
git -C "$update_root/repo" diff --cached -- snapshot.json
git -C "$update_root/repo" commit -m "Update approved public learning materials"
git -C "$update_root/repo" push origin gh-pages
```

削除するのは一時 checkout 内の旧配布ファイルだけ。以前の JS を残さず置き換える。公開完了と新しい教材の sha256 を手順2と同様に確認する。元のアプリへの push や PR マージだけでは教材サイトは更新されない。

## 4. 失敗・戻し・停止

- **検査失敗・push 失敗**：公開先へ反映されていなければ元の公開版を利用する。配布処理の失敗時も Pages の status と公開 URL を確認し、元の版が利用できるか実際に確かめる。
- **更新後に表示が壊れた**：配布 repo の `gh-pages` を clone し、直前の更新 commit を `git revert <更新commit>`、`git push origin gh-pages` する。連続更新なら、控えた正常版のフォルダーを手順3で配布し直す。再配布の成功と元の教材の sha256 を確認する。
- **公開を止める**：配布 repo の Settings → Pages → サイト URL 横のメニュー → **Unpublish site**。進行中の配布処理も Actions で停止し、以後の `gh-pages` push を止める。公開 URL と `snapshot.json` が取得できないことを確認する（[公式の停止手順](https://docs.github.com/en/pages/getting-started-with-github-pages/unpublishing-a-github-pages-site)）。停止後も新しい配布で再公開されるため、再開は本人の判断後に行う。

**Pages を停止しても public repo のファイル・Git 履歴・保存済みコピーは消えない。** 誤公開なら通常の巻戻しで済ませず、配布 repo の可視性／内容も含めて本人と対応を決める。第三者が保存したコピーは回収できない。初回承認時からこの方式を説明する。

## 検証と残作業

`bash scripts/quality-check.sh` は通常の検査と、合成教材による専用ビルド・配布フォルダー生成を行う。テストは公開可能な項目だけのコピー、不正教材・混入ファイル・リンクの拒否、既存版と Git 作業ツリーの保護、コピー失敗時に途中の版を出さないことを検証する。外部へは送信しない。

実際の公開・公開後のスマホ確認は、内容と公開先の本人承認後に行う。新しい契約、アプリ repo の public 化、本人認証基盤の追加は本手順に含まれない。

### 2026-11-05 の実装検証結果

- `bash scripts/quality-check.sh` 成功。Backend 2,037 件成功・実 LLM 評価 1 件スキップ、Frontend 407 件成功。lint / format 検査、通常版と閲覧専用版の両ビルド、合成教材での配布準備が成功。
- 配布境界の追加テスト17件が成功。実 DB・実教材・API キーは使っていない。
- 候補は `.nojekyll`（0 bytes）、`index.html`（904 bytes）、独立 JS（149,074 bytes）、合成 `snapshot.json`（755 bytes）の4ファイル。教材の sha256 は `38f62357d9bf8c8c0bf8ad32e9fc9b3dde2df028f51b0536ae8d9a335eb5d600`。
- Chrome でローカルの `/french-beginner-materials/` 配下を開き、3枚のカード・答え・説明・UTC の書き出し日時を確認。HTML / JS / JSON の取得が成功し、配布元のバイト列と一致。通常アプリの API・DB 設定・ブラウザ保存・ソースマップへの参照が生成物にないことも確認。
- 公開 repo の作成・Pages 設定・外部配布・携帯回線／スマホ実機確認は未実施。#223 は未完了のまま維持する。
