# ---------------------------------------------------------------------------
# Storage: one database, one schema per layer (mirrors the dbt layers)
# ---------------------------------------------------------------------------
resource "snowflake_database" "pp" {
  name                        = var.database_name
  comment                     = "ProcurePulse: SAP purchase-to-pay process mining (BPI Challenge 2019)"
  data_retention_time_in_days = 1
}

locals {
  schemas = {
    RAW          = "SAP tables as landed by the loader (EKKO, EKPO, EKBE, RBKP, CDHDR, ...)"
    STAGING      = "dbt staging views: typed, renamed SAP fields"
    INTERMEDIATE = "dbt intermediate: rebuilt event log and case attributes"
    MARTS        = "dbt marts: star schema and KPI marts for BI and the copilot"
    REFERENCE    = "dbt seeds: activity catalog"
    ANALYTICS    = "Python outputs: conformance, cost of deviation, early-warning scores"
  }
}

resource "snowflake_schema" "layer" {
  for_each = local.schemas
  database = snowflake_database.pp.name
  name     = each.key
  comment  = each.value
}

# ---------------------------------------------------------------------------
# Compute: one extra-small warehouse that suspends after 60 s, under a monitor
# ---------------------------------------------------------------------------
resource "snowflake_resource_monitor" "pp" {
  name                      = "PP_MONTHLY_MONITOR"
  credit_quota              = var.monthly_credit_quota
  frequency                 = "MONTHLY"
  start_timestamp           = "IMMEDIATELY"
  notify_triggers           = [50, 80]
  suspend_trigger           = 90
  suspend_immediate_trigger = 100
}

resource "snowflake_warehouse" "pp" {
  name                = var.warehouse_name
  warehouse_size      = "XSMALL"
  auto_suspend        = 60
  auto_resume         = "true"
  initially_suspended = true
  resource_monitor    = snowflake_resource_monitor.pp.name
  comment             = "ProcurePulse loads, dbt runs and BI queries"
}

# ---------------------------------------------------------------------------
# Access: least-privilege functional roles
#   PP_LOADER       writes RAW only
#   PP_TRANSFORMER  reads RAW, owns everything dbt builds
#   PP_REPORTER     reads MARTS + ANALYTICS (Power BI, Streamlit)
#   PP_COPILOT_RO   reads MARTS + ANALYTICS, nothing else (LLM tool calls)
# ---------------------------------------------------------------------------
resource "snowflake_account_role" "role" {
  for_each = toset(["PP_LOADER", "PP_TRANSFORMER", "PP_REPORTER", "PP_COPILOT_RO"])
  name     = each.key
}

resource "snowflake_grant_account_role" "to_sysadmin" {
  for_each         = snowflake_account_role.role
  role_name        = each.value.name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each          = snowflake_account_role.role
  account_role_name = each.value.name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.pp.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each          = snowflake_account_role.role
  account_role_name = each.value.name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.pp.name
  }
}

# Loader: create and fill tables and its stage in RAW
resource "snowflake_grant_privileges_to_account_role" "loader_raw" {
  account_role_name = snowflake_account_role.role["PP_LOADER"].name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE STAGE", "CREATE FILE FORMAT"]
  on_schema {
    schema_name = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer["RAW"].name}\""
  }
}

# Transformer: read RAW (current and future tables)
resource "snowflake_grant_privileges_to_account_role" "transformer_raw_schema" {
  account_role_name = snowflake_account_role.role["PP_TRANSFORMER"].name
  privileges        = ["USAGE"]
  on_schema {
    schema_name = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer["RAW"].name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "transformer_raw_tables" {
  for_each          = toset(["all", "future"])
  account_role_name = snowflake_account_role.role["PP_TRANSFORMER"].name
  privileges        = ["SELECT"]
  on_schema_object {
    dynamic "all" {
      for_each = each.key == "all" ? [1] : []
      content {
        object_type_plural = "TABLES"
        in_schema          = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer["RAW"].name}\""
      }
    }
    dynamic "future" {
      for_each = each.key == "future" ? [1] : []
      content {
        object_type_plural = "TABLES"
        in_schema          = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer["RAW"].name}\""
      }
    }
  }
}

# Transformer: build in the dbt-managed schemas
resource "snowflake_grant_privileges_to_account_role" "transformer_build" {
  for_each          = toset(["STAGING", "INTERMEDIATE", "MARTS", "REFERENCE", "ANALYTICS"])
  account_role_name = snowflake_account_role.role["PP_TRANSFORMER"].name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE FILE FORMAT"]
  on_schema {
    schema_name = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer[each.key].name}\""
  }
}

# Readers: MARTS + ANALYTICS only (current and future tables and views)
locals {
  reader_grants = {
    for pair in setproduct(["PP_REPORTER", "PP_COPILOT_RO"], ["MARTS", "ANALYTICS"], ["TABLES", "VIEWS"], ["all", "future"]) :
    join("|", pair) => { role = pair[0], schema = pair[1], kind = pair[2], scope = pair[3] }
  }
}

resource "snowflake_grant_privileges_to_account_role" "reader_schema" {
  for_each          = toset([for p in setproduct(["PP_REPORTER", "PP_COPILOT_RO"], ["MARTS", "ANALYTICS"]) : join("|", p)])
  account_role_name = snowflake_account_role.role[split("|", each.key)[0]].name
  privileges        = ["USAGE"]
  on_schema {
    schema_name = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer[split("|", each.key)[1]].name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "reader_objects" {
  for_each          = local.reader_grants
  account_role_name = snowflake_account_role.role[each.value.role].name
  privileges        = ["SELECT"]
  on_schema_object {
    dynamic "all" {
      for_each = each.value.scope == "all" ? [1] : []
      content {
        object_type_plural = each.value.kind
        in_schema          = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer[each.value.schema].name}\""
      }
    }
    dynamic "future" {
      for_each = each.value.scope == "future" ? [1] : []
      content {
        object_type_plural = each.value.kind
        in_schema          = "\"${snowflake_database.pp.name}\".\"${snowflake_schema.layer[each.value.schema].name}\""
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Service users (key-pair auth, no passwords)
# ---------------------------------------------------------------------------
resource "snowflake_service_user" "ci" {
  name              = "PP_CI"
  comment           = "GitHub Actions: loads RAW and runs dbt"
  default_warehouse = snowflake_warehouse.pp.name
  default_role      = snowflake_account_role.role["PP_TRANSFORMER"].name
  rsa_public_key    = var.ci_user_public_key
}

resource "snowflake_grant_account_role" "ci_roles" {
  for_each  = toset(["PP_LOADER", "PP_TRANSFORMER"])
  role_name = snowflake_account_role.role[each.key].name
  user_name = snowflake_service_user.ci.name
}

resource "snowflake_service_user" "copilot" {
  count             = var.copilot_user_public_key == "" ? 0 : 1
  name              = "PP_COPILOT"
  comment           = "Process Copilot: read-only access to MARTS and ANALYTICS"
  default_warehouse = snowflake_warehouse.pp.name
  default_role      = snowflake_account_role.role["PP_COPILOT_RO"].name
  rsa_public_key    = var.copilot_user_public_key
}

resource "snowflake_grant_account_role" "copilot_role" {
  count     = length(snowflake_service_user.copilot)
  role_name = snowflake_account_role.role["PP_COPILOT_RO"].name
  user_name = snowflake_service_user.copilot[0].name
}
