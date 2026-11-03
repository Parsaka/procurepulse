"""RQ2 + RQ5 - What does each deviation cost, and which interventions recover the most?

Deviations fall into two families with different consequences:
  * Rework deviations create extra manual work and delay -> priced in EUR (effort) and days.
  * Control gaps bypass a control (pay before receipt, order after invoice). They often
    make the process *faster*, so their consequence is risk: the spend that flowed
    through an uncontrolled path ("exposure"), not effort.

RQ2: excess manual touches and excess cycle days per deviation type.
     Primary estimate: OLS with all nine deviation flags at once plus fixed effects for
     item category, spend area, creation month, value quintile and vendor size;
     standard errors clustered by vendor. Robustness check: coarsened exact matching
     (each single-deviation item vs fully conforming items in the same stratum).
RQ5: counterfactual value of interventions = model prediction with the intervention's
     deviations switched off, minus prediction as observed; scaled to one year and
     priced with low / base / high cost per manual touch.

Population: mature cohort (>= 90 days observed) and closed items, so cycle times are
not cut off by the end of the log. Durations are measured PO creation -> end of case.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analytics.common import connect, publish, save_json

DEVIATIONS = {
    "dev_invoice_before_gr": "Invoice posted before goods receipt",
    "dev_paid_before_gr": "Invoice paid before goods receipt",
    "dev_gr_on_two_way_item": "Goods receipt on a 2-way item",
    "dev_invoice_on_consignment": "Invoice on a consignment item",
    "dev_po_after_invoice": "Purchase order created after the invoice date",
    "dev_price_change_after_invoice": "Price changed after invoice receipt",
    "dev_quantity_change_after_gr": "Quantity changed after goods receipt",
    "dev_payment_block": "Invoice blocked for payment (variance)",
    "dev_reversal": "Goods receipt or invoice reversed",
}

REWORK = ["dev_price_change_after_invoice", "dev_quantity_change_after_gr", "dev_payment_block", "dev_reversal"]
CONTROL_GAPS = ["dev_invoice_before_gr", "dev_paid_before_gr", "dev_gr_on_two_way_item",
                "dev_invoice_on_consignment", "dev_po_after_invoice"]

# intervention -> (family, deviations it removes, owner)
INTERVENTIONS = {
    "Clean price data and invoice tolerances (contracts, info records)": (
        "rework", ["dev_payment_block", "dev_price_change_after_invoice"], "Purchasing master data / AP"),
    "First-time-right goods receipt and invoice entry": (
        "rework", ["dev_reversal"], "Warehouse / AP"),
    "Order the right quantity: delivery tolerances and PO changes before receipt": (
        "rework", ["dev_quantity_change_after_gr"], "Buyers / Warehouse"),
    "Enforce 'no PO, no pay'": (
        "control", ["dev_po_after_invoice"], "Procurement policy"),
    "Block payment until goods receipt": (
        "control", ["dev_paid_before_gr", "dev_invoice_before_gr"], "AP / SAP configuration"),
    "Correct item category set-up in the PO": (
        "control", ["dev_gr_on_two_way_item", "dev_invoice_on_consignment"], "SAP configuration"),
}

COST_PER_TOUCH_EUR = {"low": 5.0, "base": 15.0, "high": 30.0}
CONTROLS = "C(item_category) + C(spend_area) + C(month) + C(value_q) + C(vendor_size)"


def load(con) -> pd.DataFrame:
    df = con.execute(
        """
        select p.case_key, p.item_category, coalesce(p.spend_area, 'Unknown') as spend_area,
               p.po_created_month, p.net_value_eur, p.vendor_id, v.vendor_size_band as vendor_size,
               p.e2e_cycle_days as cycle_days, p.n_manual_touches, p.has_deviation, p.po_created_at,
               {flags}
        from marts.fct_po_item p
        join marts.dim_vendor v using (vendor_id)
        where p.is_mature_cohort and p.is_closed
        order by p.case_key
        """.format(flags=", ".join(f"p.{c}" for c in DEVIATIONS))
    ).fetchdf()
    df["month"] = pd.to_datetime(df["po_created_month"]).dt.strftime("%Y-%m")
    df["value_q"] = pd.qcut(df["net_value_eur"].rank(method="first"), 5, labels=False)
    for c in DEVIATIONS:
        df[c] = df[c].astype(int)
    return df


def fit(df: pd.DataFrame, outcome: str):
    present = [c for c in DEVIATIONS if df[c].sum() >= 30]  # too rare to estimate otherwise
    formula = f"{outcome} ~ {' + '.join(present)} + {CONTROLS}"
    model = smf.ols(formula, data=df).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["vendor_id"])[0]})
    return model, present


def cem(df: pd.DataFrame, outcome: str) -> pd.DataFrame:
    """Robustness: items with exactly one deviation vs fully conforming items, same stratum."""
    strata = ["item_category", "spend_area", "month", "value_q", "vendor_size"]
    conforming = df[df["has_deviation"] == 0]
    ctrl = conforming.groupby(strata)[outcome].mean().rename("ctrl_mean")
    n_dev = df[list(DEVIATIONS)].sum(axis=1)
    rows = []
    for c in DEVIATIONS:
        t = df[(df[c] == 1) & (n_dev == 1)]
        m = t.join(ctrl, on=strata, how="inner")
        if len(m) >= 30:
            rows.append({"deviation_code": c, "outcome": outcome, "matched_items": len(m),
                         "att": float((m[outcome] - m["ctrl_mean"]).mean())})
    return pd.DataFrame(rows)


def main() -> None:
    con = connect()
    df = load(con)

    # Scale the cohort to one year: cohort covers the creation months observed
    days_covered = (df["po_created_at"].max() - df["po_created_at"].min()).days + 1
    annual = 365.0 / days_covered

    rows, models = [], {}
    for outcome in ["n_manual_touches", "cycle_days"]:
        model, present = fit(df, outcome)
        models[outcome] = model
        ci = model.conf_int()
        for c in present:
            rows.append({
                "deviation_code": c, "deviation_label": DEVIATIONS[c], "outcome": outcome,
                "excess": float(model.params[c]), "ci_low": float(ci.loc[c, 0]), "ci_high": float(ci.loc[c, 1]),
                "p_value": float(model.pvalues[c]), "items_with_deviation": int(df[c].sum()),
            })
    effects = pd.DataFrame(rows)
    robust = pd.concat([cem(df, "n_manual_touches"), cem(df, "cycle_days")], ignore_index=True)
    effects = effects.merge(robust, on=["deviation_code", "outcome"], how="left").rename(
        columns={"att": "cem_excess", "matched_items": "cem_matched_items"})
    publish(con, "deviation_effects", effects)

    # RQ5: counterfactual per intervention (full elimination = upper bound)
    base_touch = models["n_manual_touches"].predict(df)
    base_days = models["cycle_days"].predict(df)
    iv_rows = []
    for name, (family, devs, owner) in INTERVENTIONS.items():
        cf = df.copy()
        cf[devs] = 0
        affected = df[devs].sum(axis=1) > 0
        saved_touch = float((base_touch - models["n_manual_touches"].predict(cf))[affected].sum()) * annual
        saved_days = float((base_days - models["cycle_days"].predict(cf))[affected].sum()) * annual
        iv_rows.append({
            "intervention": name,
            "family": family,
            "owner": owner,
            "deviations": ", ".join(DEVIATIONS[d] for d in devs),
            "affected_items_per_year": float(affected.sum() * annual),
            "exposed_value_eur_per_year": float(df.loc[affected, "net_value_eur"].sum() * annual),
            "touches_saved_per_year": saved_touch,
            "item_days_saved_per_year": saved_days,
            **{f"effort_saved_eur_{k}": saved_touch * v for k, v in COST_PER_TOUCH_EUR.items()},
        })
    interventions = pd.DataFrame(iv_rows)
    interventions = interventions[interventions["affected_items_per_year"] > 0]
    interventions = pd.concat([
        interventions[interventions.family == "rework"].sort_values("effort_saved_eur_base", ascending=False),
        interventions[interventions.family == "control"].sort_values("exposed_value_eur_per_year", ascending=False),
    ])
    interventions["rank_in_family"] = interventions.groupby("family").cumcount() + 1
    rework_total = interventions.loc[interventions.family == "rework", "touches_saved_per_year"].sum()
    interventions["share_of_rework_effort"] = np.where(
        interventions.family == "rework", interventions["touches_saved_per_year"] / rework_total, np.nan)
    publish(con, "intervention_value", interventions)

    # Headline: yearly cost of rework deviations = all rework flags switched off at once
    cf_all = df.copy()
    cf_all[REWORK] = 0
    rework_rows = df[REWORK].sum(axis=1) > 0
    control_rows = df[CONTROL_GAPS].sum(axis=1) > 0
    touches_total = float((base_touch - models["n_manual_touches"].predict(cf_all))[rework_rows].sum()) * annual
    days_total = float((base_days - models["cycle_days"].predict(cf_all))[rework_rows].sum()) * annual
    top3 = interventions[interventions.family == "rework"].head(3)
    headline = {
        "population_items": int(len(df)),
        "cohort_days": int(days_covered),
        "annualisation_factor": annual,
        "deviating_items_share": float(df["has_deviation"].mean()),
        "deviating_value_share": float(df.loc[df["has_deviation"] == 1, "net_value_eur"].sum() / df["net_value_eur"].sum()),
        "rework_items_per_year": float(rework_rows.sum() * annual),
        "rework_items_share": float(rework_rows.mean()),
        "excess_touches_per_year": touches_total,
        "excess_item_days_per_year": days_total,
        "excess_days_per_rework_item": float(days_total / (rework_rows.sum() * annual)),
        **{f"cost_of_rework_eur_{k}": touches_total * v for k, v in COST_PER_TOUCH_EUR.items()},
        "control_gap_items_per_year": float(control_rows.sum() * annual),
        "control_gap_exposure_eur_per_year": float(df.loc[control_rows, "net_value_eur"].sum() * annual),
        "top3_interventions": top3["intervention"].tolist(),
        "top3_effort_shares": [float(x) for x in top3["touches_saved_per_year"] / touches_total],
        "r2_touches": float(models["n_manual_touches"].rsquared),
        "r2_cycle_days": float(models["cycle_days"].rsquared),
    }
    save_json("cost_of_deviation", headline)
    print(effects.round(3).to_string(index=False))
    print(interventions.round(0).to_string(index=False))
    print(headline)


if __name__ == "__main__":
    np.random.seed(0)
    main()
