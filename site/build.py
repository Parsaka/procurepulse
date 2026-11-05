"""Build the static ProcurePulse dashboard (GitHub Pages) from app/data.

    python site/build.py            # writes site/_out/index.html (+ images)

Same numbers as the Streamlit app, as one self-contained HTML page: Plotly charts,
a cost-per-touch slider in plain JavaScript, no server. Deployed by .github/workflows/pages.yml.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
OUT = ROOT / "site" / "_out"
REPO = "https://github.com/Parsaka/procurepulse"
BLUE, ORANGE, AQUA, YELLOW, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a8984"
CAT_COLORS = {
    "3-way match, invoice before GR": BLUE,
    "3-way match, invoice after GR": ORANGE,
    "Consignment": AQUA,
    "2-way match": YELLOW,
}


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"{name}.parquet")


def js(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def layout(fig: go.Figure, height: int = 340, **kw) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=12, t=36, b=8),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", size=13, color="#2b2a27"),
        legend=dict(orientation="h", y=-0.3, yanchor="top"),
        hoverlabel=dict(bgcolor="white"),
        **kw,
    )
    fig.update_xaxes(showgrid=False, linecolor="#d6d5d0")
    fig.update_yaxes(gridcolor="#ecebe7", zeroline=False)
    return fig


_first = True


def chart(fig: go.Figure) -> str:
    global _first
    out = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if _first else False,
        config={"displayModeBar": False, "responsive": True},
    )
    _first = False
    return f'<div class="chart">{out}</div>'


def table(df: pd.DataFrame, fmt: dict[str, str]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in fmt)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for col, f in fmt.items():
            v = r[col]
            num = isinstance(v, (int, float)) and not isinstance(v, bool)
            cells.append(f'<td class="{"num" if num else ""}">{html.escape(f.format(v) if f else str(v))}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def eur(x: float) -> str:
    return f"€{x / 1e6:,.2f} M" if abs(x) >= 1e6 else f"€{x / 1e3:,.0f} k"


def build() -> Path:
    cost, conf, ew, ds = js("cost_of_deviation"), js("conformance_overall"), js("early_warning"), js("dataset")
    iv, eff = load("intervention_value"), load("deviation_effects")
    conc, cs = load("vendor_concentration"), load("conformance_summary")
    mm, cal, drv = load("model_metrics"), load("model_calibration"), load("risk_drivers")
    vm, k, dev = load("vendor_monthly_rework"), load("monthly_kpis"), load("deviation_summary")
    n5 = round(len(conc) * 0.05)
    top5 = conc.cum_share.iloc[n5 - 1]
    lift = mm.lift_at_10pct.iloc[-1]
    sections = []

    # ---- answer
    rw = iv[iv.family == "rework"].sort_values("rank_in_family")
    cards = "".join(
        f'<div class="iv"><div class="rank">{int(r.rank_in_family)}</div><div class="ivbody"><h4>{html.escape(r.intervention)}</h4>'
        f'<p class="muted">Owner: {html.escape(r.owner)} · fixes: {html.escape(r.deviations)}</p></div>'
        f'<div class="ivnum"><span class="big">{r.share_of_rework_effort:.0%}</span><span class="muted">of rework effort</span></div>'
        f'<div class="ivnum"><span class="big">{r.touches_saved_per_year:,.0f}</span><span class="muted">touches / year</span></div>'
        f'<div class="ivnum"><span class="big eur" data-touches="{r.touches_saved_per_year:.0f}"></span><span class="muted">per year</span></div></div>'
        for _, r in rw.iterrows()
    )
    ctl = iv[iv.family == "control"].sort_values("rank_in_family")
    ctl_cards = "".join(
        f'<div class="kpi"><span class="label">{html.escape(r.intervention)}</span>'
        f'<span class="big">{eur(r.exposed_value_eur_per_year)}</span>'
        f'<span class="muted">spend exposed per year · {r.affected_items_per_year:,.0f} items</span></div>'
        for _, r in ctl.iterrows()
    )
    sections.append(f"""
