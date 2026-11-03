"""Simulate an SAP ECC extract for purchase-to-pay from the BPI Challenge 2019 event log.

The BPI Challenge 2019 log was itself exported from an SAP system. This script
reverses that export: it turns every event back into the SAP table row that
would have produced it, with SAP field names and SAP formats (CHAR keys with
leading zeros, DATS 'YYYYMMDD', TIMS 'HHMMSS', 'X'/'' flags). The dbt project
then rebuilds the event log from these tables, the way a process mining
connector (for example Celonis' SAP P2P connector) does in a real company.

Output: one Parquet folder per SAP table under <out>/<TABLE>/, partitioned by
extraction month (load_month=YYYY-MM), like monthly delta loads from an
extractor. Master data (LFA1, T001, T023T) is a full load.

Every event lands in exactly one table row. The audit file
<out>/_AUDIT_EVENT_COUNTS.parquet holds per-activity counts of the source log
so dbt can prove that the reconstruction is lossless.

Simplifications (documented in docs/sap_data_model.md):
  * EKBE holds goods-receipt history only (VGABE '1'); invoices live in RBKP/RSEG.
  * Invoice payment blocks are change documents keyed by PO item, not by invoice.
  * Vendor-side events (vendor creates invoice / debit memo) arrive as inbound
    IDocs (EDIDC, message type INVOIC), as with EDI vendors.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import duckdb

# Activity -> (target table, change-document field or code). Order matters only for readability.
PO_CHANGE_FIELDS = {
    "Change Price": ("EKPO", "NETPR"),
    "Change Quantity": ("EKPO", "MENGE"),
    "Change Delivery Indicator": ("EKPO", "ELIKZ"),
    "Change Final Invoice Indicator": ("EKPO", "EREKZ"),
    "Change Storage Location": ("EKPO", "LGORT"),
    "Change Rejection Indicator": ("EKPO", "ABSKZ"),
    "Delete Purchase Order Item": ("EKPO", "LOEKZ"),
    "Block Purchase Order Item": ("EKPO", "LOEKZ"),
    "Reactivate Purchase Order Item": ("EKPO", "LOEKZ"),
    "Change Currency": ("EKKO", "WAERS"),
    "Change Approval for Purchase Order": ("EKKO", "FRGKE"),
    "Change payment term": ("EKKO", "ZTERM"),
    "Change Purchasing Group": ("EKKO", "EKGRP"),
    "Release Purchase Order": ("EKKO", "FRGZU"),
    "Release Purchase Requisition": ("EBAN", "FRGZU"),
}
LOEKZ_VALUE = {
    "Delete Purchase Order Item": "L",
    "Block Purchase Order Item": "S",
    "Reactivate Purchase Order Item": "",
}
INVOICE_BLOCK = {"Set Payment Block": "R", "Remove Payment Block": ""}
INVOICE_DOCS = {
    # activity: (VGART, TBTKZ, reversal flag)
    "Record Invoice Receipt": ("RD", "", False),
    "Cancel Invoice Receipt": ("RD", "", True),
    "Record Subsequent Invoice": ("RD", "X", False),
    "Cancel Subsequent Invoice": ("RD", "X", True),
}
GR_DOCS = {"Record Goods Receipt": ("101", "S"), "Cancel Goods Receipt": ("102", "H")}
IDOCS = {"Vendor creates invoice": "INVOIC01", "Vendor creates debit memo": "INVOIC02"}
CONFIRMATIONS = {"Receive Order Confirmation": "1", "Update Order Confirmation": "2"}

ITEM_TYPE_TO_PSTYP = {
    "Standard": "0",
    "Limit": "1",
    "Consignment": "2",
    "Subcontracting": "3",
    "Third-party": "5",
    "Service": "9",
}
DOC_TYPE_TO_BSART = {"Standard PO": "NB", "Framework order": "FO", "EC Purchase order": "EC"}


def build(con: duckdb.DuckDBPyConnection, src: Path) -> None:
    """Create normalised helper views over the raw log."""
    con.execute(f"create or replace view raw as select * from read_parquet('{src.as_posix()}')")
    cols = {r[0] for r in con.execute("describe raw").fetchall()}
    need = {
        "case:concept:name", "case:Purchasing Document", "case:Item", "case:Item Type",
        "case:GR-Based Inv. Verif.", "case:Goods Receipt", "case:Company", "case:Spend area text",
        "case:Sub spend area text", "case:Spend classification text", "case:Vendor", "case:Name",
        "case:Document Type", "case:Item Category", "case:Source",
        "concept:name", "User", "time:timestamp", "Cumulative net worth (EUR)",
    }
    missing = need - cols
    if missing:
        raise SystemExit(f"Raw log misses columns: {sorted(missing)}")

    # One row per event with a stable sequence number inside the case.
    con.execute(
        """
        create or replace table ev as
        with base as (
            select
                "case:concept:name"                    as case_id,
                "case:Purchasing Document"             as po,
                "case:Item"                            as item,
                "concept:name"                         as activity,
                "User"                                 as resource,
                -- Timestamps in the log are UTC ('Z'); SAP-style DATS/TIMS keep that clock
                strptime(substr("time:timestamp", 1, 19), '%Y-%m-%dT%H:%M:%S') as ts,
                "Cumulative net worth (EUR)"           as net_worth
            from raw
        )
        select *,
               row_number() over (partition by case_id order by ts, activity) as seq
        from base
        """
    )
    con.execute(
        """
        create or replace table cases as
        select distinct
            "case:concept:name"           as case_id,
            "case:Purchasing Document"    as po,
            "case:Item"                   as item,
            "case:Item Type"              as item_type,
            "case:GR-Based Inv. Verif."   as gr_based_iv,
            "case:Goods Receipt"          as goods_receipt,
            "case:Company"                as company,
            "case:Spend area text"        as spend_area,
            "case:Sub spend area text"    as sub_spend_area,
            "case:Spend classification text" as spend_class,
            "case:Vendor"                 as vendor,
            "case:Name"                   as vendor_name,
            "case:Document Type"          as doc_type,
            "case:Item Category"          as item_category,
            "case:Source"                 as source_system
        from raw
        """
    )
    dup = con.execute("select count(*) - count(distinct case_id) from cases").fetchone()[0]
    if dup:
        raise SystemExit(f"{dup} cases have inconsistent case attributes")


def sap_tables(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Return SQL per SAP table. Keys use SAP CHAR formats with leading zeros."""
    # Master-data key maps (stable, sorted -> deterministic numbering)
    con.execute(
        """
        create or replace table map_vendor as
        select vendor, any_value(vendor_name) as vendor_name,
               lpad(cast(100000 + row_number() over (order by vendor) as varchar), 10, '0') as lifnr
        from cases group by vendor
        """
    )
    con.execute(
        """
        create or replace table map_company as
        select company, 'C' || lpad(cast(row_number() over (order by company) as varchar), 3, '0') as bukrs
        from (select distinct company from cases)
        """
    )
    con.execute(
        """
        create or replace table map_matkl as
        select spend_area, sub_spend_area, spend_class,
               'MG' || lpad(cast(row_number() over (order by spend_area, sub_spend_area, spend_class) as varchar), 4, '0') as matkl
        from (select distinct spend_area, sub_spend_area, spend_class from cases)
        """
    )
    con.execute(
        """
        create or replace table map_user as
        select resource,
               case when resource is null or resource = 'NONE' then ''
                    else upper(replace(resource, '_', '')) end as usnam
        from (select distinct resource from ev)
        """
    )
    pstyp = " ".join(f"when '{k}' then '{v}'" for k, v in ITEM_TYPE_TO_PSTYP.items())
    bsart = " ".join(f"when '{k}' then '{v}'" for k, v in DOC_TYPE_TO_BSART.items())

    # Event enriched with SAP keys and SAP date/time strings
    con.execute(
        """
        create or replace table e as
        select ev.*,
               lpad(ev.po, 10, '0')                     as ebeln,
               lpad(ev.item, 5, '0')                    as ebelp,
               strftime(ev.ts, '%Y%m%d')                as dats,
               strftime(ev.ts, '%H%M%S')                as tims,
               strftime(ev.ts, '%Y-%m')                 as load_month,
               cast(year(ev.ts) as varchar)             as gjahr,
               mu.usnam
        from ev join map_user mu using (resource)
        """
    )

    def acts(names) -> str:
        return ", ".join("'" + n.replace("'", "''") + "'" for n in names)

    chg_cases = " ".join(
        f"when '{a}' then '{t}|{f}'" for a, (t, f) in PO_CHANGE_FIELDS.items()
    )
    loekz = " ".join(f"when '{a}' then '{v}'" for a, v in LOEKZ_VALUE.items())
    block = " ".join(f"when '{a}' then '{v}'" for a, v in INVOICE_BLOCK.items())
    inv_vgart = " ".join(f"when '{a}' then '{v[0]}'" for a, v in INVOICE_DOCS.items())
    inv_tbtkz = " ".join(f"when '{a}' then '{v[1]}'" for a, v in INVOICE_DOCS.items())
    inv_rev = " ".join(f"when '{a}' then {'true' if v[2] else 'false'}" for a, v in INVOICE_DOCS.items())
    gr_bwart = " ".join(f"when '{a}' then '{v[0]}'" for a, v in GR_DOCS.items())
    gr_shkzg = " ".join(f"when '{a}' then '{v[1]}'" for a, v in GR_DOCS.items())
    idoc = " ".join(f"when '{a}' then '{v}'" for a, v in IDOCS.items())
    conf = " ".join(f"when '{a}' then '{v}'" for a, v in CONFIRMATIONS.items())

    handled = (
        list(PO_CHANGE_FIELDS) + list(INVOICE_BLOCK) + list(INVOICE_DOCS) + list(GR_DOCS)
        + list(IDOCS) + list(CONFIRMATIONS)
        + ["Create Purchase Order Item", "Create Purchase Requisition Item",
           "Record Service Entry Sheet", "Clear Invoice"]
    )

    return {
        # ---------- master data (full loads) ----------
        "LFA1": """
            select lifnr as LIFNR, vendor_name as NAME1, 'NL' as LAND1, vendor as ZZ_SRC_VENDOR
            from map_vendor""",
        "T001": """
            select bukrs as BUKRS, company as BUTXT, 'EUR' as WAERS from map_company""",
        "T023T": """
            select matkl as MATKL, 'E' as SPRAS, sub_spend_area as WGBEZ,
                   spend_area as ZZ_SPEND_AREA, spend_class as ZZ_SPEND_CLASS
            from map_matkl""",
        # ---------- purchasing documents ----------
        # EKKO: one row per PO; creation = first 'Create Purchase Order Item' of the document
        "EKKO": f"""
            with first_create as (
                select ebeln, min(ts) as ts from e
                where activity = 'Create Purchase Order Item' group by ebeln
            ), hdr as (
                select lpad(c.po, 10, '0') as ebeln,
                       any_value(c.company) as company, any_value(c.vendor) as vendor,
                       any_value(c.doc_type) as doc_type, any_value(c.source_system) as source_system
                from cases c group by 1
            )
            select h.ebeln as EBELN, mc.bukrs as BUKRS, 'F' as BSTYP,
                   case h.doc_type {bsart} else 'ZZ' end as BSART,
                   mv.lifnr as LIFNR, 'EUR' as WAERS,
                   strftime(fc.ts, '%Y%m%d') as AEDAT,
                   h.source_system as LOGSYS,
                   coalesce(strftime(fc.ts, '%Y-%m'), '0000-00') as load_month
            from hdr h
            join map_company mc on mc.company = h.company
            join map_vendor  mv on mv.vendor  = h.vendor
            left join first_create fc on fc.ebeln = h.ebeln""",
        # EKPO: one row per PO item, header-level create event stored on the item (AEDAT/ERNAM/CPUTM)
        "EKPO": f"""
            with cr as (
                select case_id, ebeln, ebelp, dats, tims, usnam, net_worth, load_month, seq
                from e where activity = 'Create Purchase Order Item'
            )
            select cr.ebeln as EBELN, cr.ebelp as EBELP, cr.seq as ZZ_EVENT_SEQ,
                   case c.item_type {pstyp} else '0' end as PSTYP,
                   case when c.goods_receipt then 'X' else '' end as WEPOS,
                   case when c.gr_based_iv   then 'X' else '' end as WEBRE,
                   mm.matkl as MATKL, cr.net_worth as NETWR,
                   cr.dats as AEDAT, cr.tims as ZZ_CPUTM, cr.usnam as ERNAM,
                   'R' || substr(cr.ebeln, 3) as BANFN, cr.ebelp as BNFPO,
                   cr.load_month as load_month
            from cr
            join cases c on c.case_id = cr.case_id
            join map_matkl mm on mm.spend_area is not distinct from c.spend_area
                             and mm.sub_spend_area is not distinct from c.sub_spend_area
                             and mm.spend_class is not distinct from c.spend_class""",
        # EBAN: purchase requisition items
        "EBAN": """
            select 'R' || substr(ebeln, 3) as BANFN, ebelp as BNFPO, seq as ZZ_EVENT_SEQ,
                   dats as BADAT, tims as ZZ_ERZET, usnam as ERNAM,
                   ebeln as EBELN, ebelp as EBELP, net_worth as RLWRT, load_month
            from e where activity = 'Create Purchase Requisition Item'""",
        # EKES: vendor confirmations
        "EKES": f"""
            select ebeln as EBELN, ebelp as EBELP, seq as ETENS, 'AB' as EBTYP,
                   case activity {conf} end as ZZ_CONF_KIND,
                   dats as ERDAT, tims as EZEIT, usnam as ERNAM, load_month
            from e where activity in ({acts(CONFIRMATIONS)})""",
        # EKBE: goods receipts and their reversals
        "EKBE": f"""
            select ebeln as EBELN, ebelp as EBELP, '1' as VGABE, gjahr as GJAHR,
                   '50' || lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 8, '0') as BELNR,
                   seq as ZZ_EVENT_SEQ, 'E' as BEWTP,
                   case activity {gr_bwart} end as BWART,
                   case activity {gr_shkzg} end as SHKZG,
                   dats as BUDAT, dats as CPUDT, tims as CPUTM, net_worth as DMBTR,
                   usnam as ERNAM, load_month
            from e where activity in ({acts(GR_DOCS)})""",
        # ESSR: service entry sheets
        "ESSR": """
            select '10' || lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 8, '0') as LBLNI,
                   ebeln as EBELN, ebelp as EBELP, seq as ZZ_EVENT_SEQ,
                   dats as ERDAT, tims as ERZET, usnam as ERNAM, net_worth as NETWR, load_month
            from e where activity = 'Record Service Entry Sheet'""",
        # RBKP + RSEG: logistics invoice verification (header and PO-item line)
        "RBKP": f"""
            select '51' || lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 8, '0') as BELNR,
                   gjahr as GJAHR, case activity {inv_vgart} end as VGART,
                   case activity {inv_tbtkz} end as TBTKZ,
                   case when (case activity {inv_rev} end) then 'X' else '' end as ZZ_IS_REVERSAL,
                   dats as BUDAT, dats as CPUDT, tims as CPUTM, usnam as USNAM,
                   net_worth as RMWWR, 'EUR' as WAERS,
                   ebeln as ZZ_EBELN, ebelp as ZZ_EBELP, seq as ZZ_EVENT_SEQ, load_month
            from e where activity in ({acts(INVOICE_DOCS)})""",
        # BSAK: cleared vendor items (payment run clears the invoice)
        "BSAK": """
            select '15' || lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 8, '0') as AUGBL,
                   dats as AUGDT, tims as ZZ_CPUTM, gjahr as GJAHR,
                   ebeln as EBELN, ebelp as EBELP, seq as ZZ_EVENT_SEQ,
                   net_worth as DMBTR, usnam as USNAM, load_month
            from e where activity = 'Clear Invoice'""",
        # EDIDC: inbound IDocs sent by the vendor
        "EDIDC": f"""
            select lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 16, '0') as DOCNUM,
                   'INVOIC' as MESTYP, case activity {idoc} end as IDOCTP, '2' as DIRECT,
                   dats as CREDAT, tims as CRETIM,
                   ebeln as ZZ_EBELN, ebelp as ZZ_EBELP, seq as ZZ_EVENT_SEQ,
                   net_worth as ZZ_AMOUNT, load_month
            from e where activity in ({acts(IDOCS)})""",
        # CDHDR/CDPOS: change documents (PO changes, invoice payment blocks)
        "CDHDR": f"""
            select case when activity = 'Release Purchase Requisition' then 'BANF' else 'EINKBELEG' end as OBJECTCLAS,
                   ebeln as OBJECTID,
                   lpad(cast(row_number() over (order by ts, case_id, seq) as varchar), 10, '0') as CHANGENR,
                   usnam as USERNAME, dats as UDATE, tims as UTIME,
                   case when activity like 'Release%' then 'ME29N' else 'ME22N' end as TCODE,
                   ebelp as ZZ_EBELP, seq as ZZ_EVENT_SEQ, activity as ZZ_ACTIVITY, load_month
            from e where activity in ({acts(list(PO_CHANGE_FIELDS) + list(INVOICE_BLOCK))})""",
        # SRM status history for items created in SAP SRM
        "SRM_STATUS": """
            select ebeln || ebelp as OBJECT_ID, ebeln as EBELN, ebelp as EBELP, seq as ZZ_EVENT_SEQ,
                   trim(substr(activity, 5)) as STATUS_TEXT,
                   dats as UDATE, tims as UTIME, usnam as USNAM, load_month
            from e where activity like 'SRM:%'""",
        # Anything the mapping does not know yet: kept, never dropped
        "ZZ_UNMAPPED_EVENTS": f"""
            select ebeln as EBELN, ebelp as EBELP, seq as ZZ_EVENT_SEQ, activity as ACTIVITY,
                   dats as UDATE, tims as UTIME, usnam as USNAM, net_worth as NETWR, load_month
            from e where activity not in ({acts(handled)}) and activity not like 'SRM:%'""",
        "_CDPOS_CTE": f"""
            select chg_table, chg_field, activity from (
                select activity, case activity {chg_cases} end as tf from (select distinct activity from e)
            ) where tf is not null""",
        "_LOEKZ": loekz,
        "_BLOCK": block,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/raw/bpic2019_events.parquet")
    ap.add_argument("--out", default="data/landing/sap")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    con = duckdb.connect()
    build(con, src)
    sql = sap_tables(con)
    loekz, block = sql.pop("_LOEKZ"), sql.pop("_BLOCK")
    sql.pop("_CDPOS_CTE")

    # CDPOS needs the change numbers of CDHDR, so derive it from the materialised header
    con.execute(f"create or replace table CDHDR as {sql.pop('CDHDR')}")
    field_map = " ".join(
        f"when '{a}' then '{t}|{f}'" for a, (t, f) in PO_CHANGE_FIELDS.items()
    ) + " when 'Set Payment Block' then 'RBKP|ZLSPR' when 'Remove Payment Block' then 'RBKP|ZLSPR'"
    con.execute(
        f"""
        create or replace table CDPOS as
        with h as (
            select h.*, e.net_worth,
                   lag(e.net_worth) over (partition by e.case_id order by e.seq) as prev_worth
            from CDHDR h
            join e on e.ebeln = h.OBJECTID and e.ebelp = h.ZZ_EBELP and e.seq = h.ZZ_EVENT_SEQ
        ), f as (
            select *, split_part(case ZZ_ACTIVITY {field_map} end, '|', 1) as TABNAME,
                      split_part(case ZZ_ACTIVITY {field_map} end, '|', 2) as FNAME
            from h
        )
        select OBJECTCLAS, OBJECTID, CHANGENR, TABNAME,
               '100' || OBJECTID || ZZ_EBELP as TABKEY, FNAME, 'U' as CHNGIND,
               case when FNAME = 'NETPR' then cast(prev_worth as varchar)
                    else '' end as VALUE_OLD,
               case when FNAME = 'NETPR' then cast(net_worth as varchar)
                    when FNAME = 'LOEKZ' then case ZZ_ACTIVITY {loekz} end
                    when FNAME = 'ZLSPR' then case ZZ_ACTIVITY {block} end
                    else 'X' end as VALUE_NEW,
               load_month
        from f
        """
    )
    # Drop the helper column that only exists to build CDPOS; the activity is derived in dbt
    con.execute("alter table CDHDR drop column ZZ_ACTIVITY")

    for name, q in sql.items():
        con.execute(f"create or replace table {name} as {q}")
    tables = list(sql) + ["CDHDR", "CDPOS"]

    summary = {}
    for name in tables:
        cols = [r[0] for r in con.execute(f"describe {name}").fetchall()]
        n = con.execute(f"select count(*) from {name}").fetchone()[0]
        part = "load_month" in cols and n > 0  # an empty table still gets one (empty) file
        target = out / name
        if part:
            con.execute(
                f"copy {name} to '{target.as_posix()}' (format parquet, partition_by (load_month), compression zstd)"
            )
        else:
            target.mkdir()
            con.execute(f"copy {name} to '{(target / 'full.parquet').as_posix()}' (format parquet, compression zstd)")
        summary[name] = n

    # Audit tables: facts about the source log, used only by dbt reconciliation tests
    for name, q in {
        "ZZ_AUDIT_EVENT_COUNTS": "select activity as ACTIVITY, count(*) as EVENTS, count(distinct case_id) as CASES from ev group by activity",
        "ZZ_AUDIT_CASE_LABELS": "select lpad(po, 10, '0') || lpad(item, 5, '0') as CASE_KEY, item_category as ITEM_CATEGORY from cases",
    }.items():
        (out / name).mkdir()
        con.execute(f"copy ({q}) to '{(out / name / 'full.parquet').as_posix()}' (format parquet)")
        summary[name] = con.execute(f"select count(*) from ({q})").fetchone()[0]
    (out / "_extract_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
