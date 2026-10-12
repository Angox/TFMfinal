resource "aws_budgets_budget" "tfm_alerta_costes" {
  name              = "alerta-costes-tfm-fargate"
  budget_type       = "COST"
  limit_amount      = "5.0"
  limit_unit        = "USD"
  time_unit         = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.email_alertas]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.email_alertas]
  }
}
