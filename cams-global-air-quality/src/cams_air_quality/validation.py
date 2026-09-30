"""Fail closed on ambiguous dimensions, wrong level, missing periods or payload errors."""

import shutil
import zipfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from filelock import FileLock

from .storage import sha256
from .units import canonical


@contextmanager
def open_raw(path, interim, chunks=None, netcdf_engine="h5netcdf"):
    """Keep original bytes; unpack ZIP safely into a checksum-specific cache."""
    path, interim = Path(path), Path(interim)
    with path.open("rb") as f:
        magic = f.read(4)

    def open_netcdf(candidate):
        with Path(candidate).open("rb") as stream:
            header = stream.read(4)
        engine = "scipy" if header.startswith(b"CDF") else netcdf_engine
        return xr.open_dataset(candidate, engine=engine, chunks=chunks)

    with ExitStack() as stack:
        if magic.startswith(b"PK"):
            target = interim / "unpacked" / sha256(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(target) + ".lock"):
                with zipfile.ZipFile(path) as z:
                    names = z.infolist()
                    if sum(n.file_size for n in names) > 4 * 1024**3:
                        raise ValueError("ZIP exceeds single-batch extraction limit (4 GiB)")
                    if z.testzip() is not None:
                        raise ValueError("ZIP CRC validation failed")
                    if any(
                        Path(n.filename).is_absolute() or ".." in Path(n.filename).parts
                        for n in names
                    ):
                        raise ValueError("Unsafe ZIP member path")
                    target.mkdir(exist_ok=True)
                    for n in names:
                        if n.is_dir():
                            continue
                        dest = target / n.filename
                        if dest.suffix.lower() not in (".nc", ".nc4"):
                            raise ValueError("Unexpected member in NetCDF ZIP")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if not dest.exists() or dest.stat().st_size != n.file_size:
                            with z.open(n) as src, dest.open("wb") as dst:
                                shutil.copyfileobj(src, dst)
            files = sorted(target.rglob("*.nc")) + sorted(target.rglob("*.nc4"))
            if not files:
                raise ValueError("ZIP has no NetCDF files")
            datasets = [stack.enter_context(open_netcdf(p)) for p in files]
            ds = (
                xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")
                if len(datasets) > 1
                else datasets[0]
            )
        elif magic == b"GRIB":
            ds = stack.enter_context(
                xr.open_dataset(
                    path,
                    engine="cfgrib",
                    decode_timedelta=True,
                    chunks=chunks,
                    backend_kwargs={
                        "indexpath": "",
                        "read_keys": [
                            "paramId",
                            "typeOfLevel",
                            "level",
                            "gridType",
                            "shapeOfTheEarth",
                        ],
                    },
                )
            )
        else:
            ds = stack.enter_context(open_netcdf(path))
        yield ds


def normalize(ds, spec):
    rename = {
        x: y
        for x, y in [("lat", "latitude"), ("lon", "longitude")]
        if x in ds.coords and y not in ds.coords
    }
    ds = ds.rename(rename)
    # GRIB valid_time includes forecast step; never silently use forecast initialization.
    if "valid_time" in ds.coords:
        vt = ds["valid_time"]
        if vt.ndim > 1:
            raise ValueError("Ambiguous forecast time/step grid")
        if vt.ndim == 1 and vt.dims[0] != "valid_time":
            old = vt.dims[0]
            if old == "time":
                ds = ds.assign_coords(time=vt.values).drop_vars("valid_time")
            else:
                raise ValueError("Unsupported valid_time dimension")
        elif "valid_time" in ds.dims:
            if "time" in ds:
                ds = ds.drop_vars("time")
            ds = ds.rename({"valid_time": "time"})
        elif "time" not in ds.dims:
            stamp = vt.values
            ds = ds.drop_vars([x for x in ["time", "valid_time"] if x in ds])
            ds = ds.expand_dims(time=[stamp])
    if "time" in ds.coords and "time" not in ds.dims:
        ds = ds.expand_dims("time")
    candidates = [
        n
        for n, a in ds.data_vars.items()
        if n in spec["aliases"] or a.attrs.get("GRIB_paramId") == spec.get("param_id")
    ]
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one requested variable, found {candidates}")
    da = ds[candidates[0]]
    if (
        "GRIB_paramId" in da.attrs
        and spec.get("param_id") is not None
        and da.attrs["GRIB_paramId"] != spec["param_id"]
    ):
        raise ValueError("GRIB parameter identity disagrees with registry")
    vertical = [
        x
        for x in (
            "hybrid",
            "model_level",
            "model_level_number",
            "level",
            "lev",
            "pressure_level",
            "isobaricInhPa",
        )
        if x in da.coords
    ]
    if spec["level_type"] == "model":
        if "isobaricInhPa" in vertical or "pressure_level" in vertical:
            raise ValueError("Pressure level is not lowest model level")
        observed = [np.asarray(da[x].values).ravel() for x in vertical]
        if not observed and "GRIB_level" in da.attrs:
            observed = [np.array([da.attrs["GRIB_level"]])]
        if not observed or any(len(x) != 1 or float(x[0]) != spec["level"] for x in observed):
            raise ValueError("Cannot verify requested model level in payload")
    if spec["level_type"] == "surface" and vertical:
        raise ValueError("Unexpected vertical coordinate for surface diagnostic")
    if spec["level_type"] == "pressure":
        pressure = [x for x in vertical if x in ("pressure_level", "isobaricInhPa")]
        if not pressure or any(
            da[x].size != 1 or float(da[x].values.ravel()[0]) != spec["level"] for x in pressure
        ):
            raise ValueError("Cannot verify requested pressure level")
    for dim in set(da.dims) - {"time", "latitude", "longitude"}:
        if dim not in vertical or da.sizes[dim] != 1:
            raise ValueError(f"Unexpected dimension {dim}; no implicit ensemble/expver merging")
        da = da.isel({dim: 0}, drop=True)
    da = da.drop_vars([x for x in da.coords if x not in ("time", "latitude", "longitude")])
    return da.transpose("time", "latitude", "longitude")


