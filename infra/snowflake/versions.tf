terraform {
  required_version = ">= 1.6"
  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 1.2"
    }
  }
}

# Credentials come from the environment, never from this repo:
#   SNOWFLAKE_ORGANIZATION_NAME, SNOWFLAKE_ACCOUNT_NAME, SNOWFLAKE_USER,
#   SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT, SNOWFLAKE_PRIVATE_KEY (admin key pair)
# Run once as an ACCOUNTADMIN user of the 30-day trial account.
provider "snowflake" {
  role = "ACCOUNTADMIN"
}
