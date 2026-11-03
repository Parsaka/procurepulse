import io

from scripts.fetch_bpic2019 import xes_to_rows

XES = b"""<?xml version="1.0" encoding="UTF-8"?>
<log xes.version="1.0" xmlns="http://www.xes-standard.org/">
  <string key="concept:name" value="BPIC19"/>
  <trace>
    <string key="concept:name" value="4507000001_00010"/>
    <boolean key="Goods Receipt" value="true"/>
    <event>
      <string key="concept:name" value="Create Purchase Order Item"/>
      <date key="time:timestamp" value="2018-01-02T09:00:00.000+00:00"/>
      <float key="Cumulative net worth (EUR)" value="298.0"/>
    </event>
    <event>
      <string key="concept:name" value="Record Goods Receipt"/>
      <date key="time:timestamp" value="2018-01-10T12:00:00.000+00:00"/>
      <float key="Cumulative net worth (EUR)" value="298.0"/>
    </event>
  </trace>
  <trace>
    <string key="concept:name" value="4507000002_00010"/>
    <boolean key="Goods Receipt" value="false"/>
    <event>
      <string key="concept:name" value="Create Purchase Order Item"/>
      <date key="time:timestamp" value="2018-02-01T08:00:00.000+00:00"/>
      <int key="Count" value="3"/>
    </event>
  </trace>
</log>"""


def test_events_carry_their_case_attributes():
    rows = list(xes_to_rows(io.BytesIO(XES)))
    assert len(rows) == 3
    assert rows[0]["case:concept:name"] == "4507000001_00010"
    assert rows[0]["case:Goods Receipt"] is True
    assert rows[1]["concept:name"] == "Record Goods Receipt"
    assert rows[1]["Cumulative net worth (EUR)"] == 298.0
    # attributes do not leak from one trace into the next
    assert rows[2]["case:Goods Receipt"] is False and "Cumulative net worth (EUR)" not in rows[2]
    assert rows[2]["Count"] == 3
    # log-level attributes are not case attributes
    assert all("case:BPIC19" not in r for r in rows)
