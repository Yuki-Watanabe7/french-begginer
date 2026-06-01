# TTS（テキスト読み上げ）機能 設定・運用ガイド

## 概要

TTS（Text-to-Speech）機能は OpenAI TTS API を使用してフランス語テキストを音声化する。
`/api/tts/speak` エンドポイントが `audio/mpeg` バイナリを返し、フロントエンドで再生できる。

> **重要**: TTS機能を使うためには `OPENAI_API_KEY` の設定が必要。
> ただし、動詞活用・名詞クイズなどの基本機能は **APIキーなしで利用可能**。

## 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `OPENAI_API_KEY` | TTS機能使用時のみ | OpenAI APIキー（`sk-...` 形式）。取得先: [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

## APIキー未設定時の挙動

| 状況 | HTTPステータス | レスポンス例 |
|------|---------------|-------------|
| APIキー未設定 | 503 | `{"detail": "TTS service unavailable: OPENAI_API_KEY is not set"}` |
| APIキーが無効 | 503 | `{"detail": "TTS service unavailable: OPENAI_API_KEY is invalid"}` |
| テキストが空 | 400 | `{"detail": "Text must not be empty"}` |
| テキストが500文字超 | 400 | `{"detail": "Text is too long (max 500 characters)"}` |
| OpenAI API接続失敗 | 502 | `{"detail": "TTS API call failed: ..."}` |

`OPENAI_API_KEY` 未設定の状態で `/api/tts/speak` を呼んでも、
`/api/questions/next` や `/api/nouns/next` など他のエンドポイントへの影響はない。

## ローカル開発環境での設定方法

### Docker Compose を使う場合（推奨）

ホストのシェル環境変数に `OPENAI_API_KEY` を設定すると、
docker-compose.yml のパススルー設定を通じてバックエンドコンテナに自動的に渡る。

```bash
export OPENAI_API_KEY=sk-xxxxxxxxxxxx
docker compose up
```

または、`.env.example` を参考に `backend/.env` ファイルを作成する方法もある（`.gitignore` 済み）:

```bash
cp .env.example backend/.env
# backend/.env の OPENAI_API_KEY= の値を実際のキーに書き換える
```

### Docker を使わずに backend を直接起動する場合

```bash
cd backend
OPENAI_API_KEY=sk-xxxxxxxxxxxx uv run uvicorn app.main:app --reload --port 8000
```

### 動作確認用コマンド

```bash
# サーバー起動後に音声ファイルを取得して再生確認
curl "http://localhost:8000/api/tts/speak?text=un%20livre" -o test.mp3

# APIキー未設定の場合は 503 が返ることを確認
curl -v "http://localhost:8000/api/tts/speak?text=un%20livre"
# → HTTP/1.1 503 Service Unavailable
```

## GitHub Codespaces での設定方法

GitHub Codespaces でTTS機能を有効にするには、リポジトリのシークレットを設定する:

1. GitHub リポジトリページで **Settings → Secrets and variables → Codespaces** を開く
2. **New repository secret** をクリック
3. Name: `OPENAI_API_KEY`、Value: APIキーを入力して保存
4. Codespace を再起動（または新しく作成）すると自動的に環境変数として注入される

シークレットを設定しない場合でも、基本機能（動詞活用・名詞クイズ）は通常通り使用できる。

## CIでのTTS取り扱い方針

**CIでは実際のOpenAI APIを呼び出さない。**

- `tests/test_tts.py` のTTS APIコールはすべて `unittest.mock.patch` でモック化
- `OPENAI_API_KEY` がなくても `bash scripts/quality-check.sh` が通る状態を維持する
- APIキー未設定時の503エラー等は、モックなしで実際のコードパスをテスト

これにより:
- CI に `OPENAI_API_KEY` のシークレット設定は不要
- OpenAIアカウントなしでテストを実行可能
- 実際のAPI呼び出しによる課金・レート制限なしでテスト可能

## コミット禁止事項

以下はリポジトリにコミットしないこと（`.gitignore` で除外済み）:

| 対象 | パス | 理由 |
|------|------|------|
| APIキー | `.env`, `backend/.env` | 秘密情報の漏洩防止 |
| TTS音声キャッシュ | `backend/.cache/` | バイナリファイルによるリポジトリ肥大化防止 |

## TTS音声キャッシュについて

生成した音声は `backend/.cache/tts/` にファイルとしてキャッシュされる。
キャッシュが存在すれば、`OPENAI_API_KEY` なしでも音声を返すことができる。

- **キャッシュキー形式**: `tts_openai_tts-1_alloy_{text_sha256}.mp3`
- **TTL**: 設定なし（手動削除まで保持）
- **用途**: 開発中の繰り返しリクエストによるAPIコスト削減

---

## 技術情報（issue #77 検証記録）

### 選定したTTS API

**OpenAI TTS API**

選定理由:
- APIキーが `OPENAI_API_KEY` 1つで済みシンプル
- フランス語の発音品質が高い
- Python SDK (`openai` パッケージ) が整備されており、既存スタックと相性が良い
- `tts-1` モデルは低レイテンシ向け。音質優先の場合は `tts-1-hd` が選択肢

モデル・ボイス: `tts-1` / `alloy`（ニュートラルな声質）

### 実装ファイル

| ファイル | 役割 |
|----------|------|
| `backend/app/services/tts_service.py` | TTS API呼び出しロジック。`generate_tts_audio(text) -> bytes` |
| `backend/app/services/tts_cache_service.py` | ファイルシステムキャッシュ。`backend/.cache/tts/` に音声を保存 |
| `backend/app/api/tts.py` | `/api/tts/speak?text=...` エンドポイント |
| `backend/tests/test_tts.py` | TTS APIのモックテスト（CI用） |
| `.env.example` | 必要な環境変数の説明 |

### レスポンス形式

```
GET /api/tts/speak?text=un+livre
→ Content-Type: audio/mpeg
→ バイナリストリーム
```

### フロントエンドでの再生方式

#### 方式1: `<audio>` 要素に src を直接指定

```tsx
<audio
  src={`/api/tts/speak?text=${encodeURIComponent(text)}`}
  controls
  autoPlay
/>
```

#### 方式2: Blob URL を生成して再生（推奨）

```ts
async function playTts(text: string): Promise<void> {
  const res = await fetch(`/api/tts/speak?text=${encodeURIComponent(text)}`)
  if (!res.ok) throw new Error(`TTS error: ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.onended = () => URL.revokeObjectURL(url)  // メモリ解放
  await audio.play()
}
```

**推奨**: 名詞問題画面への本格統合時は **Blob URL 方式** を採用する。
ローディング状態の管理とメモリ解放が明示的に行え、UXの制御がしやすい。

### 後続issue実装時の注意点

- 名詞問題画面への音声再生ボタン追加: `NounArticleCard` か `NounGenderCard` にボタンを追加する想定
- テキストは冠詞付き名詞（例: `un livre`, `l'école`）を渡すと自然な発音になる
- `tts-1` は低レイテンシだが音質が若干劣る。品質重視なら `tts-1-hd` に変更可
- ボイスは `alloy`（ニュートラル）を採用したが、`nova`（女性的）などへの変更も容易
