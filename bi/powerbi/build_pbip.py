"""Generate the Power BI project (PBIP: TMDL semantic model + PBIR report) from code.

    python bi/powerbi/build_pbip.py [--data-folder C:\\path\\to\\procurepulse\\data\\bi\\]

Writes bi/powerbi/ProcurePulse/ProcurePulse.pbip. Open it in Power BI Desktop, press Refresh,
then File > Save as > ProcurePulse.pbix. Column types come from the Parquet schemas in data/bi,
measures from measures.dax (same definitions), so the report cannot drift from the dbt KPIs.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data" / "bi"
OUT = HERE / "ProcurePulse"
NAME = "ProcurePulse"
NS = uuid.UUID("6f1c3c1e-6b0e-4a54-9a59-6c0f2f6f7a10")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item"

BLUE, ORANGE, AQUA, YELLOW, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a8984"

TABLES = [
    "fct_po_item",
    "fct_event",
    "early_warning_scores",
    "dim_vendor",
    "dim_material_group",
    "dim_company_code",
    "dim_date",
    "dim_activity",
    "dim_user",
    "deviation_effects",
    "intervention_value",
]

RELATIONSHIPS = [  # many -> one
    ("fct_po_item", "vendor_id", "dim_vendor", "vendor_id"),
    ("fct_po_item", "material_group", "dim_material_group", "material_group"),
    ("fct_po_item", "company_code", "dim_company_code", "company_code"),
    ("fct_po_item", "po_created_month", "dim_date", "date_day"),
    ("fct_event", "case_key", "fct_po_item", "case_key"),
    ("fct_event", "activity", "dim_activity", "activity"),
    ("fct_event", "user_name", "dim_user", "user_name"),
    ("early_warning_scores", "case_key", "fct_po_item", "case_key"),
]

# Measures: name -> (DAX, format string). Mirrors measures.dax; the "(Mature Closed)" variants
# reproduce the headline numbers in docs/findings.md (items whose outcome is final).
SCOPE = "fct_po_item[is_mature_cohort] = TRUE (), fct_po_item[is_closed] = TRUE ()"
REWORK = (
    "fct_po_item[dev_price_change_after_invoice] || fct_po_item[dev_quantity_change_after_gr]"
    " || fct_po_item[dev_payment_block] || fct_po_item[dev_reversal]"
)
EUR_M = "€#,0"  # a literal " M" here doubles up with the auto units on chart axes; cards scale in card()
MEASURES: dict[str, tuple[str, str]] = {
    "PO Items": ("COUNTROWS ( fct_po_item )", "#,0"),
    "PO Value EUR": ("SUM ( fct_po_item[net_value_eur] )", "€#,0"),
    "Conformance Rate": (
        "DIVIDE ( CALCULATE ( [PO Items], fct_po_item[has_deviation] = FALSE () ), [PO Items] )",
        "0.0%",
    ),
    "Conformance Rate (Mature Closed)": (f"CALCULATE ( [Conformance Rate], {SCOPE} )", "0.0%"),
    "Deviating Value Share": (
        "DIVIDE ( CALCULATE ( [PO Value EUR], fct_po_item[has_deviation] = TRUE () ), [PO Value EUR] )",
        "0.0%",
    ),
    "First Time Right Rate": (
        "DIVIDE ( CALCULATE ( [PO Items], fct_po_item[n_manual_rework_touches] = 0 ), [PO Items] )",
        "0.0%",
    ),
    "Rework Items": (f"CALCULATE ( [PO Items], FILTER ( fct_po_item, {REWORK} ) )", "#,0"),
    "Rework Rate": ("DIVIDE ( [Rework Items], [PO Items] )", "0.0%"),
    "Rework Rate (Mature Closed)": (f"CALCULATE ( [Rework Rate], {SCOPE} )", "0.0%"),
    "PO After Invoice Rate": (
        "DIVIDE ( CALCULATE ( [PO Items], fct_po_item[dev_po_after_invoice] = TRUE () ), [PO Items] )",
        "0.0%",
    ),
    "Payment Block Rate": (
        "DIVIDE ( CALCULATE ( [PO Items], fct_po_item[dev_payment_block] = TRUE () ), [PO Items] )",
        "0.0%",
    ),
    "Manual Touches": ("SUM ( fct_po_item[n_manual_touches] )", "#,0"),
    "Manual Touches per Item": ("DIVIDE ( [Manual Touches], [PO Items] )", "0.00"),
    "Automation Rate": ("DIVIDE ( SUM ( fct_po_item[n_batch_events] ), SUM ( fct_po_item[n_events] ) )", "0.0%"),
    "Median Cycle Days": (
        "CALCULATE ( MEDIAN ( fct_po_item[cycle_days] ), fct_po_item[is_closed] = TRUE () )",
        "0.0",
    ),
    "Median Invoice to Clear Days": ("MEDIAN ( fct_po_item[invoice_to_clear_days] )", "0.0"),
    "Closed Rate": (
        "DIVIDE ( CALCULATE ( [PO Items], fct_po_item[is_closed] = TRUE () ), [PO Items] )",
        "0.0%",
    ),
    "Touch Cost Value": ("SELECTEDVALUE ( 'Touch Cost'[Touch Cost], 15 )", "€0"),
    "Excess Touches per Year": (
        'CALCULATE ( SUM ( intervention_value[touches_saved_per_year] ), intervention_value[family] = "rework" )',
        "#,0",
    ),
    "Cost of Rework EUR per Year": ("[Excess Touches per Year] * [Touch Cost Value]", EUR_M),
    "Intervention Value EUR per Year": (
        'CALCULATE ( SUM ( intervention_value[touches_saved_per_year] ), intervention_value[family] = "rework" )'
        " * [Touch Cost Value]",
        EUR_M,
    ),
    "Control Gap Exposure EUR per Year": (
        'CALCULATE ( SUM ( intervention_value[exposed_value_eur_per_year] ), intervention_value[family] = "control" )',
        EUR_M,
    ),
    "Scored Items": ("COUNTROWS ( early_warning_scores )", "#,0"),
    "Observed Rework Rate (Scored)": ("AVERAGE ( early_warning_scores[label] )", "0.0%"),
    "Average Risk Score": ("AVERAGE ( early_warning_scores[risk_score] )", "0.0%"),
    "Top Decile Lift": (
        "DIVIDE ( CALCULATE ( AVERAGE ( early_warning_scores[label] ), early_warning_scores[risk_decile] = 10 ),"
        " CALCULATE ( AVERAGE ( early_warning_scores[label] ), REMOVEFILTERS ( early_warning_scores[risk_decile] ) ) )",
        '0.00"×"',
    ),
    "Vendor Rank by Rework": (
        "IF ( HASONEVALUE ( dim_vendor[vendor_id] ),"
        " RANKX ( ALL ( dim_vendor[vendor_id] ), [Rework Items], , DESC, DENSE ) )",
        "0",
    ),
    "Share of Rework Items": (
        "DIVIDE ( [Rework Items], CALCULATE ( [Rework Items], ALL ( dim_vendor ) ) )",
        "0.0%",
    ),
    "Excess per Item": (
        "IF ( HASONEVALUE ( deviation_effects[outcome] ), SUM ( deviation_effects[excess] ) )",
        "0.00",
    ),
}


def gid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


def tmdl_str(value: str) -> str:
    """A TMDL value holding quotes must be quoted itself, with its quotes doubled."""
    return '"' + value.replace('"', '""') + '"' if '"' in value else value


def tmdl_type(t: pa.DataType) -> tuple[str, str | None, str]:
    """Return (dataType, formatString, summarizeBy)."""
    if pa.types.is_boolean(t):
        return "boolean", '"TRUE";"TRUE";"FALSE"', "none"
    if pa.types.is_integer(t):
        return "int64", "0", "sum"
    if pa.types.is_floating(t):
        return "double", "#,0.00", "sum"
    if pa.types.is_date(t):
        return "dateTime", "yyyy-mm-dd", "none"
    if pa.types.is_timestamp(t):
        return "dateTime", "yyyy-mm-dd hh:nn", "none"
    return "string", None, "none"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def wjson(path: Path, obj: dict) -> None:
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


KEYS = {c for r in RELATIONSHIPS for c in ((r[0], r[1]), (r[2], r[3]))}


def table_tmdl(name: str) -> str:
    schema = pq.read_schema(DATA / f"{name}.parquet")
    lines = [f"table {q(name)}", f"\tlineageTag: {gid('t', name)}", ""]
    for field in schema:
        dtype, fmt, summ = tmdl_type(field.type)
        if field.name.startswith("share_") or field.name.endswith("_rate"):
            fmt = "0.0%"
        if field.name in ("risk_decile", "stage_order", "year", "month", "quarter", "rank_in_family", "event_seq"):
            summ = "none"
        lines.append(f"\tcolumn {q(field.name)}")
        lines.append(f"\t\tdataType: {dtype}")
        if fmt:
            lines.append(f"\t\tformatString: {tmdl_str(fmt)}")
        if (name, field.name) in KEYS and name != "dim_date":
            lines.append("\t\tisHidden")
        if name == "dim_date" and field.name == "date_day":
            lines.append("\t\tisKey")
        lines.append(f"\t\tlineageTag: {gid('c', name, field.name)}")
        lines.append(f"\t\tsummarizeBy: {summ}")
        lines.append(f"\t\tsourceColumn: {field.name}")
        lines.append("")
        lines.append("\t\tannotation SummarizationSetBy = Automatic")
        lines.append("")
    lines += [
        f"\tpartition {q(name)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Parquet.Document(File.Contents(DataFolder & "{name}.parquet"))',
        "\t\t\t\tin",
        "\t\t\t\t    Source",
        "",
    ]
    if name == "dim_date":
        lines.insert(2, "\tdataCategory: Time")
    return "\n".join(lines) + "\n"


def measures_tmdl() -> str:
    lines = ["table KPIs", f"\tlineageTag: {gid('t', 'KPIs')}", ""]
    for m, (dax, fmt) in MEASURES.items():
        lines.append(f"\tmeasure {q(m)} = {dax}")
        lines.append(f"\t\tformatString: {tmdl_str(fmt)}")
        lines.append(f"\t\tlineageTag: {gid('m', m)}")
        lines.append("")
    lines += [
        "\tcolumn Value",
        "\t\tdataType: string",
        "\t\tisHidden",
        f"\t\tlineageTag: {gid('c', 'KPIs', 'Value')}",
        "\t\tsummarizeBy: none",
        "\t\tisNameInferred",
        "\t\tsourceColumn: [Value]",
        "",
        "\tpartition KPIs = calculated",
        "\t\tmode: import",
        "\t\tsource = {BLANK()}",
        "",
    ]
    return "\n".join(lines) + "\n"


def touch_cost_tmdl() -> str:
    return (
        "\n".join(
            [
                "table 'Touch Cost'",
                f"\tlineageTag: {gid('t', 'Touch Cost')}",
                "",
                "\tcolumn 'Touch Cost'",
                "\t\tdataType: int64",
                "\t\tformatString: €0",
                f"\t\tlineageTag: {gid('c', 'Touch Cost', 'Touch Cost')}",
                "\t\tsummarizeBy: none",
                "\t\tsourceColumn: [Value]",
                "",
                "\t\textendedProperty ParameterMetadata =",
                "\t\t\t\t{",
                '\t\t\t\t  "version": 0',
                "\t\t\t\t}",
                "",
                "\tpartition 'Touch Cost' = calculated",
                "\t\tmode: import",
                "\t\tsource = {5, 15, 30}",
                "",
            ]
        )
        + "\n"
    )


def semantic_model(data_folder: str) -> None:
    sm = OUT / f"{NAME}.SemanticModel"
    wjson(
        sm / "definition.pbism",
        {"$schema": f"{SCHEMA}/semanticModel/definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {}},
    )
    d = sm / "definition"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    refs = "\n".join(f"ref table {q(t)}" for t in [*TABLES, "KPIs", "Touch Cost"])
    write(
        d / "model.tmdl",
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tsourceQueryCulture: en-US\n\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        "\tannotation __PBI_TimeIntelligenceEnabled = 0\n\n"
        f"{refs}\n\nref cultureInfo en-US\n",
    )
    folder = data_folder.replace('"', '""')
    write(
        d / "expressions.tmdl",
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {gid('e', 'DataFolder')}\n\n\tannotation PBI_ResultType = Text\n",
    )
    rel = []
    for f_t, f_c, t_t, t_c in RELATIONSHIPS:
        rel += [
            f"relationship {gid('r', f_t, f_c, t_t)}",
            f"\tfromColumn: {q(f_t)}.{q(f_c)}",
            f"\ttoColumn: {q(t_t)}.{q(t_c)}",
            "",
        ]
    write(d / "relationships.tmdl", "\n".join(rel))
    write(d / "cultures" / "en-US.tmdl", "cultureInfo en-US\n")
    for t in TABLES:
        write(d / "tables" / f"{t}.tmdl", table_tmdl(t))
    write(d / "tables" / "KPIs.tmdl", measures_tmdl())
    write(d / "tables" / "Touch Cost.tmdl", touch_cost_tmdl())


# ---------------------------------------------------------------- report (PBIR)


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "KPIs"}}, "Property": prop}}


def proj(field: dict) -> dict:
    kind = "Measure" if "Measure" in field else "Column"
    ent = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    return {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}


def lit(s: str) -> dict:
    return {"expr": {"Literal": {"Value": s}}}


def title(text: str) -> dict:
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]}


class Page:
    def __init__(self, name: str, display: str, height: int = 720):
        self.name, self.display, self.height, self.visuals = name, display, height, []

    def add(
        self,
        vtype: str,
        x: int,
        y: int,
        w: int,
        h: int,
        buckets: dict[str, list[dict]],
        heading: str | None = None,
        objects: dict | None = None,
        sort: dict | None = None,
    ) -> None:
        vis: dict = {
            "visualType": vtype,
            "query": {"queryState": {b: {"projections": [proj(f) for f in fs]} for b, fs in buckets.items()}},
            "drillFilterOtherVisuals": True,
        }
        if sort:
            vis["query"]["sortDefinition"] = {"sort": [sort], "isDefaultSort": True}
        if objects:
            vis["objects"] = objects
        if heading:
            vis["visualContainerObjects"] = title(heading)
        n = len(self.visuals)
        self.visuals.append(
            {
                "$schema": f"{SCHEMA}/report/definition/visualContainer/2.0.0/schema.json",
                "name": f"{self.name}_v{n:02d}",
                "position": {"x": x, "y": y, "z": n * 1000, "width": w, "height": h, "tabOrder": n * 1000},
                "visual": vis,
            }
        )

    def text(self, x: int, y: int, w: int, h: int, content: str, size: int = 12, bold: bool = False) -> None:
        n = len(self.visuals)
        style = {"fontSize": f"{size}pt", "color": "#2b2a27"}
        if bold:
            style["fontWeight"] = "bold"
        para = {"textRuns": [{"value": content, "textStyle": style}]}
        self.visuals.append(
            {
                "$schema": f"{SCHEMA}/report/definition/visualContainer/2.0.0/schema.json",
                "name": f"{self.name}_v{n:02d}",
                "position": {"x": x, "y": y, "z": n * 1000, "width": w, "height": h, "tabOrder": n * 1000},
                "visual": {
                    "visualType": "textbox",
                    "objects": {"general": [{"properties": {"paragraphs": [para]}}]},
                    "drillFilterOtherVisuals": True,
                },
            }
        )


def slicer_default(entity: str, column: str, literal: str) -> dict:
    """Single-select list slicer with a preselected value (PBIR stores the selection as a filter)."""
    where = {
        "Condition": {
            "In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": column}}],
                "Values": [[{"Literal": {"Value": literal}}]],
            }
        }
    }
    flt = {"Version": 2, "From": [{"Name": "s", "Entity": entity, "Type": 0}], "Where": [where]}
    return {
        "data": [{"properties": {"mode": lit("'Basic'")}}],
        "selection": [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true")}}],
        "general": [{"properties": {"filter": {"filter": flt}}}],
    }


def card(p: Page, x: int, y: int, measure: str, heading: str) -> None:
    # The default "Auto" rounds €1.27 M to €1M: EUR in millions with 2 decimals, the rest unscaled
    props = {"labelDisplayUnits": lit("1D")}
    if MEASURES[measure][1] == EUR_M:
        props = {"labelDisplayUnits": lit("1000000D"), "labelPrecision": lit("2L")}
    labels = {"labels": [{"properties": props}]}
    p.add("card", x, y, 290, 120, {"Values": [mea(measure)]}, heading, objects=labels)


def desc(field: dict) -> dict:
    return {"field": field, "direction": "Descending"}


def pages() -> list[Page]:
    a = Page("answer", "Answer", 900)
    a.text(
        20,
        10,
        1240,
        50,
        "What does deviating from the target P2P process cost, and which three fixes recover the most?",
        16,
        True,
    )
    card(a, 20, 70, "Conformance Rate (Mature Closed)", "Items without any deviation")
    card(a, 330, 70, "Rework Items", "PO items with rework (whole log)")
    card(a, 640, 70, "Cost of Rework EUR per Year", "Cost of rework per year")
    card(a, 950, 70, "Control Gap Exposure EUR per Year", "Control-gap spend exposed per year")
    a.add(
        "slicer",
        20,
        205,
        300,
        160,
        {"Values": [col("Touch Cost", "Touch Cost")]},
        "Cost of one manual touch",
        objects=slicer_default("Touch Cost", "Touch Cost", "15L"),
    )
    a.text(
        340,
        215,
        920,
        110,
        "A manual touch is 10 to 20 minutes of a buyer or AP clerk: €5 / €15 / €30 = low / base / high case. "
        "Rework cost = excess touches per year × this rate. Control gaps are spend exposed to risk, not savings. "
        "Conformance is measured on closed items of the mature cohort, rework counts on the whole log.",
        11,
    )
    a.add(
        "clusteredBarChart",
        20,
        380,
        1240,
        270,
        {"Category": [col("intervention_value", "intervention")], "Y": [mea("Intervention Value EUR per Year")]},
        "Three interventions recover all of the rework effort (value per year)",
        sort=desc(mea("Intervention Value EUR per Year")),
    )
    a.add(
        "tableEx",
        20,
        660,
        1240,
        220,
        {
            "Values": [
                col("intervention_value", "intervention"),
                col("intervention_value", "family"),
                col("intervention_value", "owner"),
                col("intervention_value", "share_of_rework_effort"),
            ]
        },
        "Interventions and owners",
    )

    pr = Page("process", "Process")
    pr.add(
        "lineChart",
        20,
        20,
        1240,
        330,
        {
            "Category": [col("dim_date", "month_start")],
            "Y": [mea("Conformance Rate")],
            "Series": [col("fct_po_item", "item_category")],
        },
        "Conformance rate by PO month and item category",
    )
    pr.add(
        "lineChart",
        20,
        370,
        610,
        280,
        {"Category": [col("dim_date", "month_start")], "Y": [mea("First Time Right Rate")]},
        "First-time-right rate by PO month",
    )
    pr.add(
        "clusteredBarChart",
        650,
        370,
        610,
        280,
        {"Category": [col("fct_po_item", "spend_area")], "Y": [mea("Payment Block Rate")]},
        "Payment block rate by spend area",
        sort=desc(mea("Payment Block Rate")),
    )
    pr.text(
        20,
        660,
        1240,
        50,
        "2-way match items are rare (157 in the mature cohort), so their monthly rate jumps. "
        "January 2019 is a partial month whose items have not finished; read it as incomplete.",
        10,
    )

    dc = Page("deviation_cost", "Deviation cost")
    dc.text(
        20,
        10,
        1240,
        50,
        "Fixed-effect OLS per item with vendor-clustered 95% CIs. Filter each table to one outcome; never put touches and days on one axis.",
        11,
    )
    cols = [
        "deviation_label",
        "outcome",
        "excess",
        "ci_low",
        "ci_high",
        "p_value",
        "items_with_deviation",
        "cem_excess",
    ]
    dc.add(
        "tableEx",
        20,
        70,
        1240,
        330,
        {"Values": [col("deviation_effects", c) for c in cols]},
        "Excess effect per deviation (selected outcome)",
    )
    dc.add(
        "slicer",
        20,
        420,
        300,
        160,
        {"Values": [col("deviation_effects", "outcome")]},
        "Outcome",
        objects=slicer_default("deviation_effects", "outcome", "'n_manual_touches'"),
    )
    dc.add(
        "clusteredBarChart",
        340,
        420,
        920,
        290,
        {"Category": [col("deviation_effects", "deviation_label")], "Y": [mea("Excess per Item")]},
        "Excess per item for the selected outcome",
    )

    v = Page("vendors", "Vendors")
    v.add(
        "tableEx",
        20,
        20,
        700,
        680,
        {
            "Values": [
                col("dim_vendor", "vendor_id"),
                mea("PO Items"),
                mea("Rework Items"),
                mea("Rework Rate"),
                mea("Payment Block Rate"),
                mea("Share of Rework Items"),
            ]
        },
        "Vendors by rework",
        sort=desc(mea("Rework Items")),
    )
    v.add(
        "slicer",
        740,
        20,
        520,
        90,
        {"Values": [col("dim_vendor", "vendor_id")]},
        "Vendor (control chart)",
        objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]},
    )
    v.add(
        "lineChart",
        740,
        120,
        520,
        500,
        {"Category": [col("dim_date", "month_start")], "Y": [mea("Rework Rate")]},
        "Rework rate by PO month",
    )
    v.text(
        740,
        630,
        520,
        70,
        "Pick vendor 0000100105 to see the drift: under 10% rework until June 2018, 67 to 93% from July. "
        "The last months fall because recent POs had less time to show rework.",
        10,
    )

    ew = Page("early_warning", "Early warning")
    card(ew, 20, 20, "Top Decile Lift", "Top-decile lift")
    card(ew, 330, 20, "Scored Items", "Scored PO items (test window)")
    card(ew, 640, 20, "Observed Rework Rate (Scored)", "Base rework rate")
    ew.add(
        "clusteredColumnChart",
        20,
        160,
        610,
        540,
        {
            "Category": [col("early_warning_scores", "risk_decile")],
            "Y": [mea("Observed Rework Rate (Scored)"), mea("Average Risk Score")],
        },
        "Calibration: observed vs predicted by risk decile",
    )
    ew.add(
        "tableEx",
        650,
        160,
        610,
        540,
        {
            "Values": [
                col("early_warning_scores", "case_key"),
                col("early_warning_scores", "risk_decile"),
                col("early_warning_scores", "risk_score"),
                col("early_warning_scores", "top_reason"),
                col("early_warning_scores", "label"),
            ]
        },
        "Items to review (sort by risk score)",
        sort=desc(col("early_warning_scores", "risk_score")),
    )
    return [a, pr, dc, v, ew]


THEME = {
    "name": "ProcurePulse",
    "dataColors": [BLUE, ORANGE, AQUA, YELLOW, GRAY, "#6a5acd", "#c0392b", "#16a085"],
    "background": "#FFFFFF",
    "foreground": "#2b2a27",
    "tableAccent": BLUE,
}


def report() -> None:
    rp = OUT / f"{NAME}.Report"
    wjson(
        rp / "definition.pbir",
        {
            "$schema": f"{SCHEMA}/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
        },
    )
    d = rp / "definition"
    wjson(
        d / "version.json",
        {"$schema": f"{SCHEMA}/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"},
    )
    wjson(rp / "StaticResources" / "RegisteredResources" / "ProcurePulse.json", THEME)
    wjson(
        d / "report.json",
        {
            "$schema": f"{SCHEMA}/report/definition/report/3.0.0/schema.json",
            "themeCollection": {
                "baseTheme": {
                    "name": "CY24SU10",
                    "reportVersionAtImport": {"visual": "2.0.0", "report": "3.0.0", "page": "2.0.0"},
                    "type": "SharedResources",
                },
                "customTheme": {
                    "name": "ProcurePulse.json",
                    "reportVersionAtImport": {"visual": "2.0.0", "report": "3.0.0", "page": "2.0.0"},
                    "type": "RegisteredResources",
                },
            },
            "resourcePackages": [
                {
                    "name": "RegisteredResources",
                    "type": "RegisteredResources",
                    "items": [{"name": "ProcurePulse.json", "path": "ProcurePulse.json", "type": "CustomTheme"}],
                }
            ],
        },
    )
    ps = pages()
    wjson(
        d / "pages" / "pages.json",
        {
            "$schema": f"{SCHEMA}/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [p.name for p in ps],
            "activePageName": ps[0].name,
        },
    )
    for p in ps:
        wjson(
            d / "pages" / p.name / "page.json",
            {
                "$schema": f"{SCHEMA}/report/definition/page/2.0.0/schema.json",
                "name": p.name,
                "displayName": p.display,
                "displayOption": "FitToPage",
                "height": p.height,
                "width": 1280,
            },
        )
        for vis in p.visuals:
            wjson(d / "pages" / p.name / "visuals" / vis["name"] / "visual.json", vis)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-folder",
        default="C:\\procurepulse\\data\\bi\\",
        help="absolute path to data/bi with a trailing backslash (the DataFolder parameter)",
    )
    args = ap.parse_args()
    if OUT.exists():
        shutil.rmtree(OUT)
    semantic_model(args.data_folder)
    report()
    wjson(
        OUT / f"{NAME}.pbip",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    write(OUT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    print(OUT / f"{NAME}.pbip")


if __name__ == "__main__":
    main()
