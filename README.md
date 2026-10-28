# trial-decision-model

Microsoft Foundry にデプロイした `Microsoft-Decision-1` を試す社内向け Web アプリです。
FastAPI が API と素の HTML・CSS・JavaScript を同一オリジンで配信し、モデルの利用には `exmgai` を使用します。

## 前提

- Python 3.13 以上、uv、Git
- Microsoft Foundry のリソース URL と `Microsoft-Decision-1` のデプロイ名
- モデルの利用権限、および API Key または Entra ID のサーバー用資格情報

exmgai は Git リポジトリのコミットを固定しています。依存関係は `uv.lock` で管理します。
ライブラリの参考資料は [ref/lib/exmgai/README.md](ref/lib/exmgai/README.md) にあります。

## セットアップ

プロジェクトのルートで実行します。以下は PowerShell の例です。

```powershell
uv sync --locked
Copy-Item env.toml.example env.toml
```

作成した `env.toml` の `endpoint` と `deployment`、認証情報を設定します。
`endpoint` は Foundry リソースの HTTPS URL です。API のパスを付加する必要はありません。
モデル設定の `name = "decision"` と `provider = "foundry"` は変更しないでください。
設定本体は Git 管理外です。実際のキーをサンプルやソースに記載しないでください。

### API Key 認証

```toml
[auth]
type = "api_key"

[[models]]
name = "decision"
provider = "foundry"
endpoint = "https://your-resource.services.ai.azure.com"
deployment = "your-microsoft-decision-1-deployment"
api_key = "your-api-key"
read_timeout = 600
input_token_cost = 0.0
```

### Entra ID 認証

ローカルでは Azure CLI をインストールして `az login` を実行し、次のように設定します。
`api_key` は不要です。

```toml
[auth]
type = "entra_id"
credential = "azure_cli"

[[models]]
name = "decision"
provider = "foundry"
endpoint = "https://your-resource.services.ai.azure.com"
deployment = "your-microsoft-decision-1-deployment"
read_timeout = 600
input_token_cost = 0.0
```

公開サーバーでは `credential = "default"` にすると Azure Identity の `DefaultAzureCredential` を使用します。
マネージド ID または環境変数など、配備環境に応じた資格情報とモデル呼び出し権限を用意してください。
認証には `https://cognitiveservices.azure.com/.default` のスコープを使用します。
これはサーバーから Foundry への認証です。閲覧者ごとのログインや資格情報の委譲ではありません。

### タイムアウトと費用

- `read_timeout` は HTTP 通信のタイムアウト設定で、1〜600秒を指定できます。
- `input_token_cost` は入力100万トークン当たりの USD 単価です。実際の契約に合わせて設定してください。
- 単価が未設定または `0.0` の場合、推定費用は表示しません。
- 推定費用は SDK が返す入力トークン数に基づく参考値で、実際の請求額を保証しません。
- 通信失敗時の自動再試行は行いません。タイムアウト後の再実行でも追加費用が発生する場合があります。
- 設定変更は次回の実行から反映されます。資格情報はブラウザーに送信しません。

## 起動

```powershell
uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --limit-concurrency 64
```

ブラウザーで http://127.0.0.1:8000 を開きます。停止はターミナルで `Ctrl+C` を押します。
ポートが使用中の場合は `--port 8001` などに変更してください。
接続設定がなくても画面・保存機能は使用でき、モデル実行時には設定不備のエラーを表示します。

### 社内公開

```powershell
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --limit-concurrency 64
```

アプリにログイン機能はありません。到達できる人は共通の接続設定でモデルを実行し、費用を発生させられます。
次の条件を満たす社内環境でのみ公開してください。

