# KPI definitions

One definition per KPI, used identically in dbt (`dbt/models/marts`), the Streamlit app, the Power BI
measures (`bi/powerbi/measures.dax`) and the copilot (`copilot/kpi_definitions.json`).

| KPI | Definition | Population | Where |
|---|---|---|---|
| PO items | Count of PO items (EBELN + EBELP) | in scope | `fct_po_item` |
| Conformance rate | Share of items where no deviation rule fires | in scope | `mart_p2p_monthly_kpis` |
| Fully conforming | Fits the reference model (token replay) **and** no rule fires | mature, closed | `analytics.case_conformance` |
| Deviating value share | PO value on items with a deviation / all PO value | in scope | `mart_p2p_monthly_kpis` |
| First-time-right rate | Share of items with zero manual rework touches | in scope | `mart_p2p_monthly_kpis` |
| Manual touches per item | Events by a named human user per item | in scope | `fct_po_item.n_manual_touches` |
| Automation rate | Events by batch users / all events | in scope | `mart_p2p_monthly_kpis` |
| Cycle days | PO creation to case end (last clearing; last GR for consignment), closed items | in scope, closed | `fct_po_item.cycle_days` |
| End-to-end cycle days | First event of the case to case end (used by the cost model) | mature, closed | `fct_po_item.e2e_cycle_days` |
| Invoice to clear days | First invoice receipt to first clearing | in scope | `fct_po_item.invoice_to_clear_days` |
| PO-after-invoice rate | Vendor invoice dated before the PO ("no PO, no pay" violation) | in scope | `mart_p2p_monthly_kpis` |
| Rework item | Price change after invoice, quantity change after GR, variance payment block or reversal | any | `fct_po_item.dev_*` |
| Cost of rework | Excess touches from rework × cost per touch (€5 / €15 / €30) | mature, closed, annualised | `analytics.intervention_value` |
| Spend exposed | Net value of items with a control gap, annualised | mature, closed | `analytics.intervention_value` |
| Lift @10% | Rework rate in the top 10% of risk scores / overall rework rate | test period from 2018-08-01 | `analytics.model_metrics` |

**Populations.** *In scope* = PO created on or after 2018-01-01 and no event outside the analysis window
2018-01-01 to 2019-01-31 (the raw log has stray timestamps from 1948 to 2020; they stay in `fct_event`,
flagged `is_outside_window`, and their items are out of scope). *Mature* = in scope and at least 90 days
observed before the end of the log, so late outcomes are not missed. *Closed* = the item has reached its
case end: a clearing for invoiced flows, a goods receipt for consignment.

## Deviation rules

| Code | Rule | Checked on | Family |
|---|---|---|---|
| `dev_invoice_before_gr` | invoice posted before (or without) goods receipt | 3-way, invoice after GR | control |
| `dev_paid_before_gr` | invoice cleared before (or without) goods receipt | 3-way, invoice before GR | control |
| `dev_gr_on_two_way_item` | goods receipt on an item that expects none | 2-way | control |
| `dev_invoice_on_consignment` | invoice posted on a consignment item | consignment | control |
| `dev_po_after_invoice` | vendor invoice dated before the PO creation date | all | control |
| `dev_price_change_after_invoice` | price changed after the first invoice receipt | all | rework |
| `dev_quantity_change_after_gr` | quantity changed after the first goods receipt | all | rework |
| `dev_payment_block` | payment block set, except the designed block of invoice-before-GR items whose invoice preceded the GR | all | rework |
| `dev_reversal` | goods receipt, invoice or subsequent invoice cancelled | all | rework |
