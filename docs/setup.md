# Setup guide: the four steps that need your accounts

Everything else runs in CI. Each step below is independent; do them in any order.
Total cost: €0 (Snowflake trial credits, free Streamlit and Power BI Desktop); the copilot eval is billed to
your Anthropic API key, a few dollars per full run.

## 1. Public app on Streamlit Community Cloud (5 min)

1. Sign in at <https://share.streamlit.io> with GitHub.
2. **Create app → Deploy a public app from GitHub**:
   repository `Parsaka/procurepulse`, branch `main`, main file `app/streamlit_app.py`, App URL `procurepulse`.
   Under **Advanced settings** pick Python **3.12**. Deploy.
3. App menu **⋮ → Settings → Sharing**: *Who can view this app* = **This app is public and searchable**.
4. Open the URL in a private browser window (not signed in). You should see six tabs. If you see
   "You do not have access to this app", step 3 is not saved.

The app reads only `app/data/*.parquet`, so it needs no secrets and redeploys by itself on every push to `main`.

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

5. GitHub → **Actions → snowflake → Run workflow**. It loads the 16 SAP tables into `RAW` (role `PP_LOADER`),
   runs `dbt build` on Snowflake (role `PP_TRANSFORMER`) and loads the Python results into `ANALYTICS`.
6. Proof for the CV: in Snowsight run `SELECT COUNT(*) FROM PROCUREPULSE.MARTS.FCT_EVENT;`
   (1,595,923) and take a screenshot of the database tree and the query history.

The warehouse is XS, suspends after 60 seconds and sits under a 5-credit monthly resource monitor, so a
forgotten warehouse cannot burn the trial.

## 3. Process Copilot eval (5 min)

1. Create an API key at <https://console.anthropic.com> (Settings → API keys) and add credit if the account
   has none.
2. Add it as the repository secret `ANTHROPIC_API_KEY` (same place as step 2.4).
3. **Actions → copilot-eval → Run workflow**. The result table appears in the run summary and as the
   artifact `copilot-eval`. Optionally run a few questions first (`only`: `q01 q05 q25`).

Locally instead: `export ANTHROPIC_API_KEY=...` then `make copilot-eval`.

## 4. Power BI report (30 to 45 min, Windows)

1. Install **Power BI Desktop** from the Microsoft Store (free).
2. Get the data: GitHub → **Actions → ci →** latest green run on `main` → **Artifacts → powerbi-data**.
   Unzip it to a folder, for example `C:\procurepulse\bi\`.
3. Follow [bi/powerbi/README.md](../bi/powerbi/README.md): parameter `DataFolder` = that folder with a trailing
   `\`, one query per table from `power_query.m`, the relationships table, then the measures from
   `measures.dax` and the five pages.
4. Check the cards against [findings.md](findings.md), save as `ProcurePulse.pbix`, and export one PNG per
   page to `docs/img/powerbi_<page>.png`.