- ファイアウォールや既存のリバースプロキシで社内ネットワークにアクセスを限定する。
- 社内公開時は既存のリバースプロキシ等で HTTPS を終端し、平文通信を外部に公開しない。
- サーバーの資格情報を最小権限にし、設定ファイルへのアクセスとモデルの利用額を管理する。
- モデルの同時実行上限は1プロセス当たり4件。超過時は429を返す。複数ワーカーにすると上限も増える。
- プロキシでは転送先・転送ヘッダーを正しく設定する。HTTPS のプロキシを使う場合は uvicorn の
	`--forwarded-allow-ips` に信頼するプロキシの IP のみを指定する。

アプリは別オリジンからの POST と JSON 以外の POST を拒否しますが、これは利用者認証の代わりにはなりません。
公開インターネットへの直接公開は対象外です。入力する業務情報がモデルに送信可能かも確認してください。

## Docker Compose で起動

Linux PC の Docker Engine と Docker Compose v2.30 以降を使用します。
Windows では Docker Desktop の Linux コンテナーを使用できますが、後述の認証キャッシュの互換性に注意してください。
ホストで uv や Python を導入する必要はありません。イメージ内に Python 3.13、uv、Azure CLI を導入します。
[compose.yaml](compose.yaml) は、ホストの Azure CLI 保存領域をコンテナーへマウントする構成です。

### 設定の準備

初回のみ、プロジェクトのルートで実行します。既存の設定ファイルは上書きしないでください。

```bash
cp .env.example .env
cp env.toml.example env.toml
```

`.env` には [.env.example](.env.example) を参考に次の値を設定します。
`.env` と `env.toml` は Git 管理外で、Docker のビルドコンテキストからも除外しています。

| 設定 | 内容 |
| --- | --- |
| `APP_BIND_ADDRESS` | 公開先 IP。サンプルは別PCから接続可能な `0.0.0.0`。未指定時はローカル限定の `127.0.0.1` |
| `APP_PORT` | ホストの公開ポート。既定は `8512`。使用中なら空きポートへ変更 |

GitHub トークンは対象リポジトリの読み取りに必要な最小権限にしてください。
Fine-grained PAT の場合は対象リポジトリの Contents 読み取り権限と、必要に応じて組織側の承認を設定します。
トークンは `.env` に保存せず、後述のビルドコマンド実行時だけ環境変数 `GITHUB_TOKEN` として渡します。
既存の `.env` に `GITHUB_TOKEN` がある場合は、その行を削除してください。
トークンをチャットやソースに記載せず、`.env` を共有・コミットしないでください。
シェルに同名の環境変数が設定されている場合は、Compose の規則により `.env` より優先されます。

`env.toml` は前述の Entra ID 認証の例を使用し、次の設定にします。
モデルの `endpoint` と `deployment` も設定してください。API Key は不要です。

```toml
[auth]
type = "entra_id"
credential = "azure_cli"
```

### Azure CLI 認証情報の共有

ホストで `az login` を済ませ、必要なら `az account set --subscription <subscription-id>` で使用先を選択します。
マウント元は [compose.yaml](compose.yaml) で `${HOME}/.azure` に固定しています。
`HOME` は Compose を実行する Linux ユーザーのホームディレクトリです。`.env` でパスを設定する必要はありません。
ディレクトリと `env.toml` が存在しない場合、Compose は空のディレクトリを自動作成せず起動を拒否します。

- `env.toml` は `/app/env.toml` へ読み取り専用でマウントします。
- Azure CLI 保存領域は `/root/.azure` へ読み書き可能でマウントします。
- コンテナー内の `AZURE_CONFIG_DIR` は `/root/.azure` に固定します。
- Azure CLI がログやトークンキャッシュを更新するため、保存領域は読み取り専用にしていません。
- コンテナーはこの認証情報で Azure にアクセスできます。信頼できる環境でのみ使用してください。

**Windows のキャッシュ互換性に注意してください。** Windows 版 Azure CLI の認証情報は DPAPI や
WAM に依存する場合があり、単に `.azure` を Linux コンテナーへマウントしても再利用できないことがあります。
この場合、既存の Windows のキャッシュを削除・変換したり、暗号化を無効化したりしないでください。

