"""Download the BPI Challenge 2019 event log from 4TU.ResearchData and convert it to Parquet.

The log is real purchase-to-pay data from the SAP system of a multinational
coatings and paints company (CC BY 4.0). The script:
  1. finds the dataset through the 4TU API (no hard-coded file URL),
  2. downloads the XES file and verifies its MD5 against the repository,
  3. streams the XES into one flat Parquet file (one row per event),
  4. writes a manifest with checksums and counts for reproducibility.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

API = "https://data.4tu.nl/v2"
TITLE = "BPI Challenge 2019"
UA = {"User-Agent": "procurepulse-data-fetch/1.0", "Content-Type": "application/json"}


def _get(url: str, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=UA, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def find_dataset() -> dict:
    hits = _get(f"{API}/articles/search", json.dumps({"search_for": TITLE}).encode())
    exact = [h for h in hits if h.get("title", "").strip().lower() == TITLE.lower()]
    if not exact:
        sys.exit(f"No dataset titled {TITLE!r}; titles seen: {[h.get('title') for h in hits][:20]}")
    return exact[0]


def pick_file(files: list[dict]) -> dict:
    for suffix in (".xes.gz", ".xes", ".zip"):
        for f in files:
            if f["name"].lower().endswith(suffix):
                return f
    sys.exit(f"No XES file in {[f['name'] for f in files]}")


def download(url: str, dest: Path) -> str:
    md5 = hashlib.md5()
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=600) as r, dest.open("wb") as out:
        while chunk := r.read(1 << 20):
            md5.update(chunk)
            out.write(chunk)
    return md5.hexdigest()


def open_xes(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rb")
    if path.name.endswith(".zip"):
        z = zipfile.ZipFile(path)
        inner = next(n for n in z.namelist() if n.lower().endswith(".xes"))
        return z.open(inner)
    return path.open("rb")


def _val(el: ET.Element):
    kind = el.tag.rsplit("}", 1)[-1]
    v = el.get("value")
    if v is None:
        return None
    if kind == "float":
        return float(v)
    if kind == "int":
        return int(v)
    if kind == "boolean":
        return v.lower() == "true"
    return v  # strings and dates stay strings; typed later in dbt


def xes_to_rows(fh):
    """Stream traces; yield one dict per event with case attributes prefixed 'case:'."""
    case_attrs: dict = {}
    in_event = False
    event: dict = {}
    depth_trace = False
    for ev, el in ET.iterparse(fh, events=("start", "end")):
        tag = el.tag.rsplit("}", 1)[-1]
        if ev == "start":
            if tag == "trace":
                depth_trace, case_attrs = True, {}
            elif tag == "event":
                in_event, event = True, {}
            continue
        # end
        if tag == "event":
            in_event = False
            yield {**case_attrs, **event}
            el.clear()
        elif tag == "trace":
            depth_trace = False
            el.clear()
        elif depth_trace and el.get("key") is not None:
            if in_event:
                event[el.get("key")] = _val(el)
            else:
                case_attrs["case:" + el.get("key")] = _val(el)


# Published statistics of the BPI Challenge 2019 log; any copy must reproduce them.
EXPECTED_EVENTS = 1_595_923
EXPECTED_CASES = 251_734


def fetch_from_4tu(work: Path) -> tuple[Path, dict]:
    ds = find_dataset()
    uuid = ds["uuid"]
    files = _get(f"{API}/articles/{uuid}/files")
    f = pick_file(files)
    expected_md5 = f.get("computed_md5") or f.get("supplied_md5")
    local = work / f["name"]
    print(f"Dataset {uuid} ({ds.get('doi')}); downloading {f['name']} ({f.get('size')} bytes)")
    md5 = download(f["download_url"], local)
    if expected_md5 and md5 != expected_md5:
        sys.exit(f"MD5 mismatch: got {md5}, expected {expected_md5}")
    return local, {"source": "4TU.ResearchData", "dataset_uuid": uuid, "doi": ds.get("doi"), "file_md5": md5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--workdir", default="/tmp/bpic2019")
    ap.add_argument("--local-file", help="Use an already downloaded XES copy (e.g. a mirror) instead of 4TU")
    ap.add_argument("--local-source", default="mirror", help="Free-text provenance of --local-file")
    a = ap.parse_args()
    out, work = Path(a.out), Path(a.workdir)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    if a.local_file:
        local = Path(a.local_file)
        md5 = hashlib.md5(local.read_bytes()).hexdigest()
        prov = {"source": a.local_source, "file_md5": md5}
    else:
        local, prov = fetch_from_4tu(work)
    f = {"name": local.name}

    rows, writer, n_events, cases, schema = [], None, 0, set(), None
    pq_path = out / "bpic2019_events.parquet"
    with open_xes(local) as fh:
        for r in xes_to_rows(fh):
            rows.append(r)
            if len(rows) == 200_000:
                writer, schema = _flush(rows, writer, schema, pq_path)
                n_events += len(rows)
                rows = []
            cases.add(r.get("case:concept:name"))
    if rows:
        writer, schema = _flush(rows, writer, schema, pq_path)
        n_events += len(rows)
    writer.close()

    if (n_events, len(cases)) != (EXPECTED_EVENTS, EXPECTED_CASES):
        sys.exit(f"Copy does not match the published log: {n_events} events, {len(cases)} cases")
    manifest = {
        **prov,
        "title": TITLE,
        "license": "CC BY 4.0",
        "file": f["name"],
        "events": n_events,
        "cases": len(cases),
        "parquet_sha256": hashlib.sha256(pq_path.read_bytes()).hexdigest(),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def _flush(rows, writer, schema, path):
    if schema is None:
        keys = sorted({k for r in rows for k in r})
        fields = []
        for k in keys:
            sample = next((r[k] for r in rows if r.get(k) is not None), None)
            t = pa.float64() if isinstance(sample, float) else pa.bool_() if isinstance(sample, bool) else pa.string()
            fields.append(pa.field(k, t))
        schema = pa.schema(fields)
        writer = pq.ParquetWriter(path, schema, compression="zstd", compression_level=9)
    cols = {}
    for fld in schema:
        vals = [r.get(fld.name) for r in rows]
        if pa.types.is_string(fld.type):
            vals = [None if v is None else str(v) for v in vals]
        elif pa.types.is_floating(fld.type):
            vals = [None if v is None else float(v) for v in vals]
        cols[fld.name] = vals
    extra = {k for r in rows for k in r} - set(schema.names)
    if extra:
        sys.exit(f"Unexpected attributes after first batch: {extra}")
    writer.write_table(pa.table(cols, schema=schema))
    return writer, schema


if __name__ == "__main__":
    main()