<section id="answer">
  <h2>The answer</h2>
  <div class="kpis">
    <div class="kpi"><span class="label">Follow the target process</span><span class="big">{conf["fully_conforming_rate"]:.0%}</span><span class="muted">{conf["fully_conforming_value_share"]:.0%} of PO value</span></div>
    <div class="kpi"><span class="label">Rework items per year</span><span class="big">{cost["rework_items_per_year"]:,.0f}</span><span class="muted">{cost["excess_item_days_per_year"]:,.0f} extra item-days</span></div>
    <div class="kpi"><span class="label">Excess manual touches per year</span><span class="big">{cost["excess_touches_per_year"]:,.0f}</span><span class="muted">from four rework deviations</span></div>
    <div class="kpi accent"><span class="label">Cost of rework per year</span><span class="big eur" data-touches="{cost["excess_touches_per_year"]:.0f}"></span><span class="muted">at <b class="rate"></b> per touch</span></div>
  </div>
  <div class="slider"><label for="rate">Cost of one manual touch: <b class="rate"></b></label>
    <input id="rate" type="range" min="5" max="30" step="1" value="15">
    <span class="muted">10 to 20 minutes of a buyer or AP clerk; €5 / €15 / €30 = low / base / high case</span></div>
  <h3>Three interventions recover all of the rework effort</h3>
  {cards}
  <h3>Two control gaps to close (risk, not effort)</h3>
  <div class="kpis two">{ctl_cards}</div>
  <h3>What drives it</h3>
  <ul>
    <li><b>Vendors:</b> {n5} vendors (5%) cause <b>{top5:.0%}</b> of all rework items.</li>
    <li><b>Track record:</b> the vendor's and the creator's past rework rate carry
        <b>{sum(d["share"] for d in ew["top_drivers"] if d["feature"] in ("hist_rate_vendor_id", "hist_rate_created_by")):.0%}</b> of the early-warning signal.</li>
    <li><b>Early enough:</b> scored at PO creation, the top 10% riskiest items carry rework <b>{lift:.1f}×</b> as often as average.</li>
  </ul>
</section>""")

    # ---- conformance
    m = cs.melt(id_vars=["item_category", "po_items"], value_vars=["fit_rate", "fully_conforming_rate"])
    fig = go.Figure()
    for var, name, color in (
        ("fit_rate", "Fits reference model", GRAY),
        ("fully_conforming_rate", "Fully conforming", BLUE),
    ):
        d = m[m.variable == var]
        fig.add_bar(
            y=d.item_category,
            x=d.value,
            name=name,
            orientation="h",
            marker_color=color,
            text=[f"{v:.0%}" for v in d.value],
            textposition="outside",
            customdata=d.po_items,
            hovertemplate="%{y}<br>%{x:.1%} of %{customdata:,} items<extra>" + name + "</extra>",
        )
    layout(fig, 300, barmode="group")
    fig.update_xaxes(tickformat=".0%", range=[0, 1.12])
    dev_tbl = table(
        dev[["deviation_label", "applies_to", "po_items", "share_of_items", "share_of_value"]],
        {
            "deviation_label": "",
            "applies_to": "",
            "po_items": "{:,}",
            "share_of_items": "{:.1%}",
            "share_of_value": "{:.1%}",
        },
    ).replace("<th>deviation_label</th>", "<th>Deviation</th>")
    imgs = "".join(
        f'<figure><img src="img/{p.name}" alt="Reference model {p.stem}" loading="lazy">'
        f"<figcaption>{p.stem.replace('reference_', '').replace('_', ' ')}</figcaption></figure>"
        for p in sorted((ROOT / "docs" / "img").glob("reference_*.png"))
    )
    sections.append(f"""
<section id="conformance">
  <h2>Conformance (RQ1)</h2>
  <p>Each item category has its own target process, set by SAP fields <code>EKPO-WEPOS</code>, <code>WEBRE</code> and
  <code>PSTYP</code>. {conf["fit_rate"]:.1%} of items fit their reference model; what breaks conformance is rework inside the right structure.</p>
  {chart(fig)}
  <h3>Deviation rules (mature cohort)</h3>{dev_tbl}
  <p class="muted">Three category rules never fire because SAP itself enforces them; they stay as guardrails.</p>
  <h3>Reference models</h3><div class="gallery">{imgs}</div>
</section>""")

    # ---- cost of deviation
    def forest(outcome: str, title: str) -> str:
        e = eff[eff.outcome == outcome].sort_values("excess")
        sig = e.p_value < 0.05
        f = go.Figure(
            go.Scatter(
                x=e.excess,
                y=e.deviation_label,
                mode="markers",
                marker=dict(size=11, color=[BLUE if s else GRAY for s in sig], line=dict(width=2, color="white")),
                error_x=dict(
                    type="data",
                    symmetric=False,
                    array=e.ci_high - e.excess,
                    arrayminus=e.excess - e.ci_low,
                    color="#a3a29d",
                    thickness=2,
                    width=0,
                ),
                customdata=e[["items_with_deviation", "p_value"]],
                hovertemplate="%{y}<br>%{x:+.2f} (95% CI shown)<br>%{customdata[0]:,} items · p = %{customdata[1]:.3f}<extra></extra>",
            )
        )
        f.add_vline(x=0, line_color="#52514e", line_width=1)
        layout(f, 300, title=dict(text=title, x=0, font=dict(size=14)))
        return chart(f)

    sections.append(f"""
