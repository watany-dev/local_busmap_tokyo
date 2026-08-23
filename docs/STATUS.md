# 現況 — 2026-08-23

引き継ぎパッケージ `tokyo-local-bus-handoff_2026-08-23` を、このリポジトリへ展開・整備した時点の記録です。
引き継ぎ元の判断・設計はすべて維持しています（[`HANDOFF.md`](HANDOFF.md)）。

## 1. リポジトリ化で行った変更

引き継ぎパッケージは「ZIPを展開して読む」前提の入れ子構造でした。リポジトリとして運用するため、
機能を変えずに次を整理しています。

| 変更 | 内容 |
|---|---|
| レイアウト | `project/tokyo-local-bus-starter/` の中身をリポジトリ直下へ移動 |
| `tools/*.sh` / `bootstrap.ps1` | プロジェクトディレクトリの解決先をリポジトリルートへ変更 |
| `tools/verify_handoff.py` | `tools/verify_repo.py` へ置換。ZIP同梱物のチェックサム照合をやめ、実行環境・`config/feeds.json`・台帳xlsx・フィクスチャの検証に変更（ファイル完全性はGitが担保するため） |
| `tools/smoke_api.py` | 新規。サーバーを一時ポートに載せてAPIと地図配信を検証。CIから実行 |
| `.github/workflows/ci.yml` | 新規。Python 3.11 / 3.12 でテストとオフラインE2Eを実行 |
| `.github/workflows/update-gtfs.yml` | 前提条件検証とAPIスモークを追加。サービス日を `date -u` からJSTへ修正（00:15 UTC実行のためUTC日付はJSTの前日になっていた） |
| `Makefile` | `verify` / `serve-sample` / `ingest-kbus` / `help` を追加 |
| `docs/snapshot/` | `BUILD_INFO.json`・`MANIFEST.sha256.json`・`RUN_RESULTS.md` を履歴として退避（2026-08-22時点の記録。以後更新しない） |
| `README.md` | リポジトリ運用手順へ書き換え |

`src/tokyo_local_bus/` のロジック、`config/feeds.json`、`web/`、`sql/`、`scripts/`、`tests/` は無変更です。

## 2. この環境で検証できたこと

| 項目 | 結果 |
|---|---|
| Python | 3.11.15（要件 3.11以上） |
| `tools/verify_repo.py` | `status: ok`, `feed_count: 21` |
| `validate-config` | `{"status":"ok","feed_count":21}` |
| 自動テスト | 5件成功 |
| 合成GTFSのE2E取り込み | 成功。停留所3件、路線形状1件 |
| `GET /api/health` | HTTP 200, `feed_count=1` |
| `GET /api/feeds` / `GET /api/routes` | HTTP 200、路線1件 |
| `GET /api/stops/nearby` | HTTP 200、距離昇順3件 |
| `GET /` | HTTP 200（地図HTML配信） |

再現コマンド:

```bash
./tools/bootstrap.sh
python tools/smoke_api.py --data-dir data/sample-run
```

## 3. 実GTFSのライブ取得

2026-08-23 時点で 21フィードすべて取得に成功しました（`data/state/latest-run.json`: 21 ok / 0 failed）。
GitHub Pages は `data/normalized/all/` の集約GeoJSON（停留所 1624、路線形状 176）を静的配信します。

## 4. 受入確認チェックリスト

引き継ぎメモ §16 に対する現時点の状態です。

- [x] リポジトリ前提条件の検証が成功する（`tools/verify_repo.py`）
- [x] Pythonが3.11以上である
- [x] `validate-config` が21件を返す
- [x] 自動テスト5件が成功する
- [x] 合成GTFSから停留所3件、路線形状1件が生成される
- [x] `/api/health` がHTTP 200を返す
- [x] `/api/stops/nearby` が距離順で返る
- [x] サンプル地図が配信される（HTTP 200。ブラウザ描画は外部CDN到達が必要）
- [x] KバスF005の実取得が成功する（61停留所、路線形状6）
- [x] Kバスの `feed_end_date` が現在日を含む（〜2026-12-31）
- [x] 21フィード一括実行の失敗一覧を保存する（0件失敗、`data/state/latest-run.json`）
- [ ] 本番へ移す前にタイル配信とPostGIS資格情報を変更する — 本番化時の作業

## 5. 次に実施する作業

1. GitHub Pages のデプロイ成功を確認する（<https://watany-dev.github.io/local_busmap_tokyo/>）
2. 成功フィードの停留所数・路線数・bbox・指定日運行便数を `inventory/` の台帳へ戻す
3. 現在地から800m検索のUXをKバスで確定する
4. PostGISへ移し、APIを `ST_DWithin` 化する（現在は全停留所のHaversine走査）
5. 杉並区グリーンスローモビリティ（F025）でGTFS-RTを試験実装する
6. 本番用タイル、HTTPS、監視、更新失敗通知を整える
7. GTFS未公開サービス向けに自治体ページ監視と手動データ入力方針を作る

## 6. 既知の制約

引き継ぎメモ §14 から変更のないものに加え、リポジトリ化で見えた項目を記載します。

1. **ライブ取得は完了** — 上記 §3。日次の `update-gtfs.yml` で継続更新する。
2. **フィードURLの変更** — `date=current` は配布側実装に依存。状態ファイルの最終解決URLは恒久URLではありません。
3. **フィード有効期限と実運行のずれ** — `feed_end_date` が未来でも路線再編が未反映の場合があります。
4. **地図の外部依存** — MapLibre GL JS 5.6.1 を unpkg.com から、背景地図を OpenStreetMap 標準タイルから読み込みます。
   本番ではMapLibreを自前バンドルし、利用規約と負荷要件を満たすタイル事業者へ変更してください。
5. **出典表示** — 地図フッターはカタログの各フィード名とライセンスを表示します。CC BY 4.0 の要件を満たすため、実データ公開前に表記内容を確認してください。
6. **GitHub Pages** — Source は GitHub Actions。公開先は
   <https://watany-dev.github.io/local_busmap_tokyo/>。Python API も WASM も使いません。
   初回デプロイは Pages 未有効化で `configure-pages` が 404 になり失敗しました。有効化後は
   `pages.yml` の `enablement: true` で再デプロイします。環境 `github-pages` は `main` のみ許可。
7. **API性能** — 近傍検索は全停留所を毎回走査します。MVP規模では動きますが、空間インデックスかPostGISが必要です。
8. **リアルタイム未実装** — VehiclePosition / TripUpdate / Alert は未統合です。
9. **依存ロック** — コア依存はゼロ。PostGIS用 `psycopg` は範囲指定でありロックファイルではありません。
10. **日次更新の書き込み権限** — `update-gtfs.yml` は `contents: write` でデフォルトブランチへ直接pushします。
   ブランチ保護が有効な場合は失敗します。その場合はPR作成型へ変更してください。
11. **合成データ** — `data/sample-run` はテスト専用です。停留所名に「テスト」が入ります。