推奨する代替方法は、WSL に Linux 版 Azure CLI を導入して `az login` し、WSL 側のキャッシュを共有する方法です。
WSL から Docker Desktop の WSL 統合を利用して Compose を実行すると、WSL ユーザーの `${HOME}/.azure` がマウントされます。
ホストとコンテナーで同じ Linux 形式のキャッシュを使用します。認証の期限切れ時も同じ環境で再ログインします。
保存領域への書き込みで所有権や権限に影響する場合があるため、共有範囲・ファイル権限も確認してください。

### ビルド・起動・停止

設定後、プロジェクトのルートで実行します。以下は Linux の Bash の例です。
`your-github-access-token` を exmgai リポジトリを取得できるトークンに置き換えてください。
`--build` は `docker compose up` のオプションです。

```bash
docker compose config --quiet
GITHUB_TOKEN='your-github-access-token' docker compose up -d --build
docker compose ps
docker compose logs -f app
```

この指定は当該コマンドのプロセスにだけ適用され、トークンを `.env` に保存したり、親シェルへ設定したりしません。
ただしコマンド履歴にトークンが残り、同一ユーザーや管理者からプロセスの環境変数を参照される可能性があります。
この PoC ではそのリスクを許容する運用です。履歴やターミナル出力を共有しないでください。
ビルド済みイメージを使う通常の起動は `docker compose up -d --no-build` で行い、トークンの指定は不要です。

ブラウザーで http://localhost:8512 を開きます。`APP_PORT` を変更した場合は URL のポートも変更します。
別PCからは `http://起動したPCのIPアドレス:8512` にアクセスします。
既存の保存した質問を使いたい場合は、以前と同じホスト名・ポートでアクセスしてください。
サンプルは全ネットワークインターフェースで接続を受け付けます。ファイアウォールで TCP `8512` の接続元を
信頼できる社内ネットワークに限定し、前述の HTTPS の条件を満たしてください。
起動したPCだけで使用する場合は `APP_BIND_ADDRESS=127.0.0.1` に変更してください。

```powershell
docker compose down
```

停止してもホストの設定・Azure CLI の認証情報・ブラウザーの保存した質問は削除しません。
モデルの同時実行上限はコンテナー1つにつき4件です。

### 認証とビルドの確認

Azure CLI の認証だけを確認する場合は、次を実行します。トークン自体は表示せず有効期限だけを確認します。

```powershell
docker compose run --rm app az account show --query name --output tsv
docker compose run --rm app az account get-access-token --resource https://cognitiveservices.azure.com/ --query expiresOn --output tsv
```

モデルの実行権限と疎通は、画面から別途確認してください。認証確認・ヘルスチェックだけではモデルの疎通は確認できません。

GitHub トークンはコマンド実行時の環境変数から Compose の build secret としてビルド時だけ渡します。
[Dockerfile](Dockerfile) は一時的な Git 設定で HTTPS URL にトークンを付加して `uv sync --locked --no-dev` を実行します。
依存定義やロックファイルにトークンを書き込まず、`ARG`・`ENV`・恒久的な Git 設定にも残しません。
認証情報入りの取得キャッシュを残さないよう、uv のキャッシュも無効にしています。
実行中のコンテナーへ GitHub トークンを渡すことはありません。
トークンを変更して再取得を試す場合は、次のようにキャッシュなしで再ビルドしてから再起動してください。

```bash
GITHUB_TOKEN='your-github-access-token' docker compose build --no-cache app
docker compose up -d --no-build
```

配備前に Docker Scout などで完成したイメージの脆弱性を確認してください。
ベースイメージのタグだけの診断では、ビルド中に更新した OS パッケージや追加した Azure CLI まで評価できません。
新しいベースイメージと OS 更新を取り込む場合も、トークンを指定して再ビルドし、起動し直します。

