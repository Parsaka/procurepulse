"""RQ1 - How much of the purchase-to-pay process follows its target flow?

Two independent views of conformance:
  1. Rule-based deviations (dbt, fct_po_item): nine business rules.
  2. Model-based conformance (this script): token-based replay of each closed PO item
     against a reference Petri net of its item category, built from a process tree.

The replay uses the milestone projection of the log (requisition, order, confirmation,
receipt, invoice, payment). Rework steps (changes, blocks, reversals) are measured by the
rules, so the two views complement each other instead of double counting.
'Vendor creates invoice' is the vendor's document date, not a step of the buyer, and is
left out of the projection.
"""
from __future__ import annotations

import pandas as pd
import pm4py
from pm4py.objects.conversion.process_tree import converter as pt_converter

from analytics.common import DOCS_IMG, connect, publish, save_json

MILESTONES = [
    "Create Purchase Requisition Item",
    "Create Purchase Order Item",
    "Receive Order Confirmation",
    "Record Goods Receipt",
    "Record Service Entry Sheet",
    "Record Invoice Receipt",
    "Clear Invoice",
]

PR, PO, OC = "'Create Purchase Requisition Item'", "'Create Purchase Order Item'", "'Receive Order Confirmation'"
GR, SES, IR, CL = "'Record Goods Receipt'", "'Record Service Entry Sheet'", "'Record Invoice Receipt'", "'Clear Invoice'"
RECEIPT = f"*( X( {GR}, {SES} ), tau )"          # one or more receipts (goods or services)
INVOICES = f"*( {IR}, tau )"                     # one or more invoices
PAYMENTS = f"X( tau, *( {CL}, tau ) )"           # zero or more clearings (partial payments)
START = f"X( tau, {PR} ), {PO}, X( tau, {OC} )"  # optional requisition and confirmation

# Target flow per item category, as process trees (pm4py notation)
REFERENCE_TREES = {
    # invoice only after receipt, payment after invoice; repeated for partial deliveries
    "3-way match, invoice after GR": f"->( {START}, *( ->( {RECEIPT}, {INVOICES}, {PAYMENTS} ), tau ) )",
    # invoice may arrive before or after receipt, but payment only after both
    "3-way match, invoice before GR": f"->( {START}, *( ->( +( {RECEIPT}, {INVOICES} ), {PAYMENTS} ), tau ) )",
    # no receipt expected
    "2-way match": f"->( {START}, *( ->( {INVOICES}, {PAYMENTS} ), tau ) )",
    # consignment: receipt only, invoicing is settled outside this flow
    "Consignment": f"->( {START}, {RECEIPT} )",
}


def load_log(con) -> pd.DataFrame:
    acts = ", ".join("'" + a + "'" for a in MILESTONES)
    return con.execute(
        f"""
        select e.case_key as "case:concept:name", e.activity as "concept:name",
               e.event_at as "time:timestamp", e.event_seq, p.item_category
        from marts.fct_event e
        join marts.fct_po_item p using (case_key)
        where p.is_mature_cohort and p.is_closed and e.activity in ({acts})
        order by e.case_key, e.event_at, e.event_seq
        """
    ).fetchdf()


def replay(log: pd.DataFrame, category: str) -> pd.DataFrame:
    tree = pm4py.parse_process_tree(REFERENCE_TREES[category])
    net, im, fm = pt_converter.apply(tree)
    sub = log[log["item_category"] == category]
    res = pm4py.conformance_diagnostics_token_based_replay(
        sub, net, im, fm,
        activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp",
    )
    # results come back in the order of the cases in the dataframe
    case_ids = sub["case:concept:name"].drop_duplicates().tolist()
    out = pd.DataFrame(
        {
            "case_key": case_ids,
            "item_category": category,
            "trace_fitness": [r["trace_fitness"] for r in res],
            "is_fit": [bool(r["trace_is_fit"]) for r in res],
            "missing_tokens": [r["missing_tokens"] for r in res],
            "remaining_tokens": [r["remaining_tokens"] for r in res],
        }
    )
    pm4py.save_vis_process_tree(tree, str(DOCS_IMG / f"reference_{_slug(category)}.png"))
    return out


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s.lower()).strip("_")


def main() -> None:
    DOCS_IMG.mkdir(parents=True, exist_ok=True)
    con = connect()
    log = load_log(con)
    results = pd.concat([replay(log, c) for c in REFERENCE_TREES], ignore_index=True)
    publish(con, "case_conformance", results)

    # Compare the model-based view with the rule-based view
    rules = con.execute(
        "select case_key, has_deviation, net_value_eur from marts.fct_po_item where is_mature_cohort and is_closed"
    ).fetchdf()
    both = results.merge(rules, on="case_key")
    summary = (
        both.groupby("item_category")
        .agg(
            po_items=("case_key", "size"),
            fit_rate=("is_fit", "mean"),
            avg_fitness=("trace_fitness", "mean"),
            rule_conformance_rate=("has_deviation", lambda s: 1 - s.mean()),
            fully_conforming_rate=("is_fit", lambda s: (s & ~both.loc[s.index, "has_deviation"]).mean()),
        )
        .reset_index()
    )
    overall = {
        "po_items": int(len(both)),
        "fit_rate": float(both["is_fit"].mean()),
        "rule_conformance_rate": float(1 - both["has_deviation"].mean()),
        "fully_conforming_rate": float((both["is_fit"] & ~both["has_deviation"]).mean()),
        "fully_conforming_value_share": float(
            both.loc[both["is_fit"] & ~both["has_deviation"], "net_value_eur"].sum() / both["net_value_eur"].sum()
        ),
        "agreement_rate": float((both["is_fit"] == ~both["has_deviation"]).mean()),
    }
    publish(con, "conformance_summary", summary)
    save_json("conformance_overall", overall)

    # Discovered model of the real process for the dominant category (top variants cover most cases)
    main_cat = log[log["item_category"] == "3-way match, invoice before GR"]
    top = pm4py.filter_variants_top_k(
        main_cat, 20, activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp"
    )
    tree = pm4py.discover_process_tree_inductive(
        top, activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp"
    )
    bpmn = pm4py.convert_to_bpmn(tree)
    pm4py.save_vis_bpmn(bpmn, str(DOCS_IMG / "discovered_bpmn_3way_before_gr.png"))
    dfg, sa, ea = pm4py.discover_dfg(
        main_cat, activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp"
    )
    pm4py.save_vis_dfg(dfg, sa, ea, str(DOCS_IMG / "dfg_3way_before_gr.png"))
    print(summary.to_string(index=False))
    print(overall)


if __name__ == "__main__":
    main()
