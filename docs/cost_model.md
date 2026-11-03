# Cost model

The model prices **effort and time**, and keeps **risk** separate. It deliberately has no
cost-of-capital term: a slower purchase-to-pay process does not cost the buyer capital (paying later is,
if anything, cheaper for the buyer), so adding one would inflate the result.

## 1. Rework deviations: effort and time

For each rework deviation *d* (reversal, price change after invoice, quantity change after GR, variance
payment block):

```
excess_touches_d  = OLS coefficient of d on n_manual_touches   (fixed effects, vendor-clustered SE)
excess_days_d     = OLS coefficient of d on e2e_cycle_days
items_per_year_d  = items with d in the cohort × 365 / 293
touches_per_year  = Σ_d excess_touches_d × items_per_year_d
cost_per_year     = touches_per_year × cost_per_touch
```

All deviation flags enter the same regression, so an item with two deviations is not counted twice.

| Assumption | Low | Base | High | Why |
|---|---:|---:|---:|---|
| Cost of one manual touch | €5 | €15 | €30 | 10 to 20 minutes of a buyer or AP clerk at a fully loaded €45 to €90 per hour, low case for simple confirmations |

Result: 84,530 excess touches per year → **€0.42 M / €1.27 M / €2.54 M** per year, plus 845,700 extra
item-days (17 days per rework item) that the effort figure does not price.

**Manual touch** = an event done by a named human SAP user (`fct_event.is_manual_touch`). Batch users and
events without a user (the vendor's own "Vendor creates invoice") do not count.

**Cycle time** for the regression is `e2e_cycle_days`, from the first event of the case to the last
clearing, not from PO creation. Otherwise items whose PO was raised after the invoice would look faster
because their clock starts late.

## 2. Control gaps: exposure

PO after invoice, invoice paid before GR, invoice before GR, GR on a 2-way item and invoice on a consignment
item skip a control. They are reported as **spend exposed per year** (net value of the affected items ×
365/293), never as effort, and never mixed into the rework total.

## 3. Interventions

| Intervention | Family | Deviations it removes |
|---|---|---|
| Clean price data and invoice tolerances | rework | variance payment block, price change after invoice |
| First-time-right goods receipt and invoice entry | rework | reversal |
| Order the right quantity | rework | quantity change after GR |
| Enforce "no PO, no pay" | control | PO after invoice |
| Block payment until goods receipt | control | invoice paid before GR, invoice before GR |

Each intervention is assumed to remove its deviations completely: the figures are the ceiling of what it
can recover. Its share is its touches divided by all rework touches.

Code: `analytics/cost_of_deviation.py`. Output: `analytics.deviation_effects`, `analytics.intervention_value`.