```bash
GITHUB_TOKEN='your-github-access-token' docker compose build --pull --no-cache app
docker compose up -d --no-build
```

高深刻度の指摘が残る場合は、対象 CVE と修正版の有無を確認してから配備してください。

## 画面と質問形式

1. 質問・コンテキストと、利用する形式のチェックを設定します。
2. 各形式の指示文、Choice の選択肢、Score の採点基準を編集します。
3. 実行すると、有効な形式をまとめて1回の `system_one` 呼び出しに送信します。

| 形式 | 入力 | 結果 |
| --- | --- | --- |
| Noul | 指示文は必須 | 肯定確率。SDK の `noul`（0〜1）を百分率で表示 |
| Choice | キーと説明のリスト、任意の指示文 | 選択されたキー・説明、信頼度、選択肢別の確率 |
| Score | 順序付き採点基準、任意の指示文 | 0から始まる基準番号の期待スコア、信頼度、各基準の確率 |

Score は固定の100点満点ではありません。例えば3基準なら番号は0・1・2で、期待スコアは小数にもなります。
無効にした形式の入力は画面内に保持し、モデルには送信しません。少なくとも1形式を有効にしてください。
実行中は編集・保存・復元を停止し、二重送信を防ぎます。再実行・入力変更・復元では古い結果を消去します。
取得した回答は各形式の表示欄と JSON で確認できます。

アプリの入力上限は質問20,000文字、各指示文・基準・説明2,000文字、Choice／Score各20行です。
Choice のキーは英数字・`_`・`-` の1〜64文字で重複不可です。
これらはアプリ側の保護上限であり、モデル固有の制約を保証するものではありません。
画像・Box・ストリーミング・会話の継続・形式ごとの複数質問には対応しません。

## 質問の保存・復元

初回アクセス時に保存領域が未作成の場合は、「ディープインパクト」「物語文」の2件を初期登録します。
一覧から選択して復元すると、サンプルの本文・指示文・選択肢・採点基準・有効状態を読み込めます。
サンプルの読み込みだけではモデルを実行せず、回答も同梱しません。
サンプルデータは [app/static/default-questions.json](app/static/default-questions.json) にあります。

既存の保存領域がある場合は、空の一覧でもサンプルを追加・上書きしません。
サンプルは通常の質問と同様に編集・保存・削除でき、削除後の再読み込みで復活しません。
保存キー自体を削除して初期化した場合は、次回アクセス時にサンプルを再登録します。

保存名を入力して保存ボタンを押すと、名前付き質問セットを `localStorage` に保存します。
一覧から選択して復元・削除できます。同名保存の上書きと削除には確認があります。
未完成の質問も保存できますが、実行時には入力検証を行います。

- 保存対象：質問本文、形式の有効状態、指示文、選択肢、採点基準。
- 保存しない情報：モデルの回答、トークン数・費用、接続先、資格情報。
- 上限は50セット、保存名は80文字。サーバー側への保存・共有・同期はしない。
- 保存領域はオリジン（プロトコル・ホスト・ポート）とブラウザープロファイルごとに別になる。
- 共用ブラウザーでは保存内容が他の利用者に見える可能性がある。暗号化保管ではないため機密情報の保存に注意する。
- サイトデータの削除やプライベートブラウズ終了で失われることがある。
- 保存データの破損・未対応バージョン・保存利用不可は通知し、モデル実行は継続できる。

保存領域を初期化する場合は、ブラウザーの開発者ツールで対象オリジンの
`decision-workspace.question-sets.v1` を削除してください。保存した全質問が消去されます。
破損したデータはアプリから自動上書きしません。

## API とエラー

- `POST /api/decision`：入力検証後にモデルを実行。有効形式のみを SDK に変換する。
- `GET /api/config`：入力上限のみを返す。秘密設定は返さない。
- `GET /health`：プロセスの稼働確認。Foundry への接続確認は行わない。
- `/` と `/static/`：画面と静的アセット。API ドキュメントの公開は無効。

