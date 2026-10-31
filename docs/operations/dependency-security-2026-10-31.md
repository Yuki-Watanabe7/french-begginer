# 2026-10-31 の依存更新と脆弱性評価（#226）

[#226](https://github.com/Yuki-Watanabe7/french-begginer/issues/226) は、家庭内本番の運用開始前に、本番イメージの修正可能な critical / high と frontend 開発依存の high を解消するための変更。LAN 公開、学習 DB の移行、Python のメジャー更新、CI へのスキャン常設は含まない。

**未修正の zlib に対する所有者の受け入れ承認は未取得。Issue は開いたままにし、本番運用開始・LAN 公開は保留する。** 以下の評価は受け入れ案であり、承認済みという意味ではない。

## 更新内容と選定根拠

| 対象 | 更新前 → 更新後 | 根拠 |
|---|---|---|
| anyio | 4.13.0 → 4.14.2 | CVE-2026-63374 の修正。公開 2026-07-12 |
| certifi | 2026.5.20 → 2026.10.19 | GHSA-6q48-6c7w-9gw2 の修正。版名と異なり実際の PyPI 公開は 2026-10-20 |
| pypdf | 6.19.0 → 6.21.4 | PDF 解析のリソース消費・無限ループの high 10 件を修正。公開 2026-10-28。`pyproject.toml` の最低版も更新 |
| starlette | 1.2.0 → 1.3.1 | CVE-2026-54283 の修正。公開 2026-06-12 |
| Python ベース | 3.12.16-slim-bookworm → 3.12.16-slim-trixie | Python は同じ 3.12.16。Debian 12 → 13 で util-linux / perl の high 7 件が消える。OS 全体の `apt-get upgrade` を本番 build に追加しない |
| nginx 最終イメージ | ベースの版・digest は維持 | curl と未使用の image-filter / xslt / njs / geoip モジュールを削除。依存の brotli / libxml2 も削除。zlib は `1.3.2-r1` を明示して更新（Alpine 公開 2026-10-06）。一括 `apk upgrade` はしない |
| Vite | 6.4.2 → 6.4.5 | 6 系のまま high を修正。公開 2026-10-21。6.4.4 は moderate の GHSA-8g5g-mxqh-grgj が残るため採用しない |
| Vitest / coverage-v8 | 4.1.7 → 4.1.12 | mocker の修正を同じ版の組合せで取り込む。公開 2026-10-15 |
| frontend 間接依存 | `npm audit fix` で互換範囲内の修正版へ | brace-expansion 1.1.21 / 5.0.12、browserslist 4.29.5、js-yaml 4.3.2、nanoid 3.3.20、postcss 8.5.32、source-map-js 1.2.2、undici 7.30.1。実際の依存グラフは `package-lock.json` |

FastAPI 0.136.3 の公開メタデータの Starlette 制約は `starlette>=0.46.0`。1.3.1 と互換なので FastAPI 自体は更新しない。Python 依存の変更は上記 4 パッケージだけで、開発環境・本番が同じ lock を使う。

通常の「公開後 2 週間待つ」方針に対し、certifi / pypdf と 2026-10-28 公開の trixie イメージは、既存の critical / high を解消するセキュリティ更新として待たずに採用する。Vite 6.4.5 と `npm audit fix` で選んだ一部の間接依存（browserslist / postcss 等）も、既知脆弱性の修正版とその依存グラフをまとめて検証するための例外とする。最新版への一括メジャー更新はしない。lock の hash とイメージ digest を固定し、既存の回帰テスト、ビルド、スキャン、localhost での起動確認を組み合わせる。

公開日・制約の一次情報: [PyPI anyio](https://pypi.org/project/anyio/4.14.2/)、[certifi](https://pypi.org/project/certifi/2026.10.19/)、[pypdf](https://pypi.org/project/pypdf/6.21.4/)、[pypdf 変更点](https://github.com/py-pdf/pypdf/releases/tag/6.21.4)、[Starlette](https://pypi.org/project/starlette/1.3.1/)、[FastAPI JSON](https://pypi.org/pypi/fastapi/0.136.3/json)、[Vite メタデータ](https://registry.npmjs.org/vite)、[Alpine zlib](https://pkgs.alpinelinux.org/package/v3.24/main/aarch64/zlib)。イメージの更新日は Docker Hub のタグ API と `docker buildx imagetools inspect` で確認した。

### ベースイメージの固定値

| 対象 | タグ | 複数プラットフォームを含む digest |
|---|---|---|
| backend | `python:3.12.16-slim-trixie` | `sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07` |
| web | `nginxinc/nginx-unprivileged:1.30.6-alpine` | `sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03`（変更なし） |
| frontend build / dev | `node:22.23.4-alpine` | `sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914`（変更なし） |

ベースだけでは最終イメージのパッケージは決まらない。web は上記の削除と zlib の修正を含めて再スキャンする。Alpine のリポジトリから固定版が消えたときは build が失敗する。その際は固定を外さず、利用可能な修正版・digest とスキャン結果を確認して更新する。

## スキャン結果

Docker Scout 1.27.0、Docker Desktop の linux/arm64 上で実行。critical / high のみを対象とし、検出の除外・抑制はしていない。amd64 等の別プラットフォームにこの件数を流用しない。

```bash
bash scripts/production_compose.sh build
docker scout cves local://french-production-backend:local --only-severity critical,high
docker scout cves local://french-production-web:local --only-severity critical,high
cd frontend
npm audit --json
npm audit --omit=dev --json
```

| 対象 | 更新前 | 更新後 |
|---|---|---|
| backend 最終イメージ | critical 2 / high 19 | critical 0 / high 1（下記 zlib のみ） |
| web 最終イメージ | critical 1 / high 2（#219 の記録） | critical 0 / high 0 |
| frontend 全依存 | critical 0 / high 8 / moderate 14 | critical 0 / high 0 / moderate 10（ESLint 系） |
| frontend 実行時依存（`--omit=dev`） | 0 件 | 0 件 |

検証した最終イメージの ID は backend `sha256:a866bda6458dcc6271a39f78fbb64164953a2a1374c8ef85356f1321c27f6016`、web `sha256:1e97dea4e95a0bd10d3ab32a458887c4deda8fbc4c05c5d438a592042f4622a9`。`--only-fixed --only-severity critical,high --exit-code` を付けた backend の追加確認も検出なし・終了コード 0。これらはコミット前の作業ツリーから作成したローカルイメージで、provenance にある基点のコミットだけでは今回の変更を含む内容を表せない。再ビルド時はこの変更を含むソースと lock を使って再スキャンする。

### 残る zlib の受け入れ案（所有者承認待ち）

- 対象: backend の Debian 13 `zlib 1:1.3.dfsg+really1.3.1-1`、high の **CVE-2026-85091**。Scout は `not fixed` と報告する。[Debian Security Tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091) でも trixie は vulnerable、修正は unstable のみ。別の Debian リリースのライブラリを混ぜて回避しない。
- 影響: 非ブロッキングの gzip 書込が停止した後、`gzprintf()` / `gzvprintf()` から `gz_vacate()` を通る条件で heap buffer overflow が起こり得る。成立すれば backend プロセスの停止やメモリ破壊に繋がる。
- 到達性の評価: このアプリは上記 C の gzip 書込 API を直接呼ばない。PDF は読み込み・テキスト抽出、外部 HTTP は取得・展開であり、問題の gzip 書込処理とは異なる。backend に gzip 出力機能や GZipMiddleware はなく、nginx でも gzip は有効化していない。**アプリからの既知の到達経路は確認していない、という評価であり、到達不可能の証明ではない。** バージョン範囲には upstream とディストリビューションの評価差もあるため、検出を消したり影響なしと断定したりしない。
- 緩和条件: localhost 限定・合成データで検証。LAN 運用時も所有者の管理端末だけ、非 root、読取専用 rootfs、権限追加禁止の設定を維持する。これらは zlib 自体の修正ではない。
- 提案: trixie の修正版が提供されるまで条件付きで受け入れ、提供時にイメージ更新・全チェック・再スキャンを行う。gzip 書込、圧縮したエクスポート、ネイティブ拡張を追加するときにも到達性を再評価する。修正の有無は運用開始前とイメージ更新時に確認する。
- 承認者: Yuki-Watanabe7。**承認日・承認記録: 未取得**。承認されない場合は localhost での検証までに留め、修正版を待つ。

### 開発・ビルドにだけ残る検出

Node ベースイメージ単体（上記 digest、arm64）の Scout 結果は critical 0 / high 10（パッケージ別計上、同じ CVE の重複を含む）。同梱 npm / Yarn が持つ brace-expansion、pacote、picomatch、ip-address、sigstore が対象で、アプリの `package-lock.json` の監査とは別の依存グラフ。これらのツールは最終 web イメージにはコピーされない。

今回は Node 本体・同梱パッケージマネージャの更新には踏み込まず、この検出を残す。ビルドは管理下のソースと固定 lock を使い、実 API キーや学習 DB を渡さない。開発サーバーを信頼できない端末へ公開しない。本番イメージの critical / high が 0/1 件になったことを、ビルド用ツールもすべて解消したという意味で扱わない。Node イメージの次回更新時に、同梱 npm / Yarn を含めてスキャンする。

frontend の moderate 10 件は minimatch の GHSA-g3hv-75wg-m249 と、それを使う ESLint / typescript-eslint の依存先への波及。minimatch 自体に新しいメジャーの修正版があっても、要求する版の範囲では `npm audit fix` で解消できない。互換性を無視した override は追加しない。この検出は lint の処理量への影響で、ブラウザで実行する React や最終 web イメージには含まれない。

## 回帰・稼働検証

| 確認 | 結果 |
|---|---|
| `bash scripts/quality-check.sh` | 成功。main の取り込み確認、ruff check / format、pytest **1,962 passed / 1 skipped**、ESLint、Vitest **30 files / 370 tests passed**、TypeScript / Vite 6.4.5 build。skip は任意の実 LLM 評価 |
| `production_compose.sh build` → `up -d --wait` | 成功。backend / web とも healthy。`127.0.0.1:8080` のみ公開 |
| `python -m app.persistence.readiness` | `ready: ok`、`schema_version=5` |
| `probe_production_boundary.sh 127.0.0.1` | 12 項目すべて PASS。8000 / 5173 は接続不可、未知 Host は 400、別 Origin / Origin なし / 不正 TTS は 403 |
| 既存 DB の保持 | 再作成と probe の前後で、読み取り専用接続から全テーブルの件数が一致。開発 DB は使用せず、教材・履歴の追加は行わない |
| コンテナ内の実体 | backend は Python 3.12.16・更新した 4 依存・uid 10001。web は zlib 1.3.2-r1・uid 101。curl / brotli / libxml2 / 追加モジュールは残らず、`nginx -t` 成功 |

pypdf は既存 `test_pdf_ingestion.py` で、フランス語の抽出結果・ページ位置、暗号化 PDF、破損 PDF、OCR が必要な PDF、サイズ・ページ数・時間上限、HTTP エラーと保存の有無を確認した。例外は `PdfIngestionError` へ変換する既存契約を維持し、アプリコード・DB schema は変更していない。

Starlette の TestClient が `httpx` を非推奨として `httpx2` を推奨する warning が 1 件出るが、既存テストはすべて成功した。本番の HTTP クライアントには変更を加えず、テストクライアントの移行は今回に含めない。
