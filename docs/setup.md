# Setup guide: the four steps that need your accounts

Everything else runs in CI. Each step below is independent; do them in any order.
Total cost: €0 (GitHub Pages, Snowflake trial credits, Power BI Desktop); the copilot eval is optional and billed
to your Anthropic API key, a few dollars per full run.

## 1. Public dashboard on GitHub Pages (2 min, once)

1. Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. The `pages` workflow then deploys <https://parsaka.github.io/procurepulse/> on every push to `main` that
   touches `site/`, `app/data/` or `docs/img/`. Re-run it from **Actions → pages** if the first run failed
   because Pages was still off.

The Streamlit app (`make app`) is the interactive local version of the same results. Streamlit Community
Cloud was dropped as the public host ([ADR 6](adr/0006-free-hosting.md)).

## 2. Snowflake (20 min, free 30-day trial)

1. Sign up at <https://signup.snowflake.com>: edition **Standard**, cloud **AWS**, region **Europe (Frankfurt)**.
   No credit card is needed. Activate the account from the e-mail and sign in to Snowsight.
2. Create the CI key pair on your PC (in the repository folder):
   ```bash
   pip install cryptography
   python scripts/make_keypair.py pp_ci
   ```
   This writes `keys/pp_ci.p8` (private, never share) and `keys/pp_ci.pub.txt` (public).
3. In Snowsight: **Projects → Worksheets → +**. Paste `infra/snowflake/bootstrap.sql`, replace
   `<PP_CI_PUBLIC_KEY>` with the line from `keys/pp_ci.pub.txt`, then **Run all**.
   The last result row is your account identifier, for example `ABCDEFG-XY12345`.
   (`infra/snowflake/*.tf` creates the same objects with Terraform if you prefer that.)
4. GitHub → repository **Settings → Secrets and variables → Actions → New repository secret**, three times:

   | Name | Value |
   |---|---|
   | `SNOWFLAKE_ACCOUNT` | the identifier from step 3 |
   | `SNOWFLAKE_USER` | `PP_CI` |
   | `SNOWFLAKE_PRIVATE_KEY` | the whole content of `keys/pp_ci.p8`, including the BEGIN/END lines |

5. GitHub → **Actions → snowflake → Run workflow**. It loads the 15 SAP tables and 3 audit tables into `RAW` (role `PP_LOADER`),
   runs `dbt build` on Snowflake (role `PP_TRANSFORMER`) and loads the Python results into `ANALYTICS`.
6. Proof for the CV: in Snowsight run `SELECT COUNT(*) FROM PROCUREPULSE.MARTS.FCT_EVENT;`
   (1,595,923) and take a screenshot of the database tree and the query history.

The warehouse is XS, suspends after 60 seconds and sits under a 5-credit monthly resource monitor, so a
forgotten warehouse cannot burn the trial.

## 3. Process Copilot eval (optional, 5 min)

1. Create an API key at <https://console.anthropic.com> (Settings → API keys) and add credit if the account
   has none.
2. Add it as the repository secret `ANTHROPIC_API_KEY` (same place as step 2.4).
3. **Actions → copilot-eval → Run workflow**. The result table appears in the run summary and as the
   artifact `copilot-eval`. Optionally run a few questions first (`only`: `q01 q05 q25`).

Locally instead: `export ANTHROPIC_API_KEY=...` then `make copilot-eval`.

## 4. Power BI report (5 min, Windows)

1. Install **Power BI Desktop** (free).
2. Get the data: GitHub → **Actions → ci →** latest green run on `main` → **Artifacts → powerbi-data**, unzip
   it to `<repo>\data\bi\`.
3. `python bi/powerbi/build_pbip.py --data-folder <repo>\data\bi\` and open
   `bi/powerbi/ProcurePulse/ProcurePulse.pbip`. Press **Refresh**.
4. Check the cards against [findings.md](findings.md) (77.4% items without deviation, €1.27 M rework cost
   at €15, €21.48 M control-gap exposure, lift 1.90), save as `ProcurePulse.pbix`, and export one PNG per
   page to `docs/img/powerbi_<page>.png`.
