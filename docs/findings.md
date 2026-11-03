# Findings: the answer to the central question

> **What does deviation from the target purchase-to-pay process cost a large manufacturer in time,
> rework and risk, what drives it, and which three interventions would recover the most of it,
> early enough to act?**

Data: BPI Challenge 2019, a real SAP purchase-to-pay log of one multinational (coatings and paints),
4 company codes, 1,595,923 events, 251,734 PO items. All numbers below are reproduced by `make all`
and checked in CI. Effects and costs use the **mature, closed cohort**: 185,010 items with POs created
2018-01-01 to 2018-10-20 (293 days), so each item had at least 90 days to finish. Yearly figures are
annualised by 365/293.

## Answer in one paragraph

Only **77% of PO items follow their target process** (60% by value). The structure is almost always
right (97.5% of items fit the reference model of their item category); what breaks conformance is
**rework inside the right structure**. Four rework deviations hit **about 49,000 items a year** and cost
**about 84,500 extra manual touches and 846,000 extra item-days**, which is **€1.27 M a year in effort at
€15 per touch** (€0.42 M to €2.54 M for €5 to €30). It is concentrated: **5% of vendors cause 81% of rework
items**. Three interventions recover nearly all of it: **clean price data and invoice tolerances (51%)**,
**first-time-right goods receipt and invoice entry (40%)** and **ordering the right quantity (9%)**.
Separately, two control gaps put **€21.4 M of spend a year** outside the purchase-order control, almost all
of it POs raised after the invoice (€19.5 M). A model that scores each item when the PO is created flags a
top-10% queue with **1.9× the average rework rate**, early enough for a buyer to check price and quantity
before the order goes out.

## RQ1: How far does the process deviate from the target process?

Each item category has its own target process, set by two SAP flags on the PO item (`EKPO-WEPOS`
goods receipt expected, `EKPO-WEBRE` GR-based invoice verification) and the item type (`PSTYP` 2 =
consignment). The reference models are in `docs/img/reference_*.png`.

| Item category | Items | Fit (token replay) | Fully conforming |
|---|---:|---:|---:|
| 3-way match, invoice before GR | 164,114 | 97.7% | 76.2% |
| 3-way match, invoice after GR | 9,112 | 91.9% | 69.6% |
| Consignment | 11,627 | 99.9% | 96.4% |
| 2-way match | 157 | 100% | 21.0% |
| **All** | **185,010** | **97.5%** | **77.1%** (60.1% of value) |

Rule-based and model-based conformance agree on 79% of items. Three category rules never fire (no GR on
2-way items, no invoice on consignment items, no invoice before GR where GR-based invoice verification is
set): SAP enforces them, so they stay in the model as guardrails rather than findings.

## RQ2: What does each deviation cost?

Fixed-effect OLS on every item (controls: item category, spend area, PO month, value quintile, vendor size
band; standard errors clustered by vendor), cross-checked with coarsened exact matching (CEM).

| Deviation | Items | Extra manual touches | Extra days end to end | CEM touches |
|---|---:|---:|---:|---:|
| Goods receipt or invoice reversed | 6,774 | **+4.0** (3.5 to 4.6) | **+31.2** (26.2 to 36.2) | +3.5 |
| Price changed after invoice receipt | 2,245 | **+3.5** (2.2 to 4.8) | **+14.6** (6.9 to 22.2) | +3.1 |
| Quantity changed after goods receipt | 2,185 | **+2.8** (2.2 to 3.4) | **+12.0** (6.3 to 17.7) | +3.0 |
| Invoice blocked for payment (variance) | 34,043 | **+0.8** (0.6 to 0.9) | **+12.0** (7.1 to 16.9) | +0.8 |
| PO created after the invoice date | 2,609 | +0.5 (n.s.) | -14.0 (n.s.) | -0.3 |
| Invoice paid before goods receipt | 569 | -2.6 | -20.1 (n.s.) | n/a |

95% confidence intervals in brackets; n.s. = not significant at 5%. The first four are **rework**: they add
work and time. Payment blocks are cheap per item but hit 17% of items, so they are the largest cost in
total. The last two are **control gaps**: they skip steps rather than add them, so they are valued as
**spend exposed** (EUR that bypassed the control), never as effort. Mixing the two would make a policy
violation look like a saving.

Cost model and assumptions: [cost_model.md](cost_model.md).

## RQ3: What drives it?

- **Vendors.** 5% of vendors (98 of 1,961) cause **81%** of rework items; 1% (20 vendors) cause 52%.
- **Track record.** In the early-warning model, the vendor's and the creator's past rework rate carry
  **69%** of the explained signal (mean |SHAP|); PO size and sub spend area come next. Item value, company
  code and document type add almost nothing.
- **Drift.** Vendor 0000100105 went from under 10% rework (January to May 2018) to 67% to 93% (July to
  November) after a change in June. A frozen model misses this; the monthly refit and a vendor control
  chart catch it within weeks.
- **Where the time goes.** In the dominant category the longest handover is invoice receipt to clearing
  (median 37 days). That is mostly payment terms, not waste; the waste is the 47,000 removals of payment
  blocks followed by another 27.5 days (median) before clearing.

## RQ4: Can we see it coming early enough?

Label: rework within 90 days of PO creation. Test: POs from 2018-08-01. The deployed design is refitted at
the start of every month on all items whose 90-day outcome is already known that day, with vendor and
creator track records built the same way, so nothing from the future leaks in.

| Model | PR-AUC | ROC-AUC | Precision @10% | Lift @10% |
|---|---:|---:|---:|---:|
| Category prevalence | 0.168 | 0.526 | 17.4% | 1.08× |
| Logistic regression | 0.191 | 0.559 | 20.9% | 1.30× |
| LightGBM, trained once | 0.237 | 0.585 | 28.1% | 1.75× |
| **LightGBM, monthly refit** | 0.230 | 0.582 | **30.6%** | **1.91×** |

Honest reading: the signal at PO creation is modest overall, but it ranks well where it matters. A buyer who
checks the top 10% of new items each week checks items that end in rework almost twice as often as average.
That supports a review queue, not automatic blocking.

## RQ5: Which three interventions recover the most?

Each intervention removes a set of deviations; its value is the excess touches and days of those deviations
(RQ2) times their yearly frequency.

| # | Intervention | Owner | Fixes | Touches / year | Item-days / year | € / year (base) | Share |
|---|---|---|---|---:|---:|---:|---:|
| 1 | Clean price data and invoice tolerances (contracts, info records) | Purchasing master data / AP | payment blocks, price changes after invoice | 43,100 | 549,900 | €647 k | **51%** |
| 2 | First-time-right goods receipt and invoice entry | Warehouse / AP | reversals | 33,800 | 263,100 | €508 k | **40%** |
| 3 | Order the right quantity: delivery tolerances, PO changes before receipt | Buyers / warehouse | quantity changes after GR | 7,600 | 32,600 | €114 k | **9%** |

Control gaps to close (risk, not effort):

| Intervention | Items / year | Spend exposed / year |
|---|---:|---:|
| Enforce "no PO, no pay" | 3,250 | €19.5 M |
| Block payment until goods receipt | 709 | €2.0 M |

## Limits

- One company, one year, anonymised values; the effort cost per touch is an assumption (shown as a range).
- Effects are associations with strong controls, not randomised causal effects; CEM agrees within about
  ±0.5 touches for every rework deviation.
- The SAP tables are a faithful simulation rebuilt from the event log (proven lossless), not a live SAP
  extract; see [sap_data_model.md](sap_data_model.md).