def inspect_array(da, batch, cfg):
    fail, warn = [], []
    if set(da.dims) != {"time", "latitude", "longitude"}:
        return {"status": "FAIL", "failures": ["Wrong dimensions"], "warnings": []}
    spec = cfg["registry"][batch.variable]
    if canonical(da.attrs.get("units", "")) != spec["original_units"]:
        fail.append("Unexpected or missing units")
    times = pd.DatetimeIndex(da.time.values)
    if times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        fail.append("Invalid, duplicate or unordered timestamps")
    p = pd.Period(f"{batch.year}-{batch.month}", "M")
    if batch.temporal_resolution == "monthly":
        if len(times) != 1 or any(times.to_period("M") != p):
            fail.append("Monthly file must contain exactly the requested month")
    else:
        expected = pd.date_range(p.start_time, p.end_time, freq="3h")
        if not times.equals(expected):
            fail.append("Subdaily timestamps do not exactly cover requested 3-hourly month")
    lat, lon = da.latitude.values, da.longitude.values
    for name, v, lower, upper in [("latitude", lat, -90, 90), ("longitude", lon, -180, 360)]:
        if v.ndim != 1 or not np.isfinite(v).all() or len(np.unique(v)) != len(v):
            fail.append(f"Invalid {name} coordinate")
        if np.any((v < lower) | (v > upper)):
            fail.append(f"Out-of-range {name}")
        if len(v) > 1 and not (np.all(np.diff(v) > 0) or np.all(np.diff(v) < 0)):
            fail.append(f"Non-monotonic {name}")
        if len(v) > 1 and not np.allclose(
            np.abs(np.diff(v)), cfg["grid"]["spacing_degrees"], atol=1e-6
        ):
            fail.append(f"Unexpected {name} grid spacing")
    if len(np.unique(np.round(lon % 360, 8))) != len(lon):
        fail.append("Duplicate cyclic longitude")
    area = batch.api_request.get("area")
    if not area:
        if (len(lat), len(lon)) != (cfg["grid"]["latitude"], cfg["grid"]["longitude"]):
            fail.append("Wrong global grid dimensions")
        if not np.isclose(np.min(lat), -90) or not np.isclose(np.max(lat), 90):
            fail.append("Missing polar latitude coverage")
        expected_lon = np.arange(cfg["grid"]["longitude"]) * cfg["grid"]["spacing_degrees"]
        if len(lon) == len(expected_lon) and not np.allclose(
            np.sort(lon % 360), expected_lon, atol=1e-6
        ):
            fail.append("Shifted global longitude grid")
    else:
        n, w, s, e = area
        spacing = cfg["grid"]["spacing_degrees"]
        if abs(max(lat) - n) > spacing or abs(min(lat) - s) > spacing:
            fail.append("Latitude bounds do not match requested area")
        # longitude endpoints may be represented in 0..360 or -180..180.
        for edge in (w, e):
            if np.min(np.abs((lon - edge + 180) % 360 - 180)) > spacing:
                fail.append("Longitude bounds do not match requested area")
    # Reduce lazily; at most a chunk plus boolean masks in memory.
    with __import__("dask").config.set(scheduler="synchronous"):
        missing = float(da.isnull().mean().compute())
        inf = bool(np.isinf(da).any().compute())
        empty_time = bool(da.isnull().all(("latitude", "longitude")).any().compute())
        negative = bool((da < 0).any().compute())
    if inf:
        fail.append("Infinite values")
    if empty_time:
        fail.append("At least one completely missing field")
    if missing > cfg["qc"]["max_missing_fraction"]:
        fail.append("Missing fraction exceeds QC limit")
    elif missing:
        warn.append("Partial missing values")
    if negative:
        warn.append("Negative concentrations/mixing ratios: inspect, not clipped")
    return {
        "status": "FAIL" if fail else "WARNING" if warn else "PASS",
        "failures": fail,
        "warnings": warn,
        "missing_fraction": missing,
        "dimensions": dict(da.sizes),
        "units": da.attrs.get("units"),
        "first_time": str(times.min()),
        "last_time": str(times.max()),
        "latitude_range": [float(min(lat)), float(max(lat))],
        "longitude_range": [float(min(lon)), float(max(lon))],
    }


def validate_file(path, batch, cfg):
    try:
        if Path(path).stat().st_size < cfg["qc"]["minimum_bytes"]:
            raise ValueError("File too small")
        with open_raw(
            path, Path(cfg["data_dir"]) / "interim", chunks={}, netcdf_engine=cfg["netcdf_engine"]
        ) as ds:
            da = normalize(ds, cfg["registry"][batch.variable]).chunk(cfg["chunks"])
            return inspect_array(da, batch, cfg)
    except Exception as e:
        return {"status": "FAIL", "failures": [f"{type(e).__name__}: {e}"], "warnings": []}
