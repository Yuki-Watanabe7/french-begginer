# TTS API 技術検証メモ

issue #77 の技術検証として実施した内容の記録。

## 選定したTTS API

**OpenAI TTS API**

選定理由:
- APIキーが `OPENAI_API_KEY` 1つで済みシンプル
- フランス語の発音品質が高い
- Python SDK (`openai` パッケージ) が整備されており、既存スタックと相性が良い
- `tts-1` モデルは低レイテンシ向け。音質優先の場合は `tts-1-hd` が選択肢

モデル・ボイス: `tts-1` / `alloy`（ニュートラルな声質）

## 実装した内容

| ファイル | 役割 |
|----------|------|
| `backend/app/services/tts_service.py` | TTS API呼び出しロジック。`generate_tts_audio(text) -> bytes` |
| `backend/app/api/tts.py` | `/api/tts/speak?text=...` エンドポイント |
| `.env.example` | 必要な環境変数の説明 |

### 動作確認用コマンド

```bash
# サーバー起動
cd backend
uv run uvicorn app.main:app --reload --port 8000

# 音声ファイルを取得して再生確認
curl "http://localhost:8000/api/tts/speak?text=un%20livre" -o test.mp3

# 動作確認テキスト例
curl "http://localhost:8000/api/tts/speak?text=une%20maison" -o test.mp3
curl "http://localhost:8000/api/tts/speak?text=l%27%C3%A9cole" -o test.mp3
```

## レスポンス形式の考察

### 採用: audio/mpeg バイナリを直接返す方式

```
GET /api/tts/speak?text=un+livre
→ Content-Type: audio/mpeg
→ バイナリストリーム
```

**採用理由:**
- 一時ファイルやURLを返す方式と比べて実装がシンプル
- クライアント側でURL管理が不要
- `StreamingResponse` でメモリ効率よく返せる

**トレードオフ:**
- キャッシュはサーバー側で対応が必要（後続issueで実装）
- CDN配信する場合はURL方式に切り替えが必要

## フロントエンドでの再生方式

### 方式1: `<audio>` 要素に src を直接指定

```tsx
<audio
  src={`/api/tts/speak?text=${encodeURIComponent(text)}`}
  controls
  autoPlay
/>
```

**特徴:**
- 実装が最もシンプル
- ブラウザがネイティブにストリーミング再生
- ボタン連打でリクエストが重複する可能性あり

### 方式2: Blob URL を生成して再生（推奨）

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

**特徴:**
- 再生開始前に全データを受信するため、安定した再生が可能
- ローディング状態の制御がしやすい
- `URL.revokeObjectURL` で確実にメモリ解放できる
- ボタン連打防止の制御を追加しやすい

**推奨**: 名詞問題画面への本格統合時は **Blob URL 方式** を採用する。
理由: ローディング状態の管理とメモリ解放が明示的に行え、UXの制御がしやすい。

## エラー時の挙動

| 状況 | HTTPステータス | レスポンス例 |
|------|---------------|-------------|
| APIキー未設定 | 503 | `{"detail": "TTS service unavailable: OPENAI_API_KEY is not set"}` |
| APIキーが無効 | 503 | `{"detail": "TTS service unavailable: OPENAI_API_KEY is invalid"}` |
| テキストが空 | 400 | `{"detail": "Text must not be empty"}` |
| テキストが500文字超 | 400 | `{"detail": "Text is too long (max 500 characters)"}` |
| OpenAI API接続失敗 | 502 | `{"detail": "TTS API call failed: ..."}` |

フロントエンドでは、503の場合はユーザーへの通知なしにボタンを非表示にする対応が想定される。
502の場合はリトライ可能なエラーとして扱う。

## キャッシュキー案

後続issueでキャッシュを実装する際のキー設計案:

```python
import hashlib

# キャッシュキー形式
# tts:{provider}:{model}:{voice}:{text_hash}
key = f"tts:openai:tts-1:alloy:{hashlib.sha256(text.encode()).hexdigest()}"

# TTL候補: 7日（フランス語の発音は変わらないため長期キャッシュ可）
# ストレージ候補: Redis（将来的にDB拡張と同タイミングで導入）
# または: ファイルシステムキャッシュ（シンプルだが水平スケールに不向き）
```

## 後続issue実装時の注意点

- 名詞問題画面への音声再生ボタン追加: `NounArticleCard` か `NounGenderCard` にボタンを追加する想定
- テキストは冠詞付き名詞（例: `un livre`, `l'école`）を渡すと自然な発音になる
- `tts-1` は低レイテンシだが音質が若干劣る。品質重視なら `tts-1-hd` に変更可
- ボイスは `alloy`（ニュートラル）を採用したが、`nova`（女性的）などへの変更も容易
