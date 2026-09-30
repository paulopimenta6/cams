"""Immutable NetCDF partitions; yearly Zarr generations with an atomic index."""

import hashlib
import json
import os
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from filelock import FileLock

from .metadata import provenance
from .requests import Batch
from .storage import Manifest, now, sha256
from .units import standardize
from .validation import normalize, open_raw


def batch_from_row(row):
    return Batch(
        **{
            k: (json.loads(row[k]) if k == "api_request" else row[k])
            for k in Batch.__dataclass_fields__
        }
    )


def process_batch(cfg, batch):
    manifest = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    row = manifest.get(batch.key)
    if not row or not manifest.intact(row):
        raise ValueError("Processing requires a checksum-verified raw payload")
    spec = cfg["registry"][batch.variable]
    # Output identity incorporates registry/conversion policy and code version.
    prov = provenance(batch, row, cfg)
    signature = hashlib.sha256(
        json.dumps(
            [spec, cfg["chunks"], prov["code_version"], row["checksum"]], sort_keys=True
        ).encode()
    ).hexdigest()[:16]
    folder = (
        Path(cfg["data_dir"])
        / "processed/eac4"
        / batch.temporal_resolution
        / batch.variable
        / str(batch.year)
    )
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"{batch.month:02d}_{batch.key[:12]}_{signature}.nc"
    with FileLock(str(output) + ".lock"):
        row = manifest.get(batch.key)
        if (
            str(output) == row["processed_path"]
            and output.exists()
            and sha256(output) == row["processed_checksum"]
        ):
            return output
        with open_raw(
            batch.filepath,
            Path(cfg["data_dir"]) / "interim",
            chunks={},
            netcdf_engine=cfg["netcdf_engine"],
        ) as ds:
            a = standardize(normalize(ds, spec).chunk(cfg["chunks"]), spec)
            a.name = batch.variable
            a.attrs.update(
                cell_methods="time: mean"
                if batch.temporal_resolution == "monthly"
                else "time: point",
                source_level_type=batch.level_type,
                source_level=str(batch.level),
            )
            # Keep original horizontal coordinate values/order and earth-shape metadata.
            out = a.to_dataset()
            out.attrs = prov
            if batch.temporal_resolution == "monthly":
                periods = pd.DatetimeIndex(out.time.values).to_period("M")
                out = out.assign_coords(time=periods.start_time)
                bounds = np.array(
                    [
                        [p.start_time.to_datetime64(), (p + 1).start_time.to_datetime64()]
                        for p in periods
                    ]
                )
                out["time_bnds"] = (("time", "bnds"), bounds)
                out.time.attrs["bounds"] = "time_bnds"
            out.latitude.attrs.update(units="degrees_north", standard_name="latitude")
            out.longitude.attrs.update(units="degrees_east", standard_name="longitude")
            out.time.attrs["standard_name"] = "time"
            temp = output.with_name(output.name + ".part")
            encoding = {
                batch.variable: {
                    "zlib": True,
                    "complevel": 4,
                    "dtype": "float32",
                    "chunksizes": tuple(min(out.sizes[d], cfg["chunks"][d]) for d in a.dims),
                }
            }
            if "time_bnds" in out:
                encoding["time"] = {
                    "units": "days since 1970-01-01",
                    "calendar": "proleptic_gregorian",
                }
                encoding["time_bnds"] = {
                    "units": "days since 1970-01-01",
                    "calendar": "proleptic_gregorian",
                }
            with __import__("dask").config.set(scheduler="synchronous"):
                out.to_netcdf(temp, engine=cfg["netcdf_engine"], encoding=encoding)
            with xr.open_dataset(temp, engine=cfg["netcdf_engine"]) as check:
                if check[batch.variable].sizes != a.sizes:
                    raise ValueError("Processed dimension mismatch")
                # Force decoder/data reads, including compressed chunks.
                if not np.isfinite(check[batch.variable]).any().item():
                    raise ValueError("Empty processed product")
            os.replace(temp, output)
        manifest.set(
            batch.key,
            "processed",
            processed_path=str(output),
            processed_checksum=sha256(output),
            processing_error=None,
        )
    return output


def product_root(cfg, kind="monthly"):
    scope = hashlib.sha256(
        json.dumps([cfg.get("area"), cfg["pollutants"]], sort_keys=True).encode()
    ).hexdigest()[:12]
    return Path(cfg["data_dir"]) / "processed/eac4" / kind / "zarr" / scope


