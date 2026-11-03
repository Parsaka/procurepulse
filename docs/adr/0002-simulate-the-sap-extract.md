# 2. Rebuild the SAP tables instead of starting from the event log

**Status:** accepted

**Context.** Real process mining projects do not start from a clean event log; they start from SAP tables
(EKKO, EKPO, EKBE, RBKP, CDHDR/CDPOS, ...) and build the log in SQL. Public SAP P2P table extracts do not
exist.

**Decision.** Reverse the BPI 2019 export into the SAP tables that would have produced it, with SAP field
names and formats, partitioned like monthly delta loads. dbt rebuilds the event log from those tables, and
two tests prove the round trip is lossless (all 1,595,923 events, all 251,734 item categories).

**Consequences.** The project exercises SAP data modelling (change documents, item categories from
PSTYP/WEPOS/WEBRE, movement types) honestly: it is documented as a simulation, never as live SAP access.