<section id="cost">
  <h2>Cost of each deviation (RQ2)</h2>
  <p>Fixed-effect OLS per item (item category, spend area, PO month, value quintile, vendor size), vendor-clustered
  95% confidence intervals; grey = not significant. Coarsened exact matching agrees within about ±0.5 touches.</p>
  <div class="grid2">{forest("n_manual_touches", "Extra manual touches per item")}{forest("cycle_days", "Extra days end to end")}</div>
  <p>Reversals and price changes after the invoice cost most per item; payment blocks are cheap per item but hit
  17% of items, so they are the biggest cost in total. Paying before goods receipt and raising the PO after the
  invoice skip steps: they are control risks, valued as spend exposed, never as savings.</p>
</section>""")

    # ---- early warning
    cf = go.Figure()
    cf.add_bar(
        x=cal.risk_decile,
        y=cal.observed,
        name="Observed rework rate",
        marker_color=BLUE,
        hovertemplate="decile %{x}: %{y:.1%}<extra></extra>",
    )
    cf.add_scatter(
        x=cal.risk_decile,
        y=cal.predicted,
        name="Predicted",
        mode="lines+markers",
        line=dict(color=ORANGE, width=2),
        marker=dict(size=8),
        hovertemplate="decile %{x}: %{y:.1%}<extra></extra>",
    )
    layout(cf, 320, title=dict(text="Calibration by risk decile (10 = highest)", x=0, font=dict(size=14)))
    cf.update_yaxes(tickformat=".0%")
    cf.update_xaxes(dtick=1)
    names = {
        "hist_rate_vendor_id": "Vendor's rework track record",
        "hist_rate_created_by": "Creator's rework track record",
        "items_in_po": "Items in the PO",
        "sub_spend_area": "Sub spend area",
        "item_type": "Item type",
        "hist_items_created_by": "Creator's volume",
        "hist_items_vendor_id": "Vendor's volume",
        "log_value": "Item value",
        "hist_rate_material_group": "Material group track record",
    }
    d8 = drv.head(8).iloc[::-1]
    df_ = go.Figure(
        go.Bar(
            x=d8.share,
            y=[names.get(f, f) for f in d8.feature],
            orientation="h",
            marker_color=BLUE,
            hovertemplate="%{y}: %{x:.0%}<extra></extra>",
        )
    )
    layout(df_, 320, title=dict(text="What drives the score (share of mean |SHAP|)", x=0, font=dict(size=14)))
    df_.update_xaxes(tickformat=".0%")
    mt = table(
        mm,
        {
            "model": "",
            "pr_auc": "{:.3f}",
            "roc_auc": "{:.3f}",
            "precision_at_10pct": "{:.1%}",
            "lift_at_10pct": "{:.2f}×",
        },
    )
    for a, b in (
        ("<th>model</th>", "<th>Model</th>"),
        ("<th>pr_auc</th>", "<th>PR-AUC</th>"),
        ("<th>roc_auc</th>", "<th>ROC-AUC</th>"),
        ("<th>precision_at_10pct</th>", "<th>Precision @10%</th>"),
        ("<th>lift_at_10pct</th>", "<th>Lift @10%</th>"),
    ):
        mt = mt.replace(a, b)
    sections.append(f"""
<section id="early-warning">
  <h2>Early warning at PO creation (RQ3, RQ4)</h2>
  <p>Label: rework within {ew["horizon_days"]} days. Test: POs from {ew["test_window_start"]}. The deployed design is
  refitted every month on items whose outcome is already known that day, so nothing from the future leaks in.</p>
  {mt}
  <p class="note">Honest reading: the signal at PO creation is modest overall (ROC-AUC {mm.roc_auc.iloc[-1]:.2f}), but the
  top 10% of flagged items carry rework {lift:.2f}× as often as average: enough for a buyer's review queue, not for blocking.</p>
  <div class="grid2">{chart(cf)}{chart(df_)}</div>
