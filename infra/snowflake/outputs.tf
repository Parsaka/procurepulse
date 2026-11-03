output "database" {
  value = snowflake_database.pp.name
}

output "warehouse" {
  value = snowflake_warehouse.pp.name
}

output "ci_user" {
  value = snowflake_service_user.ci.name
}
