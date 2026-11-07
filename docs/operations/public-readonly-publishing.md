# 公開教材の配布・更新・停止（Issue #223）

本人が内容と公開先を承認した一般教材だけを GitHub Pages で配布する。ローカルで専用ビューアーをビルドし、検査したファイルを手動で配布する。自宅の FastAPI / SQLite、学習履歴、有料 API、常時稼働クラウドは使わない。

## 公開先（2026-11-07 決定）

- アカウントの [Billing](https://github.com/settings/billing) は **GitHub Free**。2026-11-05 の確認では、[Settings → Pages](https://github.com/Yuki-Watanabe7/french-begginer/settings/pages) に「Upgrade or make this repository public to enable Pages」と表示され、private のままでは Pages を使えない。
- 2026-11-07、所有者は配布専用 repo を新しく作らず、**このアプリ repo を public にして、同じ repo の `gh-pages` ブランチから配布する**と決めた。公開 URL は `https://yuki-watanabe7.github.io/french-begginer/`。
- `gh-pages` は配布ファイルだけを置くブランチで、アプリの履歴と共通の祖先を持たない。main へ merge せず、PR も作らない。
- 可視性の変更（手順2）と教材の公開（手順3）は、どちらもまだ行っていない。
- 初回教材の候補は [合成教材3枚](public-snapshot.synthetic.json)：`bonjour`（こんにちは）、`s'il vous plaît`（お願いします）、`nous parlons`（私たちは話す）。実 DB は使わない。生成する `snapshot.json` の全文と sha256 を本人が確認して承認する。別の教材を使う場合は [#221 の書き出し手順](remote-readonly-contract.md) で作る。

**教材の公開は未承認・未実施。** この手順や実装のマージ、Issue の対応依頼は、教材の送信・Pages 有効化の承認に代わらない。

[公式の利用条件](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)では、Free は公開 repo でだけ Pages を使える。追加契約やドメイン購入は不要である。public にすると、この repo の標準 runner による Actions は無料扱いになる（[Actions 課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)）。配布は branch から行うので、Pages 用の build workflow、cache、保存 artifact は追加しない。サイト上限 1 GB・帯域 soft limit 月 100 GB 内で使い、制限超過時は更新を止めて確認する。自動アップグレードしない。

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

自動検査だけでは人名・私的な文・権利・教材の誤りを判定できない。**本人は `snapshot.json` の全文、sha256、公開 URL、誰でも保存できることを確認する。** 承認はこの内容と公開先に対して得る。内容が変われば再確認する。アプリのソースや個人 Snapshot を main / develop へ commit しない。承認済みの公開教材は、`gh-pages` の公開履歴に残す方式である。

[サブパスでの表示確認](readonly-viewer.md)と同様に、配布フォルダーを `french-begginer/` の下に置いてローカルで開く。画面・カード・答え・書き出し日時、同じ階層の静的ファイル以外への通信がないことを確認する。承認した配布フォルダーは、次の更新時にも前の版に戻せるよう手元に残す。

## 2. アプリ repo を public にする（一度だけ。外部変更あり）

public にすると、コード・全履歴・Issue / PR とコメント・保持期間内の Actions ログを誰でも読める。取得されたコピーは、private に戻しても回収できない。fork が作られると、private に戻した後も残る（[公式](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)）。所有者が下記の確認結果を読んでから行う。

### 2026-11-07 の確認結果

対象は全ブランチの履歴（216 commit、過去に存在したパス 347）、Issue / PR 233 件、コメント 162 件、Actions の設定。

| 確認項目 | 結果 |
|---|---|
| DB・音声・PDF・`.env`・バックアップ | 履歴を通じて一度も commit されていない。`.env.example` だけ |
| 秘密情報らしい文字列 | テスト用の合成値2件（`sk-private…`、`sk-synthetic…`）と、[TTS 検証手順](../tts_verification.md)のプレースホルダー `sk-xxxx…` だけ。`ghp_`・`AKIA`・秘密鍵などはない |
| IP アドレス・パス | 例示用（`192.168.1.20`、`10.0.0.1`、`100.64.0.1` など）とテスト用の `/Users/yuki/private.txt` だけ |
| 学習データ・第三者の教材 | 評価は合成学習者と固定 fixture。実利用の学習履歴、取り込んだ Source の原文、外部の URL はない（YouTube の URL は `abcdefghijk` などの例） |
| Issue / PR・コメント | 個人的な情報はない（家族の語は単語教材）。家庭内で認証なし HTTP を動かす設計の記述はあるが、実際の IP・ホスト名はなく、ルーターのポートも開けない構成である |
| コミットのメールアドレス | public の他の repo（DME）と同じで、新たに出るものではない |
| artifact・Release | 0 件 |
| Actions secrets | `CLAUDE_CODE_OAUTH_TOKEN`・`OPENAI_API_KEY`。値は public にしても見えない。fork からの PR の workflow には渡らない |
| `@claude` の起動 | `claude.yml` を、所有者・collaborator が書いた Issue とコメントでだけ動くように絞った。claude-code-action 自体も書き込み権限のない人の依頼を拒否する。Claude の全出力をログに出す `show_full_output` は既定の `false` のまま |

過去 747 回の Actions 実行ログは、全部は読んでいない。secrets は GitHub がログ上で伏せる。LICENSE は置かない（閲覧はできるが、利用の許諾は与えない）。

### 変更する

```bash
gh repo edit Yuki-Watanabe7/french-begginer --visibility public --accept-visibility-change-consequences
gh repo view Yuki-Watanabe7/french-begginer --json visibility --jq .visibility  # PUBLIC
```

Settings → General → Danger Zone → Change visibility からでもよい。

## 3. 承認後だけ初回公開する（外部変更あり）

手順2の後に行う。`gh-pages` ブランチの作成と Pages の有効化を伴い、配布ファイルは誰でも取得・保存できる。教材の承認がなければここから先を実行しない。

以下の `bundle` には、本人が確認した生成済みフォルダーを指定する。アプリの Git 履歴・ファイルをコピーせず、空の一時 Git repo から履歴を持たない `gh-pages` を作る。

```bash
app_repo=Yuki-Watanabe7/french-begginer
bundle=/tmp/french-public-review/site
shasum -a 256 "$bundle/snapshot.json"  # 本人が承認した値と照合する
deploy_checkout=$(mktemp -d)
git -C "$deploy_checkout" init -b gh-pages
git -C "$deploy_checkout" remote add origin "https://github.com/$app_repo.git"
git -C "$deploy_checkout" ls-remote --heads origin gh-pages  # 何も出ないことを確かめる。出たら手順4で更新する
cp -R "$bundle/." "$deploy_checkout/"
git -C "$deploy_checkout" add -- .nojekyll index.html assets snapshot.json
git -C "$deploy_checkout" diff --cached --stat
git -C "$deploy_checkout" diff --cached -- snapshot.json
git -C "$deploy_checkout" commit -m "Publish approved public learning materials"

# ここから外部変更。
git -C "$deploy_checkout" push origin gh-pages
gh api --method POST "repos/$app_repo/pages" \
  -f build_type=legacy -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

Pages の Source は **Deploy from a branch / gh-pages / /(root)**。`.nojekyll` は Jekyll による加工を省く指定で、GitHub の配布処理だけが走る（[公式のブランチ配布手順](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)）。通常の CI は main / develop への push でだけ動くので、`gh-pages` への push では動かない。GitHub トークンをファイルや公開 repo へ保存しない。

```bash
gh api "repos/$app_repo/pages" --jq '{html_url,status,source,https_enforced}'
gh api "repos/$app_repo/pages/builds/latest" --jq '{status,error,commit}'
```

配布成功の commit と URL を確かめ、公開 URL の `snapshot.json` を取得して、承認したファイルと sha256 を照合する。スマホの携帯回線からカードと答えを開き、自宅 PC が停止中でも読めることを本人が確認する。公開を試していない段階で実施済みと記録しない。#223 は公開・実機確認と関連 PR のレビュー／マージを確認するまで閉じない。

## 4. 更新する

まず品質検査と手順1で、新しい候補を**別フォルダー**へ作る。本人が新しい教材の全文・sha256 と同じ公開先を承認してから、次を行う。

```bash
app_repo=Yuki-Watanabe7/french-begginer
bundle=/tmp/french-public-next/site
shasum -a 256 "$bundle/snapshot.json"  # 今回承認した値と照合する
update_root=$(mktemp -d)
git clone --single-branch --branch gh-pages "https://github.com/$app_repo.git" "$update_root/repo"
git -C "$update_root/repo" rev-parse HEAD  # 前の公開版の commit を控える
git -C "$update_root/repo" rm -r --ignore-unmatch .
cp -R "$bundle/." "$update_root/repo/"
git -C "$update_root/repo" add -- .nojekyll index.html assets snapshot.json
git -C "$update_root/repo" diff --cached --stat
git -C "$update_root/repo" diff --cached -- snapshot.json
git -C "$update_root/repo" commit -m "Update approved public learning materials"
git -C "$update_root/repo" push origin gh-pages
```

削除するのは一時 checkout 内の旧配布ファイルだけ。以前の JS を残さず置き換える。公開完了と新しい教材の sha256 を手順3と同様に確認する。main へのマージや develop への push だけでは教材サイトは更新されない。

## 5. 失敗・戻し・停止

- **検査失敗・push 失敗**：公開先へ反映されていなければ元の公開版を利用する。配布処理の失敗時も Pages の status と公開 URL を確認し、元の版が利用できるか実際に確かめる。
- **更新後に表示が壊れた**：`gh-pages` だけを clone し、直前の更新 commit を `git revert <更新commit>`、`git push origin gh-pages` する。連続更新なら、控えた正常版のフォルダーを手順4で配布し直す。再配布の成功と元の教材の sha256 を確認する。
- **公開を止める**：Settings → Pages → サイト URL 横のメニュー → **Unpublish site**。進行中の配布処理も Actions で停止し、以後の `gh-pages` push を止める。公開 URL と `snapshot.json` が取得できないことを確認する（[公式の停止手順](https://docs.github.com/en/pages/getting-started-with-github-pages/unpublishing-a-github-pages-site)）。停止後も新しい配布で再公開されるため、再開は本人の判断後に行う。

**Pages を停止しても、`gh-pages` のファイル・Git 履歴・保存済みコピーは消えない。** 配布専用 repo なら repo ごと消せたが、アプリ repo は消せない。誤公開なら `git push origin --delete gh-pages` でブランチを消し、対応を本人と決める。ブランチを消しても、clone・fork と、SHA を指定した GitHub 上の表示には残りうる。GitHub Support が消すのは秘密情報などに限られる（[公式](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)）。第三者が保存したコピーは回収できない。初回承認時からこの方式を説明する。

repo を private に戻すと、Free では Pages の公開も止まる。ただし、それまでに読まれた内容や fork は残る（手順2）。

## 検証と残作業

`bash scripts/quality-check.sh` は通常の検査と、合成教材による専用ビルド・配布フォルダー生成を行う。テストは公開可能な項目だけのコピー、不正教材・混入ファイル・リンクの拒否、既存版と Git 作業ツリーの保護、コピー失敗時に途中の版を出さないことを検証する。外部へは送信しない。

repo の public 化、実際の公開、公開後のスマホ確認は、本人の操作と承認の後に行う。新しい契約と本人認証基盤の追加は本手順に含まれない。

### 2026-11-05 の実装検証結果

- `bash scripts/quality-check.sh` 成功。Backend 2,037 件成功・実 LLM 評価 1 件スキップ、Frontend 407 件成功。lint / format 検査、通常版と閲覧専用版の両ビルド、合成教材での配布準備が成功。
- 配布境界の追加テスト17件が成功。実 DB・実教材・API キーは使っていない。
- 候補は `.nojekyll`（0 bytes）、`index.html`（904 bytes）、独立 JS（149,074 bytes）、合成 `snapshot.json`（755 bytes）の4ファイル。教材の sha256 は `38f62357d9bf8c8c0bf8ad32e9fc9b3dde2df028f51b0536ae8d9a335eb5d600`。
- Chrome でローカルの `/french-beginner-materials/` 配下を開き、3枚のカード・答え・説明・UTC の書き出し日時を確認。HTML / JS / JSON の取得が成功し、配布元のバイト列と一致。通常アプリの API・DB 設定・ブラウザ保存・ソースマップへの参照が生成物にないことも確認。
- 公開 repo の作成・Pages 設定・外部配布・携帯回線／スマホ実機確認は未実施。#223 は未完了のまま維持する。

### 2026-11-07 の再検証（配布先の変更後）

- `bash scripts/quality-check.sh` 成功。Backend 2,037 件成功・1 件スキップ、Frontend 407 件成功。配布候補の4ファイルと教材の sha256 は 2026-11-05 と同じ。
- 変えたのは文書と `claude.yml` だけで、ビューアー・スクリプト・テストは変えていない。ビルドの `base` は `./` なので、サブパスが `/french-begginer/` になっても生成物は変わらない。ブラウザでの表示確認はやり直していない。
- repo の public 化、`gh-pages` の作成、Pages 設定、外部配布、携帯回線／スマホ実機確認は未実施。
