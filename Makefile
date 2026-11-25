# BoxOfficeBozo task runner. CI runs these same targets.
# Windows: install GNU make (e.g. `winget install ezwinports.make`) or run the commands by hand.

UV  ?= uv
NPM ?= npm
ETL  = $(UV) --directory etl run

.DEFAULT_GOAL := help
.PHONY: help setup etl fetch-status check test test-py test-site site-dev site-build sample-data pull-data guard clean

help:
	@echo "make setup       install Python (uv) and Node (npm ci) dependencies from the lockfiles"
	@echo "make etl         build Parquet into site/public/data (offline unless BOFFO_FETCH=1; CI sets it)"
	@echo "make fetch-status after make etl: is anything left that another CI pass could fetch?"
	@echo "make check       data-quality report: manual CSV sources + built tables"
	@echo "make test        pytest + vitest"
	@echo "make site-dev    Vite dev server"
	@echo "make site-build  production build into site/dist, plus a page file for every route"
	@echo "make sample-data fictional sample tables in site/public/data, for working on the site"
	@echo "make pull-data   copy the published tables from the live site into site/public/data"
	@echo "make guard       fail if built or scraped data is tracked by git"

setup:
	$(UV) --directory etl sync --locked
	cd site && $(NPM) ci

etl:
	$(ETL) python -m boffo_etl.build

fetch-status:
	$(ETL) python -m boffo_etl.fetch_status

check:
	$(ETL) python -m boffo_etl.checks

test: test-py test-site

test-py:
	$(ETL) pytest

test-site:
	cd site && $(NPM) test

site-dev:
	cd site && $(NPM) run dev

site-build:
	cd site && $(NPM) run build
	$(ETL) python -m boffo_etl.route_pages

sample-data:
	$(ETL) python -m boffo_etl.sample

pull-data:
	$(ETL) python -m boffo_etl.pull_data

guard:
	sh scripts/check-no-data.sh

clean:
	rm -rf data/build site/public/data site/dist
