# 東京ローカルバス現在地マップ — データ基盤

東京都内の**都営バスを除く**自治体・地域交通（コミュニティバス等）の静的GTFSを取得・検証し、
GeoJSONへ正規化して「現在地から近い停留所」を地図で探せるようにするMVPです。

公開地図: <https://watany-dev.github.io/local_busmap_tokyo/>

調査台帳で優先度Aとした静的GTFS **21フィード**を `config/feeds.json` に設定済みです。

- 引き継ぎ元メモ: [`docs/HANDOFF.md`](docs/HANDOFF.md)
- 現在の到達点と未完了項目: [`docs/STATUS.md`](docs/STATUS.md)
- 実行時のソース・オブ・トゥルース: `config/feeds.json`（Excel台帳は調査・判断用）

コア処理は **Python 3.11以上の標準ライブラリのみ**で動作します。`pyproject.toml` の通常依存は空です。

## クイックスタート

```bash
git clone <this-repo>
cd local_busmap_tokyo
./tools/bootstrap.sh          # Windowsは tools\bootstrap.ps1
```

`bootstrap.sh` は次を順に実行します。

1. Python 3.11以上の確認
2. `.venv` の作成
3. `tools/verify_repo.py`（設定・台帳・フィクスチャの検証）
4. `validate-config`（フィード21件）
5. 自動テスト5件
6. 同梱の合成GTFSによるオフラインE2E取り込み

続けて合成データの地図を起動できます。

```bash
./tools/start_sample_map.sh   # http://127.0.0.1:8000
```

ネットワーク取得を伴わないため、この時点までは配布元へ接続できない環境でも完走します。

## 手動で操作する

リポジトリ直下で `PYTHONPATH` を通します。`make` を使う場合は不要です。

```bash
export PYTHONPATH="$PWD/src"
```

| 目的 | make | 直接実行 |
|---|---|---|
| 前提条件の検証 | `make verify` | `python tools/verify_repo.py` |
| フィード設定の検証 | `make config` | `python -m tokyo_local_bus validate-config` |
| 自動テスト | `make test` | `python -m unittest discover -s tests -v` |
| 合成GTFS取り込み | `make sample` | 下記参照 |
| 合成データで地図起動 | `make serve-sample` | 下記参照 |
| GitHub Pages用に静的書き出し | `make export-pages` | `python tools/export_pages.py --out site` |
| 静的サイトを確認 | `make serve-pages` | `python -m http.server 8000 --directory site` |
| Kバスのみ取得 | `make ingest-kbus` | `python -m tokyo_local_bus ingest --feed F005` |
| 21フィード一括取得 | `make ingest` | `python -m tokyo_local_bus ingest --allow-partial` |
| 実データで地図起動 | `make serve` | `python -m tokyo_local_bus serve` |

`validate-config` の期待値:

```json
{"status": "ok", "feed_count": 21}
```

### 合成GTFSによるオフライン検証

```bash
rm -rf data/sample-run
python -m tokyo_local_bus ingest \
  --config tests/fixtures/test-feeds.json \
  --data-dir data/sample-run \
  --date 2026-08-22 \
  --local-zip TEST=tests/fixtures/minimal_gtfs.zip

python tools/smoke_api.py --data-dir data/sample-run
```

`smoke_api.py` はサーバーを一時ポートに載せて `/api/health`・`/api/feeds`・`/api/routes`・
`/api/stops/nearby`（距離昇順であること）・`/` を確認します。CIでも同じチェックを実行します。

合成データの停留所名には「テスト」を付けています。実運行データとして扱わないでください。

## 実データの取り込み

配布元（`api-public.odpt.org`・`api.gtfs-data.jp`・`www.arcgis.com`・`www.city.itabashi.tokyo.jp`）への
HTTPS接続が必要です。

```bash
# まずKバス1件で確認する
python -m tokyo_local_bus ingest --feed F005 --date "$(date +%F)"

# 21フィード一括。一部失敗しても成功分を集約する
python -m tokyo_local_bus ingest --date "$(date +%F)" --allow-partial
```

タイムアウトする場合は `--timeout 90 --retries 5` を付けます。

手元に取得済みのZIPがある場合はネットワーク取得を回避できます。

```bash
python -m tokyo_local_bus ingest \
  --feed F005 \
  --local-zip F005=/absolute/path/to/KitaAllLines.zip \
  --date "$(date +%F)"
```

### 終了コード

| コード | 意味 |
|---:|---|
| 0 | 全件成功、または `--allow-partial` 指定で1件以上成功 |
| 1 | 一部失敗かつ `--allow-partial` なし |
| 2 | 全件失敗、設定不正、引数不正 |

失敗の一次調査先は `data/state/latest-run.json` です。エラーのあるフィードは集約GeoJSONに混ざりません。

## 地図とAPI

```bash
python -m tokyo_local_bus serve --host 127.0.0.1 --port 8000
```

