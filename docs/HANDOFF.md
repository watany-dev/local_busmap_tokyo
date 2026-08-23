> **注記**: 本書は 2026-08-23 のハンドオフパッケージ同梱版をそのまま保存したものです。本文中の `project/tokyo-local-bus-starter/` はこのリポジトリのルートに、`tools/`・`inventory/` はそのまま同名ディレクトリに対応します。現在のリポジトリ手順は [README.md](../README.md)、環境ごとの検証状況は [STATUS.md](STATUS.md) を参照してください。

# 東京ローカルバス現在地マップ — 環境引き継ぎメモ

- 引き継ぎスナップショット: **2026-08-23（JST）**
- 元成果物の基準日: **2026-08-22**
- プロジェクト名: `tokyo-local-bus`
- プロジェクト版: `0.1.0`
- 対象: 東京都内の**都営バスを除く**自治体・地域交通
- MVP設定済み静的GTFS: **21フィード**
- 外部取得記録で照合済み: **8フィード**
- 実GTFS ZIP本体: **同梱なし**

このファイルだけで、目的、現在地、再開手順、設計判断、既知の制約を追跡できるようにしています。最初に `tools/verify_handoff.py`、次にOS別のブートストラップを実行してください。

## 1. 現在の到達点

完了しているもの:

- 東京都内ローカルバス・地域交通の調査台帳
- 74サービス、2023年基準194路線・運行エリア行の整理
- MVP優先度Aの静的GTFS 21フィードの実行設定
- GTFSの取得、再試行、HTTPリダイレクト、ETag、Last-Modified、SHA-256記録
- ZIP CRC検査、パストラバーサル防止、展開容量制限
- GTFS必須ファイル、主キー、外部キー、座標、時刻、有効期間の検証
- 停留所Point、路線LineStringのGeoJSON化
- `shapes.txt`欠落時の代表便停留所列による補完
- 全フィードの集約GeoJSONとカタログ生成
- 現在地から指定半径内の停留所を返すHTTP API
- MapLibre GL JSの地図プレビュー
- PostGISスキーマとGeoJSON投入スクリプト
- GitHub Actionsの日次更新ジョブ
- 合成GTFSによる自動テスト5件

未完了または本番化前のもの:

- 21フィードすべての実ネットワーク取得と失敗URLの解消
- GTFS-RTのデコード、車両位置・遅延の地図統合
- APIのPostGIS接続。本体APIは現在、GeoJSON全件をメモリ走査するMVP実装
- 本番用タイル配信、CDN、監視、認証、レート制御
- 自治体公式ページの変更検知とフィードURL自動差し替え
- デマンド交通を固定路線GTFSと同じUIに載せるためのデータモデル

**再開地点は、Kバス `F005` の実取り込みを最初に成功させ、次に21フィード一括実行の `data/state/latest-run.json` から失敗を潰す段階です。**

## 2. パッケージ構成

```text
tokyo-local-bus-handoff_2026-08-23/
├── HANDOFF.md                         この引き継ぎメモ
├── MANIFEST.json                      スナップショットの機械可読情報
├── SHA256SUMS.txt                     同梱ファイルの整合性確認
├── project/
│   └── tokyo-local-bus-starter/       展開済み・そのまま実行できるプロジェクト
├── inventory/
│   ├── tokyo_local_bus_inventory_2026-08-22.xlsx
│   └── tokyo_local_bus_inventory_2026-08-22_next_phase.xlsx
├── source-archives/
│   └── tokyo-local-bus-starter_2026-08-22.zip
├── previews/                           台帳の参考画像
└── tools/
    ├── bootstrap.sh                    macOS/Linux/WSL2用セットアップ・検証
    ├── bootstrap.ps1                   Windows PowerShell用セットアップ・検証
    ├── start_sample_map.sh             合成データ地図の起動
    ├── run_live_kbus.sh                Kバス実取得の開始
    └── verify_handoff.py               チェックサム・設定・XLSX構造検証
```

`source-archives/`は元の成果物を変更せず保存するための領域です。開発は `project/tokyo-local-bus-starter/` を使用します。

## 3. 必要環境

### 必須

