"""ProcurePulse: what does deviating from the target P2P process cost, and what fixes it?

Reads only the aggregated Parquet files in app/data (exported by
analytics/export_app_data.py), so it runs for free on Streamlit Community Cloud.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).parent / "data"
IMG = Path(__file__).parents[1] / "docs" / "img"
REPO = "https://github.com/Parsaka/procurepulse"

# Reference palette (validated for colour-vision deficiency); one hue per meaning
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
CATEGORY_COLORS = {"3-way match, invoice before GR": BLUE, "3-way match, invoice after GR": ORANGE,
                   "Consignment": AQUA, "2-way match": "#eda100"}

st.set_page_config(page_title="ProcurePulse · P2P process mining", page_icon="📦", layout="wide")


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"{name}.parquet")


@st.cache_data
def load_json(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=36, b=8), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(size=13), legend_title_text="",
                      hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(showgrid=False, linecolor="#d6d5d0")
    fig.update_yaxes(gridcolor="#ecebe7", zeroline=False)
    return fig


def eur(x: float) -> str:
    return f"€{x / 1e6:,.2f} M" if abs(x) >= 1e6 else f"€{x / 1e3:,.0f} k"


cost, conf, ew, ds = load_json("cost_of_deviation"), load_json("conformance_overall"), \
    load_json("early_warning"), load_json("dataset")
interventions = load("intervention_value")
effects = load("deviation_effects")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### ProcurePulse")
    st.caption("Process mining on a real SAP purchase-to-pay log (BPI Challenge 2019): "
               f"{ds['po_items_in_scope']:,} PO items, {ds['vendors']:,} vendors, "
               f"POs from {ds['first_po']} to {ds['last_po']}.")
    touch_cost = st.slider("Cost of one manual touch (EUR)", 5, 30, 15, step=1,
                           help="Fully loaded cost of one manual activity by a buyer or AP clerk "
                                "(about 10-20 minutes). 5 / 15 / 30 EUR are the low / base / high cases.")
    st.caption("All EUR figures on this page follow this assumption; touches and days do not.")
    st.markdown(f"[Code, SQL and method]({REPO}) · data: BPI Challenge 2019, 4TU (CC BY 4.0)")

tab_answer, tab_conf, tab_cost, tab_ew, tab_vendor, tab_trend = st.tabs(
    ["The answer", "Conformance", "Cost of deviation", "Early warning", "Vendors", "Monthly KPIs"])

# ---------------------------------------------------------------- 1. answer
with tab_answer:
    st.markdown("## What does deviating from the target purchase-to-pay process cost, "
                "what drives it, and which three fixes recover the most?")
    rework_eur = cost["excess_touches_per_year"] * touch_cost
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items that follow the target process", f"{conf['fully_conforming_rate']:.0%}",
              help="Fit the reference model of their item category and trigger none of the deviation rules.")
    c2.metric("Rework items per year", f"{cost['rework_items_per_year']:,.0f}",
              help="Items with a price change after invoice, quantity change after GR, payment block or reversal.")
    c3.metric("Excess manual touches per year", f"{cost['excess_touches_per_year']:,.0f}",
              help="Extra touches caused by rework deviations, estimated with fixed-effect regression.")
    c4.metric("Cost of rework per year", eur(rework_eur),
              help=f"Excess touches × €{touch_cost}. Plus {cost['excess_item_days_per_year']:,.0f} extra item-days in the process.")

    st.markdown("#### The three interventions that recover the most rework")
    rw = interventions[interventions.family == "rework"].sort_values("rank_in_family").copy()
    rw["eur"] = rw.touches_saved_per_year * touch_cost
    for _, r in rw.iterrows():
        with st.container(border=True):
            a, b, c, d = st.columns([5, 2, 2, 2])
            a.markdown(f"**{int(r.rank_in_family)}. {r.intervention}**  \n"
                       f"<span style='color:#52514e'>Owner: {r.owner} · fixes: {r.deviations}</span>",
                       unsafe_allow_html=True)
            b.metric("Share of rework effort", f"{r.share_of_rework_effort:.0%}")
            c.metric("Touches saved / year", f"{r.touches_saved_per_year:,.0f}")
            d.metric("Value / year", eur(r.eur), help=f"{r.item_days_saved_per_year:,.0f} item-days faster as well")

    ctl = interventions[interventions.family == "control"].sort_values("rank_in_family")
    st.markdown("#### Two control gaps to close (risk, not effort)")
    st.caption("These deviations do not create extra work (some even look faster), "
               "so they are valued by the spend that bypasses a control, not in touches.")
    cols = st.columns(len(ctl))
    for col, (_, r) in zip(cols, ctl.iterrows(), strict=False):
        col.metric(r.intervention, eur(r.exposed_value_eur_per_year) + " exposed / year",
                   help=f"{r.affected_items_per_year:,.0f} items per year · {r.deviations}")

    st.markdown("#### What drives it")
    conc = load("vendor_concentration")
    n5 = round(len(conc) * 0.05)
    st.markdown(
        f"- **Vendors:** {n5} vendors (5%) cause **{conc.cum_share.iloc[n5 - 1]:.0%}** of all rework items.\n"
        f"- **Who and what is ordered:** the vendor's and the creator's track record explain "
        f"{sum(d['share'] for d in ew['top_drivers'] if d['feature'] in ('hist_rate_vendor_id', 'hist_rate_created_by')):.0%} of the early-warning model's signal.\n"
        f"- **Early enough to act:** at PO creation, the top 10% riskiest items have "
        f"{ew['metrics'][-1]['lift_at_10pct']:.2f}× the average rework rate, so a buyer can check price and "
        "quantity before the order goes out (see *Early warning*).")

# ---------------------------------------------------------------- 2. conformance
with tab_conf:
    st.markdown("### Does the process run the way SAP is configured to run it?")
    st.caption("Each item category has its own target process (reference model, below). "
               "Fit = token replay on the milestone sequence; rule conformance = no deviation rule fires.")
    cs = load("conformance_summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Fit the reference model", f"{conf['fit_rate']:.1%}")
    c2.metric("Follow the target process (fit + rules)", f"{conf['fully_conforming_rate']:.1%}")
    c3.metric("…weighted by PO value", f"{conf['fully_conforming_value_share']:.1%}",
              help="Large orders deviate more often than small ones.")
    m = cs.melt(id_vars=["item_category", "po_items"], value_vars=["fit_rate", "fully_conforming_rate"],
                var_name="measure", value_name="rate")
    m["measure"] = m.measure.map({"fit_rate": "Fits reference model", "fully_conforming_rate": "Fully conforming"})
    fig = px.bar(m, x="rate", y="item_category", color="measure", barmode="group", orientation="h",
                 color_discrete_sequence=[GRAY, BLUE], text_auto=".0%",
                 hover_data={"po_items": ":,"}, labels={"rate": "", "item_category": ""})
    fig.update_xaxes(tickformat=".0%", range=[0, 1.08])
    st.plotly_chart(style(fig, 320), width="stretch")
    st.markdown("Every case fits structurally in almost all categories; what breaks conformance is "
                "**rework inside the right structure**: blocked invoices, changed prices and reversals.")

    dev = load("deviation_summary")
    st.markdown("#### Deviation rules (mature cohort: items observed for at least 90 days)")
    st.dataframe(dev[["deviation_label", "applies_to", "po_items", "share_of_items", "share_of_value"]],
                 hide_index=True, width="stretch",
                 column_config={"deviation_label": "Deviation", "applies_to": "Checked on",
                                "po_items": st.column_config.NumberColumn("PO items", format="%d"),
                                "share_of_items": st.column_config.ProgressColumn("Share of items", format="percent", max_value=0.25),
                                "share_of_value": st.column_config.ProgressColumn("Share of value", format="percent", max_value=0.25)})
    st.caption("Three category rules never fire: SAP itself enforces them (no GR on 2-way items, no invoice on "
               "consignment, no invoice before GR where GR-based invoice verification is set). "
               "They stay in the model as guardrails.")

    st.markdown("#### Reference models (target process per item category)")
    imgs = sorted(IMG.glob("reference_*.png"))
    for col, p in zip(st.columns(2) * 2, imgs, strict=False):
        col.image(str(p), caption=p.stem.replace("reference_", "").replace("_", " "), width="stretch")

    st.markdown("#### Most frequent variants")
    var = load("process_variants")
    cat = st.selectbox("Item category", sorted(var.item_category.unique()), index=2, key="var_cat")
    v = var[var.item_category == cat].head(10)
    st.dataframe(v[["variant", "po_items", "deviation_rate", "median_cycle_days", "avg_manual_touches"]],
                 hide_index=True, width="stretch",
                 column_config={"variant": st.column_config.TextColumn("Variant (activity sequence)", width="large"),
                                "deviation_rate": st.column_config.NumberColumn("Deviation rate", format="percent"),
                                "median_cycle_days": st.column_config.NumberColumn("Median days", format="%.0f"),
                                "avg_manual_touches": st.column_config.NumberColumn("Manual touches", format="%.1f")})
    hand = load("handover_times")
    st.markdown("#### Where the time goes (handovers with the most total waiting)")
    h = hand[hand.item_category == cat].head(8).copy()
    h["step"] = h.from_activity + " → " + h.to_activity
    fig = px.bar(h.iloc[::-1], x="total_wait_days", y="step", orientation="h", color_discrete_sequence=[BLUE],
                 hover_data={"transitions": ":,", "median_wait_days": ":.1f", "p90_wait_days": ":.1f"},
                 labels={"total_wait_days": "Total waiting time (item-days)", "step": ""})
    st.plotly_chart(style(fig, 340), width="stretch")

# ---------------------------------------------------------------- 3. cost
with tab_cost:
    st.markdown("### What does each deviation add, compared with a similar clean item?")
    st.caption("OLS with fixed effects for item category, spend area, PO month, value quintile and vendor size; "
               "standard errors clustered by vendor. Bars are 95% confidence intervals. "
               "Coarsened exact matching (CEM) gives a second, independent estimate.")
    outcome = st.radio("Outcome", ["n_manual_touches", "cycle_days"], horizontal=True,
                       format_func=lambda o: {"n_manual_touches": "Extra manual touches per item",
                                              "cycle_days": "Extra days end to end"}[o])
    e = effects[effects.outcome == outcome].sort_values("excess")
    e["significant"] = e.p_value < 0.05
    fig = go.Figure(go.Scatter(
        x=e.excess, y=e.deviation_label, mode="markers",
        marker=dict(size=11, color=[BLUE if s else GRAY for s in e.significant], line=dict(width=2, color="white")),
        error_x=dict(type="data", symmetric=False, array=e.ci_high - e.excess, arrayminus=e.excess - e.ci_low,
                     color="#a3a29d", thickness=2, width=0),
        customdata=e[["items_with_deviation", "cem_excess", "p_value"]],
        hovertemplate="%{y}<br>excess %{x:.2f} (95%% CI shown)<br>items %{customdata[0]:,}"
                      "<br>CEM estimate %{customdata[1]:.2f}<br>p = %{customdata[2]:.3f}<extra></extra>"))
    fig.add_vline(x=0, line_color="#52514e", line_width=1)
    st.plotly_chart(style(fig, 330), width="stretch")
    st.markdown("**Reading it:** reversals and price changes after the invoice are the most expensive "
                "events per item; payment blocks are cheap per item but happen on 17% of items, which "
                "makes them the largest cost in total. Paying before goods receipt and creating the PO after "
                "the invoice do **not** add work, they skip steps: they are control risks, not rework.")
    st.markdown("#### Sensitivity of the yearly cost of rework")
    sens = pd.DataFrame({"case": ["Low (€5/touch)", "Base (€15/touch)", "High (€30/touch)", f"Your setting (€{touch_cost})"],
                         "eur": [cost["excess_touches_per_year"] * x for x in (5, 15, 30, touch_cost)]})
    st.dataframe(sens, hide_index=True, column_config={"case": "Case", "eur": st.column_config.NumberColumn("EUR per year", format="€%,.0f")})

# ---------------------------------------------------------------- 4. early warning
with tab_ew:
    st.markdown("### Can we see rework coming when the PO is created?")
    st.caption(f"Label: rework within {ew['horizon_days']} days of PO creation. Test period: POs from "
               f"{ew['test_window_start']}. The deployed design is refitted at the start of every month on all items "
               f"whose {ew['horizon_days']}-day outcome is already known that day, so nothing from the future leaks in; "
               "vendor and creator track records are computed the same way.")
    mm = load("model_metrics")
    st.dataframe(mm, hide_index=True, width="stretch",
                 column_config={"model": "Model", "pr_auc": st.column_config.NumberColumn("PR-AUC", format="%.3f"),
                                "roc_auc": st.column_config.NumberColumn("ROC-AUC", format="%.3f"),
                                "brier": st.column_config.NumberColumn("Brier", format="%.3f"),
                                "precision_at_10pct": st.column_config.NumberColumn("Precision @10%", format="percent"),
                                "recall_at_10pct": st.column_config.NumberColumn("Recall @10%", format="percent"),
                                "lift_at_10pct": st.column_config.NumberColumn("Lift @10%", format="%.2f×")})
    st.info(f"Honest reading: the signal at PO creation is modest (ROC-AUC {mm.roc_auc.iloc[-1]:.2f}), "
            f"but it ranks well where it matters: the top 10% flagged items carry rework "
            f"{mm.lift_at_10pct.iloc[-1]:.2f}× as often as average. That is enough for a review queue, "
            "not for automatic blocking. Refitting monthly beats a frozen model because vendors change: "
            "see the control chart in *Vendors*.")
    a, b = st.columns(2)
    cal = load("model_calibration")
    fig = go.Figure()
    fig.add_bar(x=cal.risk_decile, y=cal.observed, name="Observed rework rate", marker_color=BLUE,
                hovertemplate="decile %{x}<br>observed %{y:.1%}<extra></extra>")
    fig.add_scatter(x=cal.risk_decile, y=cal.predicted, name="Predicted", mode="lines+markers",
                    line=dict(color=ORANGE, width=2), marker=dict(size=8),
                    hovertemplate="decile %{x}<br>predicted %{y:.1%}<extra></extra>")
    fig.update_yaxes(tickformat=".0%")
    fig.update_xaxes(title="Risk decile (10 = highest)", dtick=1)
    fig.update_layout(title="Calibration on the test period", legend=dict(orientation="h", y=-0.25))
    a.plotly_chart(style(fig, 360), width="stretch")
    drv = load("risk_drivers").head(8).iloc[::-1]
    names = {"hist_rate_vendor_id": "Vendor's rework track record", "hist_rate_created_by": "Creator's rework track record",
             "items_in_po": "Items in the PO", "sub_spend_area": "Sub spend area", "item_type": "Item type",
             "hist_items_created_by": "Creator's volume", "hist_items_vendor_id": "Vendor's volume",
             "log_value": "Item value", "hist_rate_material_group": "Material group track record",
             "spend_area": "Spend area", "creator_is_batch": "Created by a batch user"}
    fig = px.bar(drv, x="share", y=drv.feature.map(lambda f: names.get(f, f)), orientation="h",
                 color_discrete_sequence=[BLUE], labels={"share": "Share of mean |SHAP|", "y": ""},
                 title="What drives the risk score (SHAP)")
    fig.update_xaxes(tickformat=".0%")
    b.plotly_chart(style(fig, 360), width="stretch")
    st.markdown("#### Review queue: top-decile items in the test period")
    al = load("early_warning_alerts")
    st.dataframe(al.head(200), hide_index=True, width="stretch",
                 column_config={"risk_score": st.column_config.ProgressColumn("Risk", format="%.2f", min_value=0, max_value=1),
                                "net_value_eur": st.column_config.NumberColumn("Value (EUR)", format="%,.0f"),
                                "top_reason": "Main reason"})

# ---------------------------------------------------------------- 5. vendors
with tab_vendor:
    st.markdown("### A few vendors cause most of the rework")
    conc = load("vendor_concentration")
    fig = px.line(conc.assign(vendor_share=conc.vendor_rank / conc.vendors), x="vendor_share", y="cum_share",
                  labels={"vendor_share": "Share of vendors (sorted by rework items)", "cum_share": "Share of rework items"},
                  color_discrete_sequence=[BLUE])
    fig.update_traces(line=dict(width=2), hovertemplate="top %{x:.1%} of vendors → %{y:.1%} of rework<extra></extra>")
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    fig.add_annotation(x=0.05, y=conc.cum_share.iloc[n5 - 1], text=f"5% of vendors → {conc.cum_share.iloc[n5 - 1]:.0%}",
                       showarrow=True, arrowhead=0, ax=60, ay=30)
    st.plotly_chart(style(fig, 340), width="stretch")
    sc = load("vendor_scorecard")
    st.markdown("#### Control chart: monthly rework rate of the 10 vendors with the most rework")
    vm = load("vendor_monthly_rework")
    vm["po_created_month"] = pd.to_datetime(vm.po_created_month)
    vend = st.selectbox("Vendor", vm.vendor_id.unique(), key="vm_vendor")
    one = vm[vm.vendor_id == vend]
    centre = (one.rework_rate * one.po_items).sum() / one.po_items.sum()
    fig = px.line(one, x="po_created_month", y="rework_rate", markers=True, color_discrete_sequence=[BLUE],
                  hover_data={"po_items": ":,"}, labels={"po_created_month": "", "rework_rate": "Rework rate"})
    fig.update_traces(line=dict(width=2), marker=dict(size=8, line=dict(width=2, color="white")))
    fig.add_hline(y=centre, line_dash="dot", line_color=GRAY, annotation_text=f"average {centre:.0%}",
                  annotation_position="top left")
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    st.plotly_chart(style(fig, 320), width="stretch")
    st.caption("Vendor 0000100105 is the clearest case: its rework rate jumps from under 10% to about 90% in "
               "June-July 2018 and stays high through November (December is too recent: its rework has not happened yet). "
               "A monthly KPI alert on this chart would have caught "
               "it within weeks; a model trained once in spring cannot.")
    st.markdown("#### Vendor scorecard (vendors with at least 50 PO items)")
    st.dataframe(sc.head(100)[["deviation_volume_rank", "vendor_name", "vendor_size_band", "po_items", "po_value_eur",
                               "deviation_rate", "payment_block_rate", "avg_rework_touches", "median_cycle_days"]],
                 hide_index=True, width="stretch",
                 column_config={"deviation_volume_rank": "Rank", "vendor_name": "Vendor (anonymised)",
                                "vendor_size_band": "Size", "po_value_eur": st.column_config.NumberColumn("PO value", format="€%,.0f"),
                                "deviation_rate": st.column_config.NumberColumn("Deviation rate", format="percent"),
                                "payment_block_rate": st.column_config.NumberColumn("Payment blocks", format="percent"),
                                "avg_rework_touches": st.column_config.NumberColumn("Rework touches / item", format="%.2f"),
                                "median_cycle_days": st.column_config.NumberColumn("Median days", format="%.0f")})

# ---------------------------------------------------------------- 6. monthly
with tab_trend:
    st.markdown("### Monthly KPIs by PO creation month")
    k = load("monthly_kpis")
    k["po_created_month"] = pd.to_datetime(k.po_created_month)
    kpis = {"conformance_rate": "Conformance rate", "first_time_right_rate": "First-time-right rate",
            "automation_rate": "Automation rate", "avg_manual_touches": "Manual touches per item",
            "median_cycle_days": "Median cycle days", "po_after_invoice_rate": "PO after invoice rate"}
    choice = st.selectbox("KPI", list(kpis), format_func=kpis.get)
    cats = [c for c in CATEGORY_COLORS if c in set(k.item_category)]
    fig = px.line(k, x="po_created_month", y=choice, color="item_category", markers=True,
                  category_orders={"item_category": cats}, color_discrete_map=CATEGORY_COLORS,
                  labels={"po_created_month": "", choice: kpis[choice]}, hover_data={"po_items": ":,"})
    fig.update_traces(line=dict(width=2), marker=dict(size=8, line=dict(width=2, color="white")))
    if choice.endswith("rate"):
        fig.update_yaxes(tickformat=".0%")
    fig.update_layout(legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(style(fig, 380), width="stretch")
    st.caption("Months near the end of the window have fewer closed items, so cycle-time KPIs there are "
               "right-censored; the cost model uses only the mature cohort (90 days observed).")
    st.dataframe(k, hide_index=True, width="stretch")
