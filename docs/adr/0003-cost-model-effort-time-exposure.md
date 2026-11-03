# 3. Price effort and time; report control gaps as exposure; no cost of capital

**Status:** accepted

**Context.** First drafts priced deviations with a cost of capital on longer cycle times and synthetic
payment terms. A longer P2P cycle does not cost the buyer capital (paying later helps the buyer), and the
log has no payment terms. Control-gap deviations (PO after invoice, paid before GR) have *negative* effort
effects because they skip steps, which made a top-3 share exceed 100%.

**Decision.** Rework deviations are priced as excess manual touches × cost per touch (€5/€15/€30) and
reported with excess item-days. Control gaps are reported as spend exposed per year. The two families are
never added together.

**Consequences.** Every euro in the headline traces to a regression coefficient and one stated assumption;
the sensitivity range is shown wherever the number appears.
