# SAP data model (EN / DE)

The BPI Challenge 2019 log was exported from an SAP ECC system. `extract/sap_extract.py` reverses that
export: every event becomes the SAP table row that would have produced it, with SAP field names and
formats (CHAR keys with leading zeros, DATS `YYYYMMDD`, TIMS `HHMMSS`, `X`/blank flags). dbt then rebuilds
the event log from those tables, as a process mining connector (for example Celonis' P2P connector) does
on a real system. The test `assert_event_log_reconstruction_is_lossless` proves that every one of the
1,595,923 events comes back with the right activity, and
`assert_item_category_derived_from_sap_fields_matches_source` proves that the item category derived from
`EKPO-PSTYP/WEPOS/WEBRE` matches the source label for all 251,734 items.

> This is a simulation built from a real SAP log, not access to a live SAP system.

## Tables

| Table | EN | DE | Rows | Activities it carries |
|---|---|---|---:|---|
| EKKO | Purchasing document header | Einkaufsbelegkopf | 76,349 | (context) |
| EKPO | Purchasing document item | Einkaufsbelegposition | 251,734 | Create Purchase Order Item |
| EBAN | Purchase requisition | Bestellanforderung | 46,592 | Create Purchase Requisition Item |
| EKES | Vendor confirmations | Lieferantenbestätigungen | 32,309 | Receive / Update Order Confirmation |
| EKBE | PO history: goods receipts | Bestellentwicklung: Wareneingänge | 317,193 | Record / Cancel Goods Receipt (BWART 101/102) |
| ESSR | Service entry sheet | Leistungserfassungsblatt | 164,975 | Record Service Entry Sheet |
| RBKP | Invoice document header | Rechnungsbelegkopf | 236,514 | Record / Cancel (Subsequent) Invoice Receipt |
| BSAK | Cleared vendor items | Ausgeglichene Kreditorenposten | 194,393 | Clear Invoice |
| EDIDC | Inbound IDoc control record | IDoc-Kontrollsatz (Eingang) | 226,174 | Vendor creates invoice / debit memo |
| CDHDR / CDPOS | Change document header / items | Änderungsbelegkopf / -position | 114,441 | price, quantity, indicators, deletion, release, payment block |
| SRM_STATUS | SRM transaction status | SRM-Vorgangsstatus | 11,598 | SRM: ... |
| LFA1 | Vendor master | Kreditorenstamm | 1,975 | master data |
| T001 | Company codes | Buchungskreise | 4 | master data |
| T023T | Material group texts | Warengruppenbezeichnungen | 136 | master data (spend taxonomy) |

The event tables add up to exactly 1,595,923 rows; `ZZ_UNMAPPED_EVENTS` is empty.

## Key fields

| Field | Table | EN | DE | Used for |
|---|---|---|---|---|
| EBELN / EBELP | EKKO, EKPO | PO number / item | Bestellnummer / -position | case key `EBELN‖EBELP` |
| BSART | EKKO | document type (NB standard, FO framework, EC) | Belegart | features |
| LIFNR | EKKO | vendor | Kreditor | vendor dimension |
| BUKRS | EKKO | company code | Buchungskreis | dimension |
| PSTYP | EKPO | item category (0 standard, 2 consignment, ...) | Positionstyp | item category |
| WEPOS | EKPO | goods receipt expected | Wareneingangskennzeichen | 2-way vs 3-way match |
| WEBRE | EKPO | GR-based invoice verification | WE-bezogene Rechnungsprüfung | invoice before / after GR |
| MATKL | EKPO | material group | Warengruppe | spend taxonomy |
| NETWR | EKPO | net order value | Nettobestellwert | value |
| BWART / SHKZG | EKBE | movement type / debit-credit | Bewegungsart / Soll-Haben | GR vs GR reversal |
| VGART, TBTKZ | RBKP | transaction / subsequent debit-credit | Vorgangsart / Nachbelastung | invoice vs subsequent invoice |
| ZLSPR | RBKP (via CDPOS) | payment block key | Zahlsperre | payment block set / removed |
| OBJECTCLAS, TABNAME, FNAME | CDHDR, CDPOS | changed object, table, field | Objektklasse, Tabelle, Feld | which change happened |
| AUGDT | BSAK | clearing date | Ausgleichsdatum | Clear Invoice |
| MESTYP, IDOCTP | EDIDC | IDoc message / type | Nachrichtentyp | vendor-side events |

## Item category (target process)

| Category | PSTYP | WEPOS | WEBRE | Target process |
|---|---|---|---|---|
| 3-way match, invoice after GR | ≠ 2 | X | X | PO → GR → invoice → clear |
| 3-way match, invoice before GR | ≠ 2 | X | blank | PO → (invoice, GR in any order) → payment blocked until GR → clear |
| 2-way match | ≠ 2 | blank | | PO → invoice → clear (no GR) |
| Consignment | 2 | | | PO → GR; invoiced outside the PO item |

## Simplifications

- `EKBE` holds goods receipts only; invoices sit in `RBKP`, which carries the PO item reference that `RSEG`
  would hold (`ZZ_EBELN`, `ZZ_EBELP`).
- Payment blocks are change documents on `RBKP-ZLSPR` keyed by PO item.
- Vendor-side events arrive as inbound IDocs (EDI vendors).
- Fields prefixed `ZZ_` are customer fields that keep the link to the source event for the audit.
- The anonymised user names of the log map to `USNAM`/`ERNAM` (`batch_xx` users are background jobs).