def consolidate(cfg, kind="monthly"):
    """One immutable, consolidated-metadata store per year, all configured variables.

    Rebuild only changed years. Index changes atomically after successful writes;
    older generations remain available for rollback, and are not auto-deleted.
    """
    m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    rows = [
        r
        for r in m.rows()
        if r["status"] == "processed"
        and r["temporal_resolution"] == kind
        and r["variable"] in cfg["pollutants"]
        and json.loads(r["api_request"]).get("area") == cfg.get("area")
        and json.loads(r["api_request"]).get("data_format") == cfg["data_format"]
    ]
    if not rows:
        raise ValueError("No processed observations: cannot build a scientific dataset")
    root = product_root(cfg, kind)
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / "writer.lock")):
        old = (
            json.loads((root / "index.json").read_text())
            if (root / "index.json").exists()
            else {"years": {}}
        )
        index = {
            "source": "EAC4",
            "temporal_resolution": kind,
            "updated_at": now(),
            "years": dict(old["years"]),
        }
        for year in sorted({r["year"] for r in rows}):
            yr = [r for r in rows if r["year"] == year]
            coverage = {
                v: {r["month"] for r in yr if r["variable"] == v} for v in cfg["pollutants"]
            }
            if (
                any(not v for v in coverage.values())
                or len({tuple(sorted(v)) for v in coverage.values()}) != 1
            ):
                raise ValueError(
                    f"Unequal variable coverage for {year}: {coverage}; fill gaps first"
                )
            if len({(r["variable"], r["month"]) for r in yr}) != len(yr):
                raise ValueError(
                    "Duplicate processed partitions; review configuration/request identity"
                )
            for r in yr:
                if (
                    not Path(r["processed_path"]).is_file()
                    or sha256(r["processed_path"]) != r["processed_checksum"]
                ):
                    raise ValueError("Processed checksum mismatch")
            digest = hashlib.sha256(
                json.dumps([(r["key"], r["processed_checksum"]) for r in yr]).encode()
            ).hexdigest()[:16]
            name = f"{year}-{digest}.zarr"
            dest = root / name
            if not dest.exists():
                datasets = []
                try:
                    for v in cfg["pollutants"]:
                        paths = [r["processed_path"] for r in yr if r["variable"] == v]
                        ds = xr.open_mfdataset(
                            paths,
                            engine=cfg["netcdf_engine"],
                            combine="by_coords",
                            chunks=cfg["chunks"],
                            data_vars="minimal",
                            coords="minimal",
                            compat="equals",
                            join="exact",
                            combine_attrs="drop_conflicts",
                        )
                        datasets.append(ds)
                    ds = xr.merge(
                        datasets, join="exact", compat="equals", combine_attrs="drop_conflicts"
                    )
                    ds.attrs = {
                        "source": "EAC4",
                        "dataset": yr[0]["dataset"],
                        "temporal_resolution": kind,
                        "year": year,
                        "months_present": json.dumps(sorted(next(iter(coverage.values())))),
                        "provenance_manifest": json.dumps(
                            [
                                {
                                    k: r[k]
                                    for k in (
                                        "key",
                                        "filepath",
                                        "checksum",
                                        "processed_path",
                                        "processed_checksum",
                                    )
                                }
                                for r in yr
                            ]
                        ),
                        "history": "annual immutable Zarr partition; no spatial interpolation",
                    }
                    for v in ds.variables:
                        ds[v].encoding = {}
                    ds = ds.chunk({k: min(v, ds.sizes[k]) for k, v in cfg["chunks"].items()})
                    temp = root / (name + ".part-" + uuid.uuid4().hex)
                    with __import__("dask").config.set(scheduler="synchronous"):
                        ds.to_zarr(temp, mode="w", consolidated=True, zarr_format=2)
                    with xr.open_zarr(temp, consolidated=True) as test:
                        if dict(test.sizes) != dict(ds.sizes):
                            raise ValueError("Zarr size mismatch")
                    os.replace(temp, dest)
                finally:
                    for d in datasets:
                        d.close()
            index["years"][str(year)] = {"path": name, "generation": digest}
        tmp = root / "index.json.part"
        tmp.write_text(json.dumps(index, indent=2))
        os.replace(tmp, root / "index.json")
    return root / "index.json"


def open_database(cfg, kind="monthly", allow_gaps=False):
    root = product_root(cfg, kind)
    index = json.loads((root / "index.json").read_text())
    opened = [
        xr.open_zarr(root / v["path"], consolidated=True) for k, v in sorted(index["years"].items())
    ]
    try:
        ds = xr.concat(
            opened,
            dim="time",
            data_vars="minimal",
            coords="minimal",
            compat="equals",
            join="exact",
            combine_attrs="drop_conflicts",
        ).sortby("time")
        t = pd.DatetimeIndex(ds.time.values)
        if t.has_duplicates:
            raise ValueError("Duplicate times in database")
        if not allow_gaps:
            expected = pd.date_range(t.min(), t.max(), freq="MS" if kind == "monthly" else "3h")
            if not t.equals(expected):
                raise ValueError("Temporal gaps in analytical database")
        ds.attrs.update(source="EAC4", temporal_resolution=kind)
        ds.set_close(lambda: [d.close() for d in opened])
        return ds
    except Exception:
        for d in opened:
            d.close()
        raise