| 項目 | 条件 | 用途 |
|---|---|---|
| Python | 3.11以上。基準環境は3.12 | 取得、検証、GeoJSON、API |
| ブラウザ | WebGLとGeolocation対応 | MapLibre地図、現在地 |
| ネットワーク | HTTPSでGTFS配布元へ接続可能 | 実フィード取得 |
| 空きポート | TCP 8000 | 地図とAPI |

コア処理はPython標準ライブラリだけで動きます。`pyproject.toml`の通常依存は空です。

### 任意

| 項目 | 条件 | 用途 |
|---|---|---|
| Docker + Compose | 現行安定版 | PostGIS起動 |
| PostgreSQL/PostGIS | ComposeではPostgreSQL 16 / PostGIS 3.4 | 空間検索 |
| `psycopg[binary]` | `requirements-postgis.txt` | GeoJSON投入 |
| Git | GitHub Actions・差分管理 | 日次更新と共同開発 |
| GNU Make | macOS/Linux/WSL2 | 短縮コマンド |

WindowsネイティブではPowerShell手順を使えます。開発の再現性はWSL2の方が高いです。

## 4. 最短の引き継ぎ手順

### 4.1 パッケージ整合性を確認

```bash
cd tokyo-local-bus-handoff_2026-08-23
python3 tools/verify_handoff.py
```

正常時は `status: ok`、`feed_count: 21` が出ます。

### 4.2 macOS / Linux / WSL2

```bash
chmod +x tools/*.sh tools/verify_handoff.py
./tools/bootstrap.sh
```

この処理は次を行います。

1. Python 3.11以上を確認
2. `project/tokyo-local-bus-starter/.venv`を作成
3. フィード設定21件を検証
4. 自動テスト5件を実行
5. 同梱の合成GTFSを取り込み、オフラインでE2E検証

サンプル地図を起動:

```bash
./tools/start_sample_map.sh
```

ブラウザ:

```text
http://127.0.0.1:8000
```

### 4.3 Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tools\bootstrap.ps1
```

起動コマンドはスクリプト終了時に表示されます。

## 5. 開発プロジェクトを直接操作する場合

```bash
cd project/tokyo-local-bus-starter
export PYTHONPATH="$PWD/src"
```

設定確認:

```bash
python -m tokyo_local_bus validate-config
```

期待値:

```json
{"status":"ok","feed_count":21}
```

自動テスト:

```bash
python -m unittest discover -s tests -v
```

合成データ取り込み:

```bash
rm -rf data/sample-run
python -m tokyo_local_bus ingest \
  --config tests/fixtures/test-feeds.json \
  --data-dir data/sample-run \
  --date 2026-08-22 \
  --local-zip TEST=tests/fixtures/minimal_gtfs.zip
