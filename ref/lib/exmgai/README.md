# exmgai

社内向け Azure OpenAI、AWS Bedrock、Microsoft Foundry ラッパーライブラリ。LLM をシンプルに利用できます。
社内向け Azure OpenAI、AWS Bedrock、Microsoft Foundry ラッパーライブラリ。LLM をシンプルに利用できます。
## インストール

```bash
uv add "exmgai @ git+https://github.com/tomotaka-nagano/exmgai.git"
```

## セットアップ

`env.toml.example` をコピーして `env.toml` を作成し、利用するモデルの情報を記入してください:

```bash
cp env.toml.example env.toml
```

### 認証方式

**API Key 認証**:

```toml
[auth]
type = "api_key"

[[models]]
name = "gpt-4o"
endpoint = "https://your-resource.openai.azure.com/openai/v1/"
deployment = "gpt-4o"
api_key = "your-api-key"
context_window = 128000
max_output_tokens = 16384
input_token_cost = 2.50   # dollars/Mtoken
output_token_cost = 10.00 # dollars/Mtoken
```

**Entra ID 認証** (`az login` 後に利用可能):

```toml
[auth]
type = "entra_id"

[[models]]
name = "gpt-4o"
endpoint = "https://your-resource.openai.azure.com/openai/v1/"
deployment = "gpt-4o"
context_window = 128000
max_output_tokens = 16384
input_token_cost = 2.50   # dollars/Mtoken
output_token_cost = 10.00 # dollars/Mtoken
```

認証方式は Microsoft Foundry でも共通です。API Key 認証ではモデルの `api_key`、Entra ID 認証では
`https://cognitiveservices.azure.com/.default` scopeを使用します。

## 使い方

```python
from exmgai import Client

# 利用可能なモデルを確認
print(Client.get_available_models())  # -> ['gpt-4o', 'gpt-5.1', ...]

# クライアント作成
client = Client("gpt-4o")
print(client.context_window)  # -> 128000
print(client.max_output_tokens)  # -> 16384

# 会話を開始
res = client.chat.create("こんにちは")
print(res.content)

# トークン使用量とコストを確認
print(res.input_tokens)   # -> 入力トークン数
print(res.output_tokens)  # -> 出力トークン数
print(res.cost())         # -> コスト（ドル）

# 会話を続ける
res = client.chat.add("今日はいい天気ですね")
print(res.content)
```

### Structured Output (Pydantic)

```python
from pydantic import BaseModel, Field

class AnswerFormat(BaseModel):
    answer: str = Field(description="The answer")
    confidence: float = Field(description="0-1")

res = client.chat.create("フランスの首都は？", response_format=AnswerFormat)
print(res.answer)       # -> 'パリ'
print(res.confidence)   # -> 1.0
```

### システムプロンプト

```python
# パターン1: インスタンス生成時
client = Client("gpt-4o", system_prompt="あなたは優秀なアシスタントです。")

# パターン2: プロパティで設定
client.system_prompt = "あなたは優秀なアシスタントです。"

# パターン3: チャット生成時
res = client.chat.create("こんにちは", system_prompt="あなたは優秀なアシスタントです。")
```

### ストリーミング

`mode='streaming'` を指定すると、レスポンスをチャンク単位で逐次取得できます。

```python
stream = client.chat.create('こんにちは', mode='streaming')
for chunk in stream:
    print(chunk, end='')

# ストリーム完了後、完全なテキストを取得
print(stream.content)
```

`add` メソッドでも同様に利用できます:

```python
stream = client.chat.add('今日はいい天気ですね', mode='streaming')
for chunk in stream:
    print(chunk, end='')
```

Structured Output と組み合わせることも可能です:

```python
stream = client.chat.create('フランスの首都は？', mode='streaming', response_format=AnswerFormat)
for chunk in stream:
    print(chunk, end='')

print(stream.answer)       # -> 'パリ'
print(stream.confidence)   # -> 1.0
```

### 画像キャプション

Vision対応モデルを使って画像のキャプション（説明文）を生成できます。

```python
# ファイルパスを指定
res = client.caption.create('path/to/image.jpg')
print(res.content)

# URLを指定
res = client.caption.create('https://example.com/photo.png')
print(res.content)

# カスタムプロンプト
res = client.caption.create('image.jpg', prompt='日本語で詳細に説明してください')
print(res.content)
```

Structured Outputと組み合わせて構造化された結果を取得:

```python
class ImageDescription(BaseModel):
    subject: str = Field(description='画像の主題')
    mood: str = Field(description='全体的な雰囲気')

res = client.caption.create('image.jpg', response_format=ImageDescription)
print(res.subject)  # -> '猫'
print(res.mood)     # -> '穏やか'
```

ストリーミングも対応しています:

```python
stream = client.caption.create('image.jpg', mode='streaming')
for chunk in stream:
    print(chunk, end='')
```

### Microsoft Foundry Decision

Microsoft Foundry にデプロイした `Microsoft-Decision-1` を利用できます。`endpoint` にはFoundryリソースのURL、
`deployment` にはモデルのデプロイ名を指定します。

```toml
[[models]]
name = "decision"
provider = "foundry"
endpoint = "https://your-resource.services.ai.azure.com"
deployment = "your-microsoft-decision-1-deployment"
api_key = "your-api-key"
input_token_cost = 0.60 # dollars/Mtoken
read_timeout = 600
```

```python
from exmgai import Client
from typesafe_sdk import Choice, Noul, Score

client = Client('decision')
response = client.decision.system_one(
    state='新しい取引申請を審査してください。',
    questions={
        'approve': Noul(instructions='承認すべきですか？'),
        'route': Choice(criteria={'manual': '手動審査', 'auto': '自動承認'}),
        'risk': Score(criteria=['低リスク', '中リスク', '高リスク']),
    },
)

print(response.answers['approve'])
print(response.usage.input_tokens)
print(response.cost())
```

非同期クライアントでは `await client.decision.system_one(...)` を使用します。Decision APIは `Noul`、`Choice`、
`Score` の質問に対応し、Box、画像、ストリーミングには対応していません。`cost()` は `input_token_cost` と
入力トークン数から費用を計算します。

## 開発

```bash
uv sync --extra dev
uv run python -m pytest --cov
uv run ruff check src/ tests/
```
```