入力不備は422、同時実行数超過は429、上流の失敗・不正な回答は502、設定不備・Entra ID の認証失敗は503、
タイムアウトは504を返します。上流の401・403・429を含むエラー本文は利用者に転送しません。
キー・接続先・質問全文をエラーに含めず、入力検証エラーも入力値を返しません。

## コマンドラインで実モデルへの接続確認

[debug/debug_decision.py](debug/debug_decision.py) は、プロジェクトルートの `env.toml` を読み込み、
`exmgai.Client('decision', env=...)` の `decision.system_one()` で Decision-1 に Noul の質問を1回送信します。
アプリ独自の接続処理は使用せず、exmgai 自体の設定読み込み・認証・接続を確認します。
モックではなく実際のモデルを呼び出すため、費用が発生します。

Linux PC で Entra ID 認証を確認する場合は、Azure CLI、Python 3.13 以上、uv、Git を用意し、
プロジェクトルートで次を実行します。ログインとスクリプトの実行は同じ Linux ユーザーで行ってください。

```bash
uv sync --locked --no-dev
test -e env.toml || cp env.toml.example env.toml
az login --tenant '<tenant-id>'
az account set --subscription '<subscription-id>'
```

`env.toml` は前述の Entra ID 認証の例を参考に、`type = "entra_id"`、
`credential = "azure_cli"` と実際の `endpoint`・`deployment` を設定します。API Key は不要です。
ブラウザーを開けない場合は `az login --tenant '<tenant-id>' --use-device-code` を使用します。

トークン取得のみを確認する場合は、トークン自体を表示せず有効期限を確認します。
このコマンドだけではモデルの実行権限は確認できません。

```bash
az account get-access-token \
  --resource https://cognitiveservices.azure.com/ \
  --query expiresOn \
  --output tsv
```

実際のモデルへの接続確認は次のコマンドです。Web サーバーの起動は不要です。
PowerShell でも同じコマンドを使用できます。

```bash
uv run --no-dev python -m debug.debug_decision
```

成功時は `Connection successful.` とモデル名・回答・使用トークン数などの SDK レスポンスの JSON を表示します。
失敗時は元の例外のトレースバックを表示し、終了コードは非ゼロになります。自動再試行は行いません。
スクリプト自体は認証情報を出力しませんが、SDK 等の例外に含まれる情報はマスクしません。
エラーを共有する際は、トークン・キー・接続先などの機密情報が含まれていないか確認してください。

この確認はホストの資格情報を使用します。ホストでは成功してコンテナー内で失敗する場合は、
コンテナー側の設定・実行ユーザー・Azure CLI キャッシュのマウントを別途確認してください。

## 開発・テスト

```powershell
uv sync --locked
uv run python -m playwright install chromium
uv run python -m ruff check app debug tests
uv run python -m pytest
```

自動テストは実際の exmgai プロバイダーにモック HTTP を接続し、課金 API を呼びません。
API Key／Entra ID のヘッダー、SDK 変換、接続の解放、入力検証、エラー、同時実行上限を検証します。
Playwright はテスト専用のローカルサーバーで、PC・モバイル表示、保存・復元・削除、実行中状態などを検証します。
スクリーンショットは Git 管理外の `test-results/` に出力します。
実 Foundry への疎通は、資格情報を設定して画面または前述の接続確認スクリプトから別途確認してください。
実行には費用が発生します。

主要なコードは `app/main.py`（配信・API）、`app/schemas.py`（入力検証）、
`app/decision.py`（SDK 接続）、`app/static/`（画面）、`tests/`（検証）にあります。
アイコンはローカルに同梱した Lucide 0.468.0 を使用しています。
ライセンスは `app/static/vendor/LICENSE.lucide` にあります。