```

## 6. 実データ取り込み

### 6.1 Kバスだけ取得

```bash
./tools/run_live_kbus.sh
```

サービス日を明示する場合:

```bash
SERVICE_DATE=2026-08-23 ./tools/run_live_kbus.sh
```

プロジェクト直下から実行する場合:

```bash
python -m tokyo_local_bus ingest --feed F005 --date 2026-08-23
```

成功時の主要出力:

```text
data/raw/F005/feed.zip
data/extracted/F005/*.txt
data/state/F005.download.json
data/normalized/kita-kbus/validation.json
data/normalized/kita-kbus/stops.geojson
data/normalized/kita-kbus/routes.geojson
data/normalized/all/stops.geojson
data/normalized/all/routes.geojson
data/normalized/all/catalog.json
data/state/latest-run.json
```

### 6.2 21フィード一括取得

```bash
python -m tokyo_local_bus ingest \
  --date 2026-08-23 \
  --allow-partial
```

`--allow-partial`は、一部配布元が失敗しても1件以上成功すれば終了コード0とし、成功分の集約データを生成します。

終了コード:

- `0`: 全件成功、または`--allow-partial`指定で1件以上成功
- `1`: 一部成功・一部失敗で`--allow-partial`なし
- `2`: 全件失敗、設定不正、引数不正など

失敗の一次調査先:

```text
data/state/latest-run.json
```

### 6.3 手元のGTFS ZIPを使用

配布元から手動取得したZIPを使い、ネットワーク取得を回避できます。

```bash
python -m tokyo_local_bus ingest \
  --feed F005 \
  --local-zip F005=/absolute/path/to/KitaAllLines.zip \
  --date 2026-08-23
```

## 7. 地図とAPI

実データ取り込み後:

```bash
python -m tokyo_local_bus serve \
  --host 127.0.0.1 \
  --port 8000
```

API:

```text
GET /api/health
GET /api/feeds
GET /api/routes
GET /api/stops/nearby?lat=35.7521&lon=139.7386&radius=800&limit=50
```

近傍検索の制約:

- 半径: 10mから20,000m
- 件数: 1から500件
- 現在はPythonのHaversine距離を使用
- 大規模化時はPostGISの`ST_DWithin`へ移行

ブラウザ位置情報は、`localhost`以外の配信ではHTTPSが必要です。

## 8. PostGIS

起動:

```bash
docker compose up -d postgis
```

クライアント依存を追加:

```bash
python -m pip install -r requirements-postgis.txt
```

投入:

```bash
DATABASE_URL=postgresql://localbus:localbus@localhost:5432/localbus \
  python scripts/load_postgis.py
```

`localbus/localbus`はローカル開発用の固定資格情報です。本番環境では使用しないでください。

## 9. 日次更新

`.github/workflows/update-gtfs.yml`は毎日 **09:15 JST** に実行する設定です。

処理:

1. Python 3.12を準備
2. 21フィード設定を検証
3. GTFS取得・検証・正規化
4. 自動テスト
5. `latest-run.json`とGeoJSONを30日保持のArtifactへ保存
6. `data/state`と`data/normalized`に差分があればコミット・push

注意点:

- Workflowは`contents: write`を要求します。
- デフォルトブランチ保護が厳しい場合、直接pushは失敗します。その場合はPR作成型へ変更してください。
- `--allow-partial`により一部失敗でもジョブが継続します。失敗件数を別途監視してください。

## 10. ランタイム用フィードカタログ

Excel台帳は調査・判断用です。アプリの実行時ソース・オブ・トゥルースは `config/feeds.json` です。

| Feed ID | 自治体 | サービス | slug | 配布系統 | ライセンス | RTメタデータ |
|---|---|---|---|---|---|---|
| F020 | 三宅村 | 村営バス | `miyake-village-bus` | ODPT | CC BY 4.0 | なし |
| F005 | 北区 | Kバス | `kita-kbus` | ODPT | CC BY 4.0 | なし |
| F021 | 千代田区 | 風ぐるま | `chiyoda-kazaguruma` | ODPT | CC BY 4.0 | なし |
| F022 | 台東区 | めぐりん | `taito-megurin` | ODPT | CC BY 4.0 | なし |
| F010 | 国分寺市 | ぶんバス | `kokubunji-bunbus` | ODPT | CC BY 4.0 | なし |
| F012 | 国立市 | あおやぎっこ | `kunitachi-aoyagikko` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F011 | 国立市 | くにっこ | `kunitachi-kunikko` | GTFSデータリポジトリ | CC0 1.0 | なし |
| F023 | 小笠原村 | 村営バス | `ogasawara-village-bus` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F003 | 文京区 | Bーぐる | `bunkyo-b-guru` | ODPT | CC BY 4.0 | なし |
| F025 | 杉並区 | グリーンスローモビリティ | `suginami-green-slow-mobility` | ODPT | CC BY 4.0 | 設定あり |
| F026 | 東大和市 | ちょこバス | `higashiyamato-chokobus` | ODPT | CC0 1.0 | なし |
| F015 | 東村山市 | グリーンバス | `higashimurayama-green-bus` | ODPT | CC BY 4.0 | なし |
| F008 | 板橋区 | りんりんGO | `itabashi-rinringo` | 自治体直配布 | CC BY 4.0 | なし |
| F013 | 清瀬市 | きよバス | `kiyose-kiyobus` | ODPT | CC BY 4.0 | なし |
| F001 | 渋谷区 | ハチ公バス | `shibuya-hachiko-bus` | ArcGIS | CC BY 4.0 | なし |
| F018 | 瑞穂町 | コミュニティバス | `mizuho-community-bus` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F016 | 町田市 | 市民バス・コミュニティバス | `machida-community-bus` | ODPT | CC0 1.0 | なし |
| F028 | 神津島村 | 村営バス | `kozushima-village-bus` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F014 | 立川市 | くるりん | `tachikawa-kururin` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F029 | 荒川区 | コミュニティバスさくら | `arakawa-sakura` | GTFSデータリポジトリ | CC BY 4.0 | なし |
| F030 | 西東京市 | はなバス | `nishitokyo-hanabus` | ODPT | CC BY 4.0 | なし |

フィードIDはデータの名前空間に使用されます。既存IDを別サービスへ再利用しないでください。

## 11. 外部照合済みフィード

2026年8月22日の公開取得記録と照合済みの8件です。実ZIP本体をこのパッケージ内で再配布しているわけではありません。

| Feed ID | サービス | 照合時の終了日 | shapes.txt |
|---|---|---:|---:|
| F020 | 三宅村 村営バス | 2026-12-31 | なし |
| F005 | 北区 Kバス | 2026-12-31 | あり |
| F021 | 千代田区 風ぐるま | 2027-12-31 | あり |
| F022 | 台東区 めぐりん | 2026-12-31 | あり |
| F003 | 文京区 Bーぐる | 2027-12-31 | あり |
| F025 | 杉並区 グリーンスローモビリティ | 2028-06-30 | あり |
| F008 | 板橋区 りんりんGO | 2028-03-31 | あり |
| F001 | 渋谷区 ハチ公バス | 2030-03-31 | なし |

詳細:

```text
config/external_verification_2026-08-22.json
config/external_verification_2026-08-22.csv
```

F020とF001は`shapes.txt`がないため、代表便の停留所列による形状補完対象です。

## 12. データ処理の設計判断

### ID名前空間

外部GTFSのID衝突を避けるため、正規化後は次の形式です。

```text
feed_id:source_id
```

例:

```text
F005:stop_123
```

### 不正フィードの隔離

必須ファイル欠落、主キー重複、参照切れ、異常座標、異常時刻、有効期限切れはエラーです。エラーのあるフィードは全体GeoJSONへ混ぜません。

### shapes欠落

`shapes.txt`がない場合は、代表便の`stop_times.txt`と停留所座標からLineStringを補完します。これは道路中心線に沿う形状ではなく、停留所間の直線列です。表示には使えますが、正確な走行距離や道路追従には使わないでください。

### 静的GTFSとGTFS-RT

現在の取り込み処理は静的GTFSのみです。`config/feeds.json`には杉並区グリーンスローモビリティのVehiclePosition URLがありますが、現行コードはまだprotobufを取得・デコードしません。

### ExcelとJSONの役割分担

- Excel: 調査履歴、比較、ソース、優先度、変更管理
- `config/feeds.json`: 実行対象、ID、URL、ライセンス、RTメタデータ
- `data/state`: 取得結果と実行履歴
- `data/normalized`: アプリに渡すGeoJSON

## 13. 調査台帳

最新版:

```text
inventory/tokyo_local_bus_inventory_2026-08-22_next_phase.xlsx
```

シート:

1. `調査概要`
2. `サービス一覧`
3. `路線一覧_2023`
4. `GTFSカタログ`
5. `事業者包括GTFS`
6. `変更・要確認`
7. `自治体サイト`
8. `実装設計`
9. `MVP優先順位`
10. `取得検証_20260822`
11. `成果物一覧`

旧版も比較用として同梱しています。通常は`next_phase`版を参照してください。

## 14. 既知の制約とリスク

1. **全21フィードのライブ取得未完了**
   - この成果物作成環境では配布サーバーへの直接通信ができませんでした。
   - 新環境で最初に一括実行し、URL・TLS・リダイレクト・配布終了を確認してください。

2. **フィードURLの変更**
   - `date=current`は配布側の実装に依存します。
   - 状態ファイルに最終解決URLを残しますが、恒久URLとは限りません。

3. **フィード有効期限と実運行のずれ**
   - `feed_end_date`が未来でも、自治体の路線再編が未反映の場合があります。
   - 公式路線ページと`routes.txt`の照合を継続してください。

4. **地図外部依存**
   - MapLibre GL JS 5.6.1を`unpkg.com`から読み込みます。
   - 背景地図はOpenStreetMap標準タイルです。
   - 本番ではMapLibreを自前バンドルし、利用規約と負荷要件を満たすタイル事業者へ変更してください。

5. **API性能**
   - 近傍検索は全停留所を毎回走査します。
   - 21フィード程度のMVPでは動きますが、都内全交通・高トラフィックではPostGISか空間インデックスが必要です。

6. **リアルタイム未実装**
   - 車両位置、TripUpdate、Alertは未統合です。
   - 静的GTFSの`trip_id`とRTの`trip_id`対応を確認してから追加してください。

7. **依存ロック**
   - コア依存はゼロです。
   - PostGIS用`psycopg`は範囲指定であり、完全なロックファイルではありません。

8. **セキュリティ**
   - 同梱物にAPIキーやトークンはありません。
   - GitHub Actionsの書き込み権限とPostGISの開発用パスワードを本番へ持ち込まないでください。

9. **合成データ**
   - `data/sample-run`はテスト専用です。
   - 停留所名に「テスト」があり、実運行として扱わないでください。

## 15. 次に実施する作業

優先順:

1. `tools/verify_handoff.py`と`bootstrap`を新環境で成功させる
2. KバスF005をライブ取得し、`validation.json`と地図を確認する
3. 21フィードを`--allow-partial`で一括取得する
4. `latest-run.json`の失敗を、URL変更・期限切れ・配布停止・GTFS不正に分類する
5. 成功フィードの停留所数、路線数、bbox、指定日運行便数を台帳へ戻す
6. 現在地から800m検索のUXをKバスで確定する
7. PostGISへ移し、APIを`ST_DWithin`化する
8. 杉並区グリーンスローモビリティでGTFS-RTを試験実装する
9. 本番用タイル、HTTPS、監視、更新失敗通知を整える
10. GTFS未公開サービス向けに自治体ページ監視と手動データ入力方針を作る

## 16. 受入確認チェックリスト

- [ ] `python tools/verify_handoff.py`が成功する
- [ ] Pythonが3.11以上である
- [ ] `validate-config`が21件を返す
- [ ] 自動テスト5件が成功する
- [ ] 合成GTFSから停留所3件、路線形状1件が生成される
- [ ] `/api/health`がHTTP 200を返す
- [ ] `/api/stops/nearby`が距離順で返る
- [ ] サンプル地図がブラウザで表示される
- [ ] KバスF005の実取得が成功する
- [ ] Kバスの`feed_end_date`が現在日を含む
- [ ] 21フィード一括実行の失敗一覧を保存する
- [ ] 本番へ移す前にタイル配信とPostGIS資格情報を変更する

## 17. トラブルシュート

### `No module named tokyo_local_bus`

プロジェクト直下で`PYTHONPATH`を設定します。

```bash
export PYTHONPATH="$PWD/src"
```

または`tools/bootstrap.sh`が作成した`.venv`を使います。

### GTFS取得がタイムアウトする

```bash
python -m tokyo_local_bus ingest \
  --feed F005 \
  --timeout 90 \
  --retries 5 \
  --date 2026-08-23
```

### 一部フィードだけ失敗する

`--allow-partial`を付け、`data/state/latest-run.json`を確認します。失敗フィードは集約GeoJSONに入りません。

### 地図は開くが現在地が取れない

- ブラウザの位置情報許可を確認
- `127.0.0.1`または`localhost`で開く
- リモート配信ではHTTPSを使用

### 地図が白い

- `unpkg.com`と`tile.openstreetmap.org`への接続を確認
- ブラウザ開発者ツールのNetwork/Consoleを確認
- 本番では外部CDN依存を廃止

### PostGISへ接続できない

```bash
docker compose ps
docker compose logs postgis
```

既に5432番ポートが使われている場合は`docker-compose.yml`のホスト側ポートを変更してください。

## 18. ファイル整合性

パッケージ内の全主要ファイルは`SHA256SUMS.txt`で確認できます。

```bash
python tools/verify_handoff.py
```

ZIP全体のSHA-256は、ダウンロードファイルと同じ場所にある次のファイルで確認します。

```text
tokyo-local-bus-handoff_2026-08-23.zip.sha256
```

## 19. 引き継ぎ時の判断事項

- 対象範囲は都営バスを除外する。
- 調査台帳は広く、MVP取り込みは静的GTFS公開済みの固定路線から始める。
- 最初の実装・UX検証対象は北区KバスF005。
- フィード間ID衝突を防ぐため`feed_id:source_id`を不変条件とする。
- 不正・期限切れフィードを集約データへ混ぜない。
- `shapes.txt`補完形状を高精度な道路形状として扱わない。
- 静的GTFSとGTFS-RTの更新・障害処理を分離する。
- Excelは調査管理、JSONはランタイム設定として役割を分ける。
