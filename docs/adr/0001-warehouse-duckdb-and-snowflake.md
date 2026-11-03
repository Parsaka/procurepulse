# 1. One dbt project, two warehouses: DuckDB and Snowflake

**Status:** accepted

**Context.** The project must run for free, forever, and still show the cloud warehouse that German job
ads ask for (Snowflake, Fabric). A Snowflake trial lasts 30 days; Microsoft Fabric trials are often blocked
for student and new tenants.

**Decision.** Build the dbt project on DuckDB (local and CI, €0) and keep it portable to Snowflake. Every
dialect difference goes through a dispatched macro (`dbt/macros/dialect.sql`, `sap.sql`). CI compiles the
Snowflake target on every push. Snowflake infrastructure is Terraform (`infra/snowflake`) with an XS
warehouse that suspends after 60 s, a monthly resource monitor and least-privilege roles.

**Consequences.** The pipeline never depends on a trial. Snowflake runs are a manual workflow while the
trial lasts. Fabric is dropped; Power BI Desktop (free) covers the Microsoft BI side.
