"""Discover live ADS forms and intersect variable-specific availability constraints.

No guessed end year and no silent fallback to old snapshots for downloads.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CatalogError(RuntimeError):
    pass


def _session():
    s = requests.Session()
    s.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        ),
    )
    return s


def fetch_catalog(cfg, kind, source="EAC4"):
    dataset = cfg["sources"][source][kind]
    url = cfg["catalog_url"].rstrip("/") + "/" + dataset
    session = _session()

    def get(url):
        r = session.get(url, timeout=cfg["http_timeout"])
        r.raise_for_status()
        return r.json()

    collection = get(url)
    if collection.get("cads:disabled_reason"):
        raise CatalogError(str(collection["cads:disabled_reason"]))
    links = {x["rel"]: x["href"] for x in collection["links"]}
    try:
        snap = {
            "collection": collection,
            "form": get(links["form"]),
            "constraints": get(links["constraints"]),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
        }
    except (KeyError, TypeError) as exc:
        raise CatalogError("ADS schema changed: inspect current collection/form") from exc
    if not isinstance(snap["form"], list) or not isinstance(snap["constraints"], list):
        raise CatalogError("Unsupported ADS schema; refusing inferred availability")
    folder = Path(cfg["metadata_dir"]) / "catalog"
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snap, indent=2)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (folder / f"{dataset}-{digest[:16]}.json").write_text(payload)
    snap["sha256"] = digest
    session.close()
    return snap


def load_snapshot(directory, kind):
    """Explicit offline evidence; never used implicitly by download commands."""
    directory = Path(directory)
    return {
        key: json.loads((directory / f"{kind}.{key}.json").read_text())
        for key in ("collection", "form", "constraints")
    }


def choices(snap, field):
    f = next((x for x in snap["form"] if x.get("name") == field), None)
    if f is None:
        raise CatalogError(f"Field {field!r} absent from live form")
    details = f.get("details", {})
    return set(map(str, details.get("values", []))) | {
        str(v) for g in details.get("groups", []) for v in g.get("values", [])
    }


def matching_rows(snap, spec, kind):
    if spec["cams_variable"] not in choices(snap, "variable"):
        raise CatalogError(f"Variable unavailable: {spec['cams_variable']}")
    if spec["level_type"] not in ("surface", "model", "pressure"):
        raise CatalogError("Unsupported level type")
    key = {"model": "model_level", "pressure": "pressure_level"}.get(spec["level_type"])
    rows = []
    for row in snap["constraints"]:
        if spec["cams_variable"] not in row.get("variable", []):
            continue
        if key and str(spec["level"]) not in row.get(key, []):
            continue
        if not key and (row.get("model_level") or row.get("pressure_level")):
            continue
        if kind == "monthly" and "monthly_mean" not in row.get("product_type", []):
            continue
        if kind == "subdaily" and not {f"{h:02d}:00" for h in range(0, 24, 3)} <= set(
            row.get("time", [])
        ):
            continue
        rows.append(row)
    if not rows:
        raise CatalogError("No compatible variable/level/product availability rows")
    return rows


def available_months(snap, spec, kind):
    """Only complete calendar months allowed, per variable and selected level."""
    cache_key = (spec["cams_variable"], spec["level_type"], spec["level"], kind)
    cache = snap.setdefault("_availability", {})
    if cache_key in cache:
        return cache[cache_key]
    rows = matching_rows(snap, spec, kind)
    start, end = snap["collection"]["extent"]["temporal"]["interval"][0]
    if not start or not end:
        raise CatalogError("Open-ended catalogue interval: cannot infer last complete month")
    lo, hi = pd.Timestamp(start).tz_localize(None), pd.Timestamp(end).tz_localize(None)
    months = set()
    for row in rows:
        if kind == "monthly":
            if not row.get("year") or not row.get("month"):
                raise CatalogError("Missing year/month constraints")
            months.update(
                pd.Period(f"{y}-{m}", freq="M") for y in row["year"] for m in row["month"]
            )
        else:
            # Union days across intervals before demanding full-month completeness.
            days = set()
            for interval in row.get("date", []):
                ends = interval.split("/")
                days.update(pd.date_range(ends[0], ends[-1], freq="D"))
            for p in pd.period_range(lo, hi, freq="M"):
                if set(pd.date_range(p.start_time, p.end_time.normalize())) <= days:
                    months.add(p)
    # Collection end timestamps often denote 00:00 on the last included day.
    result = sorted(
        p
        for p in months
        if p.start_time >= lo.normalize() and p.end_time.normalize() <= hi.normalize()
    )
    cache[cache_key] = result
    return result


def validate_request(snap, spec, kind, request):
    matching_rows(snap, spec, kind)
    for key, value in request.items():
        if key in ("date", "area"):
            continue
        allowed = choices(snap, key)
        values = value if isinstance(value, list) else [value]
        if not set(map(str, values)) <= allowed:
            raise CatalogError(f"Request {key} contains values not in ADS form")
    p = (
        pd.Period(f"{request['year'][0]}-{request['month'][0]}", freq="M")
        if kind == "monthly"
        else pd.Period(request["date"].split("/")[0], freq="M")
    )
    if p not in available_months(snap, spec, kind):
        raise CatalogError(f"Month {p} not confirmed by current constraints")
