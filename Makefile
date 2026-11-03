# ProcurePulse: one command per pipeline stage. `make all` rebuilds everything from the raw log.
PY      ?= python3
DBT     := cd dbt && DBT_PROFILES_DIR=. dbt
RAW     := data/raw/bpic2019_events.parquet

.PHONY: help setup data extract dbt analytics ml exports app-data bi app test lint all \
        copilot copilot-eval snowflake-load snowflake-dbt snowflake-analytics tf-validate clean

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

setup:           ## install Python dependencies
	$(PY) -m pip install -r requirements.txt
	$(DBT) deps || true

data: $(RAW)     ## get the BPI Challenge 2019 log (from the repo's `data` branch)
$(RAW):
	mkdir -p data/raw
	git fetch origin data:refs/remotes/origin/data
	git show origin/data:raw/bpic2019_events.parquet > $(RAW)

extract: data    ## simulate the SAP extract (EKKO, EKPO, EKBE, RBKP, CDHDR, ...)
	$(PY) -m extract.sap_extract --src $(RAW) --out data/landing/sap

dbt:             ## build + test the warehouse on DuckDB (staging -> event log -> marts)
	$(DBT) build

analytics:       ## RQ1 conformance, RQ2/RQ5 cost of deviation and interventions
	$(PY) -m analytics.process_mining
	$(PY) -m analytics.cost_of_deviation

ml:              ## RQ3/RQ4 early-warning model
	$(PY) -m ml.early_warning

app-data:        ## export aggregates for the Streamlit app (committed in app/data)
	$(PY) -m analytics.export_app_data

bi:              ## export the star schema for Power BI (data/bi)
	$(PY) -m analytics.export_bi

exports: app-data bi

app:             ## run the Streamlit app locally
	streamlit run app/streamlit_app.py

test:            ## unit tests
	$(PY) -m pytest -q

lint:            ## ruff + terraform fmt
	ruff check .
	terraform -chdir=infra/snowflake fmt -check

all: extract dbt analytics ml exports test   ## the full pipeline

copilot:         ## run the copilot API on :8000 (needs ANTHROPIC_API_KEY)
	uvicorn copilot.api:app --port 8000

copilot-eval:    ## score the copilot on the 30-question eval set (needs ANTHROPIC_API_KEY)
	$(PY) -m copilot.eval.run_eval

# ---- Snowflake (needs SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PRIVATE_KEY) ----
tf-validate:     ## terraform init + validate (no credentials needed)
	terraform -chdir=infra/snowflake init -backend=false -input=false
	terraform -chdir=infra/snowflake validate

snowflake-load:  ## load the SAP landing zone into PROCUREPULSE.RAW
	$(PY) -m loader.load_snowflake raw

snowflake-dbt:   ## build + test the same dbt project on Snowflake
	$(DBT) build --target snowflake

snowflake-analytics: ## load Python results into PROCUREPULSE.ANALYTICS
	$(PY) -m loader.load_snowflake analytics

clean:
	rm -rf data/landing data/analytics data/bi data/procurepulse.duckdb dbt/target
