"""One variable × month × homogeneous vertical representation per request."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .catalog import available_months, choices, validate_request


@dataclass(frozen=True)
class Batch:
    dataset: str
    variable: str
    year: int
    month: int
    temporal_resolution: str
    level_type: str
    level: int | None
    api_request: dict
    filepath: str
    key: str
    catalog_sha256: str = ""

    def to_dict(self):
        return asdict(self)


def build_batch(cfg, snap, pollutant, period, kind):
    p = pd.Period(period, freq="M")
    spec = cfg["registry"][pollutant]
    r = {"variable": [spec["cams_variable"]], "data_format": cfg["data_format"]}
    if kind == "monthly":
        r.update(
            year=[str(p.year)],
            month=[f"{p.month:02d}"],
            product_type=["monthly_mean"],
            time=["00:00"],
        )
    elif kind == "subdaily":
        times = sorted(choices(snap, "time"))
        if times != [f"{h:02d}:00" for h in range(0, 24, 3)]:
            raise ValueError("ADS temporal sampling changed: review before requesting")
        r.update(date=f"{p.start_time:%Y-%m-%d}/{p.end_time:%Y-%m-%d}", time=times)
    else:
        raise ValueError(kind)
    if spec["level_type"] != "surface":
        r[spec["level_type"] + "_level"] = [str(spec["level"])]
    if cfg.get("area"):
        r["area"] = cfg["area"]
    validate_request(snap, spec, kind, r)
    dataset = snap["collection"]["id"]
    digest = hashlib.sha256(json.dumps([dataset, r], sort_keys=True).encode()).hexdigest()
    suffix = "grib" if cfg["data_format"] == "grib" else "zip"
    path = Path(cfg["data_dir"]) / "raw/eac4" / kind / pollutant / str(p.year)
    path /= f"{p.month:02d}"
    path /= f"{pollutant}_{p}_{digest[:12]}.{suffix}"
    return Batch(
        dataset,
        pollutant,
        p.year,
        p.month,
        kind,
        spec["level_type"],
        spec["level"],
        r,
        str(path),
        digest,
        snap.get("sha256", "offline"),
    )


def plan_batches(cfg, snap, kind, start=None, end=None, pollutants=None):
    start, end = start or cfg.get("start_date"), end or cfg.get("end_date")
    if start and end and pd.Period(start, "M") > pd.Period(end, "M"):
        raise ValueError("start must not be after end")
    result = []
    for name in pollutants or cfg["pollutants"]:
        periods = available_months(snap, cfg["registry"][name], kind)
        if not periods:
            raise ValueError(f"No available complete months for {name}")
        if start and pd.Period(start, "M") < periods[0]:
            raise ValueError(f"start predates available {name} data")
        if end and pd.Period(end, "M") > periods[-1]:
            raise ValueError(f"end exceeds confirmed available {name} data")
        periods = [
            p
            for p in periods
            if (not start or p >= pd.Period(start, "M")) and (not end or p <= pd.Period(end, "M"))
        ]
        result.extend(build_batch(cfg, snap, name, p, kind) for p in periods)
    return sorted(result, key=lambda b: (b.year, b.month, b.variable))


def estimate(cfg, batches):
    grid = cfg["grid"]
    cells = grid["latitude"] * grid["longitude"]
    samples = sum(
        1
        if b.temporal_resolution == "monthly"
        else pd.Period(f"{b.year}-{b.month}", "M").days_in_month * 8
        for b in batches
    )
    raw = cells * samples * 4
    return {
        "batches_files": len(batches),
        "fields": samples,
        "grid_cells": cells,
        "float32_uncompressed_bytes": raw,
        "float32_uncompressed_GiB": raw / 2**30,
        "planning_disk_GiB": raw * cfg["storage_copies"] / 2**30,
        "assumptions": "global float32; raw + interim + processed + temporary (configurable); compression and metadata not measured; bbox estimate is conservative",
    }