| エンドポイント | 内容 |
|---|---|
| `GET /api/health` | 稼働確認とフィード数 |
| `GET /api/feeds` | 取り込み済みフィードのカタログ |
| `GET /api/routes` | 路線LineStringのFeatureCollection |
| `GET /api/stops/nearby?lat=&lon=&radius=&limit=` | 現在地から半径内の停留所を距離昇順で返す（ローカルAPI） |

近傍検索は半径10〜20,000m、件数1〜500件にクランプされます。サーバーAPIはPythonのHaversine距離で
全停留所を走査するMVP実装です。GitHub Pages向けの地図は同じ計算をブラウザのJavaScriptで行います。
ブラウザの位置情報は `localhost` 以外ではHTTPSが必要です。

## GitHub Pages で公開する

GitHub Pages は **静的ファイルだけ** を配信できます。Python サーバーも WASM も不要です。

- 地図は従来どおり MapLibre GL JS（ブラウザ）
- 停留所・路線は正規化済み GeoJSON を同じサイトから読む
- 「現在地から探す」は読み込み済み停留所への Haversine 計算（`web/app.js`）
- WASM / Pyodide は、21フィード規模の距離計算には過剰で読み込みも重いため使いません

公開 URL: <https://watany-dev.github.io/local_busmap_tokyo/>

Settings → Pages の Source は **GitHub Actions** です。`main` への push、または Actions の `Deploy GitHub Pages` 手動実行でデプロイします。`github-pages` 環境は `main` からのデプロイのみ許可しています。

`.github/workflows/pages.yml` は `web/` と `data/normalized/all/` を `site/` に組み立ててデプロイします。
カタログが空のときは、デプロイ前に GTFS 取得を1回試みます。取得に失敗した場合は空の地図を出さず、ジョブを失敗させます。
日次の `update-gtfs.yml` が GeoJSON をコミットすると、Pages ワークフローが再デプロイします。

手元で静的サイトだけ確認する場合:

```bash
make export-pages
make serve-pages          # http://127.0.0.1:8000
```

プロジェクトサイト（`/local_busmap_tokyo/`）でも動くよう、HTML/JS の参照はルート絶対パスではなく相対パスです。
GitHub Pages は HTTPS のため、ブラウザの位置情報も使えます。

CC BY 4.0 フィードの出典は地図フッターにカタログから表示します。GTFS の ZIP 本体は公開しません。

## PostGIS（任意）

```bash
docker compose up -d postgis
python -m pip install -r requirements-postgis.txt
DATABASE_URL=postgresql://localbus:localbus@localhost:5432/localbus \
  python scripts/load_postgis.py
```

`localbus/localbus` はローカル開発専用の資格情報です。本番へ持ち込まないでください。

## ディレクトリ

```text
config/                            21フィード設定と外部照合記録
src/tokyo_local_bus/               取得・検証・正規化・API
web/                               MapLibre GL JSの現在地マップ
tests/                             合成GTFSと自動テスト
tools/                             セットアップ・検証・起動スクリプト
inventory/                         調査台帳（xlsx）
docs/                              引き継ぎメモと現況
docs/snapshot/                     2026-08-22時点のビルド記録（履歴・更新しない）
sql/schema.sql                     PostGISスキーマ
scripts/load_postgis.py            GeoJSONからPostGISへの投入
data/                              実行時データ（raw / extracted / state / normalized）
.github/workflows/ci.yml           テストとオフラインE2E
.github/workflows/update-gtfs.yml  日次GTFS更新（09:15 JST）
.github/workflows/pages.yml        GitHub Pagesへ静的サイトをデプロイ
```

## データ処理の設計判断

- **ID名前空間**: 外部GTFSのID衝突を避けるため、正規化後は `feed_id:source_id` 形式（例 `F005:stop_123`）。
  この不変条件は崩さないでください。既存のFeed IDを別サービスへ再利用しないでください。
- **不正フィードの隔離**: 必須ファイル欠落、主キー重複、参照切れ、異常座標、異常時刻、有効期限切れはエラー。
  エラーのあるフィードは全体GeoJSONへ混ぜません。`shapes.txt` 欠落と指定日に運行便がない状態は警告です。
- **shapes補完**: `shapes.txt` がない場合は代表便の `stop_times.txt` と停留所座標からLineStringを補完します。
  停留所間の直線列であり道路中心線ではありません。走行距離や道路追従の用途には使わないでください。
- **静的GTFSとGTFS-RT の分離**: 現行の取り込みは静的GTFSのみです。`config/feeds.json` には杉並区
  グリーンスローモビリティのVehiclePosition URLがありますが、protobufの取得・デコードは未実装です。
- **ExcelとJSONの役割分担**: Excelは調査履歴・比較・優先度、`config/feeds.json` は実行対象、
  `data/state` は取得結果、`data/normalized` はアプリへ渡すGeoJSON。

## ライセンスと出典

各フィードのライセンスは `config/feeds.json` の `license`（CC BY 4.0 / CC0 1.0）に記載しています。
CC BY 4.0 のフィードは地図表示時に出典表示が必要です。本リポジトリはGTFSのZIP本体を再配布しません。