</section>""")

    # ---- vendors
    lf = go.Figure(
        go.Scatter(
            x=conc.vendor_rank / conc.vendors,
            y=conc.cum_share,
            mode="lines",
            line=dict(color=BLUE, width=2),
            hovertemplate="top %{x:.1%} of vendors → %{y:.1%} of rework<extra></extra>",
        )
    )
    lf.add_annotation(x=0.05, y=top5, text=f"5% of vendors → {top5:.0%}", showarrow=True, arrowhead=0, ax=70, ay=30)
    layout(lf, 320, title=dict(text="Cumulative share of rework items by vendor", x=0, font=dict(size=14)))
    lf.update_xaxes(tickformat=".0%")
    lf.update_yaxes(tickformat=".0%", range=[0, 1.02])
    vm["po_created_month"] = pd.to_datetime(vm.po_created_month)
    cc = go.Figure()
    vendors = list(vm.vendor_id.unique())
    for i, v in enumerate(vendors):
        one = vm[vm.vendor_id == v]
        cc.add_scatter(
            x=one.po_created_month,
            y=one.rework_rate,
            mode="lines+markers",
            name=v,
            visible=(i == 0),
            line=dict(color=BLUE, width=2),
            marker=dict(size=8, line=dict(width=2, color="white")),
            customdata=one.po_items,
            hovertemplate="%{x|%b %Y}: %{y:.0%} of %{customdata:,} items<extra></extra>",
        )
    cc.update_layout(
        updatemenus=[
            dict(
                type="dropdown",
                x=0,
                y=1.18,
                xanchor="left",
                buttons=[
                    dict(
                        label=f"Vendor {v}", method="update", args=[{"visible": [j == i for j in range(len(vendors))]}]
                    )
                    for i, v in enumerate(vendors)
                ],
            )
        ]
    )
    layout(cc, 340, showlegend=False)
    cc.update_yaxes(tickformat=".0%", range=[0, 1.02])
    sections.append(f"""
<section id="vendors">
  <h2>Vendors</h2>
  <div class="grid2">{chart(lf)}{chart(cc)}</div>
  <p>Control chart of the 10 vendors with most rework. Vendor 0000100105 jumps from under 10% to about 90% rework
  in June-July 2018: a monthly KPI alert catches that within weeks, a model trained once in spring cannot.
  The last month is too recent to judge.</p>
</section>""")

    # ---- monthly KPIs
    k["po_created_month"] = pd.to_datetime(k.po_created_month)
    small = []
    for col, title, pct in (
        ("conformance_rate", "Conformance rate", True),
        ("first_time_right_rate", "First-time-right rate", True),
        ("avg_manual_touches", "Manual touches per item", False),
        ("median_cycle_days", "Median cycle days (closed items)", False),
    ):
        f = go.Figure()
        for cat, color in CAT_COLORS.items():
            d = k[k.item_category == cat]
            if d.empty or cat == "2-way match":
                continue
            f.add_scatter(
                x=d.po_created_month,
                y=d[col],
                name=cat,
                mode="lines+markers",
                line=dict(color=color, width=2),
                marker=dict(size=6),
                hovertemplate="%{x|%b %Y}: %{y:" + (".1%" if pct else ".1f") + "}<extra>" + cat + "</extra>",
            )
        layout(f, 280, title=dict(text=title, x=0, font=dict(size=14)))
        if pct:
            f.update_yaxes(tickformat=".0%")
        small.append(chart(f))
    sections.append(f"""
<section id="monthly">
  <h2>Monthly KPIs by PO creation month</h2>
  <div class="grid2">{"".join(small)}</div>
  <p class="muted">2-way match items are omitted (157 items in total). Recent months are right-censored for cycle times.</p>
