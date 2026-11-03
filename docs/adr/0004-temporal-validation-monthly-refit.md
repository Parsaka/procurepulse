# 4. Strict temporal validation and a monthly refit for the early-warning model

**Status:** accepted

**Context.** Labels (rework within 90 days) are only known 90 days after PO creation, and vendor behaviour
drifts (one large vendor went from under 10% to about 90% rework in June 2018). Random splits and
target-encoded vendor history leak the future and overstate performance.

**Decision.** Train only on items whose label is known on the scoring day; encode vendor, creator and
material-group history out of fold, grouped by purchase order; compare against two baselines; refit at the
start of each month (expanding window) and report the frozen model next to it.

**Consequences.** Reported lift (1.9× at top 10%) is what a deployment would see. The model is presented
as a review queue, not an automatic block.
