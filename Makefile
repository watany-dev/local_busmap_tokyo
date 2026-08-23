PYTHON ?= python3
ENV = PYTHONPATH=src

.PHONY: help verify config test sample serve-sample ingest ingest-kbus serve export-pages serve-pages postgis-up postgis-load clean

help:
	@echo "verify        リポジトリ前提条件の検証"
	@echo "config        フィード設定の検証"
	@echo "test          自動テスト"
	@echo "sample        合成GTFSのオフライン取り込み"
	@echo "serve-sample  合成データで地図とAPIを起動"
	@echo "ingest        21フィード一括取得（ネットワーク必要）"
	@echo "ingest-kbus   北区KバスF005のみ取得（ネットワーク必要）"
	@echo "serve         実データで地図とAPIを起動"
	@echo "export-pages  GitHub Pages向け静的サイトを site/ に書き出す"
	@echo "serve-pages   静的サイトを http://127.0.0.1:8000 で確認"
	@echo "postgis-up    PostGISコンテナ起動"
	@echo "postgis-load  GeoJSONをPostGISへ投入"
	@echo "clean         取得・正規化データを削除"

verify:
	$(PYTHON) tools/verify_repo.py

config:
	$(ENV) $(PYTHON) -m tokyo_local_bus validate-config

test:
	$(ENV) $(PYTHON) -m unittest discover -s tests -v

sample:
	rm -rf data/sample-run
	$(ENV) $(PYTHON) -m tokyo_local_bus ingest \
	  --config tests/fixtures/test-feeds.json \
	  --data-dir data/sample-run \
	  --date 2026-08-22 \
	  --local-zip TEST=tests/fixtures/minimal_gtfs.zip

serve-sample:
	$(ENV) $(PYTHON) -m tokyo_local_bus serve \
	  --data-dir data/sample-run --web-dir web --host 127.0.0.1 --port 8000

ingest:
	$(ENV) $(PYTHON) -m tokyo_local_bus ingest --allow-partial

ingest-kbus:
	$(ENV) $(PYTHON) -m tokyo_local_bus ingest --feed F005

serve:
	$(ENV) $(PYTHON) -m tokyo_local_bus serve --host 127.0.0.1 --port 8000

export-pages:
	$(PYTHON) tools/export_pages.py --out site

serve-pages: export-pages
	$(PYTHON) -m http.server 8000 --directory site

postgis-up:
	docker compose up -d postgis

postgis-load:
	DATABASE_URL=postgresql://localbus:localbus@localhost:5432/localbus \
	  $(PYTHON) scripts/load_postgis.py

clean:
	rm -rf data/raw/* data/extracted/* data/state/*.json data/normalized/* data/sample-run site