</section>""")

    page = TEMPLATE.format(
        sections="".join(sections),
        repo=REPO,
        items=f"{ds['po_items_in_scope']:,}",
        vendors=f"{ds['vendors']:,}",
        first=ds["first_po"],
        last=ds["last_po"],
    )
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "img").mkdir(parents=True)
    for p in (ROOT / "docs" / "img").glob("reference_*.png"):
        shutil.copy(p, OUT / "img" / p.name)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    return OUT / "index.html"


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProcurePulse</title>
<meta name="description" content="SAP purchase-to-pay process mining on a real event log: cost of deviation, drivers, interventions, early warning.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#fcfcfb; --surface:#ffffff; --line:#e7e6e1; --ink:#0b0b0b; --ink2:#52514e; --blue:#2a78d6; --soft:#eef4fc; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 Inter, system-ui, sans-serif; }}
header {{ background:var(--surface); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 16px; }}
header .wrap {{ display:flex; gap:20px; align-items:center; height:56px; overflow-x:auto; white-space:nowrap; }}
header b {{ font-size:17px; }} header a {{ color:var(--ink2); text-decoration:none; font-size:14px; }}
header a:hover {{ color:var(--blue); }}
.hero {{ padding:40px 0 8px; }} .hero h1 {{ font-size:clamp(26px,4vw,40px); line-height:1.15; margin:0 0 12px; }}
.hero p {{ color:var(--ink2); max-width:820px; margin:0; }}
section {{ padding:28px 0; border-bottom:1px solid var(--line); }} h2 {{ font-size:26px; margin:0 0 12px; }}
h3 {{ font-size:18px; margin:28px 0 12px; }} h4 {{ margin:0 0 4px; font-size:16px; }}
.muted {{ color:var(--ink2); font-size:14px; }} code {{ font-size:13px; background:#f1f0ed; padding:1px 4px; border-radius:4px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
.kpis.two {{ grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); }}
.kpi {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:16px; display:flex; flex-direction:column; gap:4px; }}
.kpi.accent {{ background:var(--soft); border-color:#cfe0f6; }}
.label {{ font-size:14px; color:var(--ink2); }} .big {{ font-size:30px; font-weight:700; line-height:1.1; }}
.slider {{ margin:16px 0 4px; display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; }}
.slider input {{ width:min(320px,100%); accent-color:var(--blue); }}
.iv {{ display:grid; grid-template-columns:40px 1fr repeat(3,minmax(110px,150px)); gap:12px; align-items:center;
       background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:10px; }}
.rank {{ width:32px; height:32px; border-radius:50%; background:var(--blue); color:#fff; display:grid; place-items:center; font-weight:700; }}
.ivnum {{ display:flex; flex-direction:column; }} .ivnum .big {{ font-size:24px; }}
.grid2 {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; }}
@media (max-width:980px) {{ .grid2 {{ grid-template-columns:minmax(0,1fr); }} }}
.chart {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:8px; min-width:0; }}
.tbl {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }} th,td {{ padding:8px 12px; border-bottom:1px solid var(--line); text-align:left; }}
th {{ color:var(--ink2); font-weight:600; background:#f7f6f3; }} td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
tr:last-child td {{ border-bottom:0; }}
.note {{ background:var(--soft); border-left:3px solid var(--blue); padding:10px 14px; border-radius:6px; }}
.gallery {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr)); gap:12px; }}
figure {{ margin:0; background:#fff; border:1px solid var(--line); border-radius:10px; padding:8px; }}
figure img {{ width:100%; height:auto; }} figcaption {{ font-size:13px; color:var(--ink2); text-align:center; }}
footer {{ padding:28px 0 48px; color:var(--ink2); font-size:14px; }} a {{ color:var(--blue); }}
@media (max-width:760px) {{ .iv {{ grid-template-columns:32px 1fr; }} .ivnum {{ grid-column:2; flex-direction:row; gap:8px; align-items:baseline; }} }}
</style></head>
<body>
<header><div class="wrap"><b>ProcurePulse</b><a href="#answer">Answer</a><a href="#conformance">Conformance</a>
<a href="#cost">Cost</a><a href="#early-warning">Early warning</a><a href="#vendors">Vendors</a><a href="#monthly">Monthly</a>
<a href="{repo}">Code ↗</a></div></header>
<main class="wrap">
<div class="hero"><h1>What does deviating from the target purchase-to-pay process cost, what drives it, and which three fixes recover the most?</h1>
<p>Process mining on a real SAP purchase-to-pay log (BPI Challenge 2019): {items} PO items, {vendors} vendors, POs from {first} to {last}.
SAP tables rebuilt from the log, dbt on DuckDB and Snowflake, PM4Py, fixed-effect regression, LightGBM.</p></div>
{sections}
</main>
<footer class="wrap">Data: BPI Challenge 2019, van Dongen (2019), 4TU.ResearchData, CC BY 4.0. The SAP tables are rebuilt from that
log, not extracted from a live SAP system. Method, SQL and tests: <a href="{repo}">github.com/Parsaka/procurepulse</a>.</footer>
<script>
(function () {{
  var input = document.getElementById('rate');
  function fmt(x) {{ return x >= 1e6 ? '€' + (x / 1e6).toFixed(2) + ' M' : '€' + Math.round(x / 1e3).toLocaleString('en') + ' k'; }}
  function update() {{
    var r = +input.value;
    document.querySelectorAll('.rate').forEach(function (el) {{ el.textContent = '€' + r; }});
    document.querySelectorAll('.eur[data-touches]').forEach(function (el) {{ el.textContent = fmt(+el.dataset.touches * r); }});
  }}
  input.addEventListener('input', update); update();
  window.addEventListener('load', function () {{
    if (window.Plotly) document.querySelectorAll('.js-plotly-plot').forEach(function (g) {{ Plotly.Plots.resize(g); }});
  }});
}})();
</script>
</body></html>
"""

if __name__ == "__main__":
    print(build())
