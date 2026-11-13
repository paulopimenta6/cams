"""Separate CAMS greenhouse-gas inversion archive for daily CH4 profiles."""

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import dask
import numpy as np
import pandas as pd
import xarray as xr
from filelock import FileLock

from .catalog import CatalogError, choices, fetch_catalog
from .downloader import download_batch, safe_error
from .extraction import extract_point, save_table, subset_bbox
from .maps import plot_map
from .requests import Batch
from .storage import Manifest, now, sha256
from .validation import open_raw

SOURCE = "GHG_INVERSION"
DATASET = "cams-global-greenhouse-gas-inversion"
FILE_RE = re.compile(r"cams73_(latest|v\d+r\d+)_ch4_conc_first_guess_dm_(\d{6})\.nc$")
SAMPLE_MONTH_BYTES = 536_685_448  # The inspected 30-day September 2024 file.
LOG = logging.getLogger("camsaq.ch4")


def source_config(cfg):
    """Use a separate manifest while retaining the project's data and API settings."""
    out = dict(cfg)
    out["metadata_dir"] = str(Path(cfg["metadata_dir"]) / "ghg_inversion")
    return out


def manifest(cfg):
    return Manifest(Path(source_config(cfg)["metadata_dir"]) / "downloads.sqlite")


def fetch_ch4_catalog(cfg):
    return fetch_catalog(cfg, "daily_mean", source=SOURCE)


def _request(period, version, observations):
    if observations != "first_guess":
        raise ValueError("Only the inspected first_guess CH4 variant is supported")
    p = pd.Period(period, freq="M")
    return {
        "variable": ["methane"],
        "quantity": ["concentration"],
        "input_observations": [observations],
        "time_aggregation": ["daily_mean"],
        "version": [version],
        "year": [str(p.year)],
        "month": [f"{p.month:02d}"],
    }


def _check_catalog(snap, request):
    for field, selected in request.items():
        if not set(selected) <= choices(snap, field):
            raise CatalogError(f"GHG inversion form does not offer {field}={selected}")
    if not any(
        all(set(selected) <= set(row.get(field, [])) for field, selected in request.items())
        for row in snap["constraints"]
    ):
        raise CatalogError("GHG inversion constraints reject this exact combination")


def build_batch(cfg, period, version="v25r1", observations="first_guess", snap=None):
    p = pd.Period(period, freq="M")
    request = _request(p, version, observations)
    if snap is not None:
        _check_catalog(snap, request)
    digest = hashlib.sha256(json.dumps([DATASET, request], sort_keys=True).encode()).hexdigest()
    path = (
        Path(cfg["data_dir"])
        / "raw/ghg_inversion/ch4"
        / observations
        / version
        / str(p.year)
        / f"{p.month:02d}"
        / f"ch4_{p}_{digest[:12]}.nc"
    )
    return Batch(
        dataset=DATASET,
        variable="ch4",
        year=p.year,
        month=p.month,
        temporal_resolution="daily_mean",
        level_type="model_profile",
        level=None,
        api_request=request,
        filepath=str(path),
        key=digest,
        catalog_sha256=snap.get("sha256", "local-import") if snap else "local-import",
    )


def plan_batches(cfg, snap, start, end=None, version="v25r1", observations="first_guess"):
    if not start:
        raise ValueError("A start month is required to avoid an unintended bulk download")
    first, last = pd.Period(start, "M"), pd.Period(end or start, "M")
    if first > last:
        raise ValueError("start must not be after end")
    return [
        build_batch(cfg, period, version, observations, snap)
        for period in pd.period_range(first, last, freq="M")
    ]


def estimate(batches, storage_copies=4):
    days = sum(pd.Period(f"{b.year}-{b.month:02d}", "M").days_in_month for b in batches)
    raw = round(SAMPLE_MONTH_BYTES * days / 30)
    return {
        "files": len(batches),
        "days": days,
        "estimated_raw_GiB": round(raw / 2**30, 3),
        "planning_disk_GiB": round(raw * storage_copies / 2**30, 3),
        "basis": "536685448-byte, 30-day September 2024 sample; actual ADS assets may differ",
    }


def _grid_check(ds, cfg, failures):
    grid = cfg["ghg_inversion"]["grid"]
    lat, lon = ds.latitude.values, ds.longitude.values
    if (len(lat), len(lon)) != (grid["latitude"], grid["longitude"]):
        failures.append("Wrong GHG inversion grid dimensions")
        return
    for name, values in (("latitude", lat), ("longitude", lon)):
        if not np.isfinite(values).all() or not np.all(np.diff(values) > 0):
            failures.append(f"Invalid {name} coordinates")
        elif not np.allclose(np.diff(values), grid["spacing_degrees"], atol=1e-6):
            failures.append(f"Wrong {name} grid spacing")
    if grid.get("global", True):
        spacing = grid["spacing_degrees"]
        if not np.allclose(lat, -90 + spacing / 2 + np.arange(len(lat)) * spacing):
            failures.append("Unexpected global latitude centres")
        if not np.allclose(lon, -180 + spacing / 2 + np.arange(len(lon)) * spacing):
            failures.append("Unexpected global longitude centres")


def _inspect_ch4(ds, batch, cfg):
    failures, warnings = [], []
    if "CH4" not in ds.data_vars:
        raise ValueError("CH4 data variable absent")
    a = ds["CH4"]
    if a.dims != ("time", "level", "latitude", "longitude"):
        failures.append("CH4 must have time, level, latitude, longitude dimensions")
    if a.attrs.get("standard_name") != "mole_fraction_of_methane_in_air":
        failures.append("CH4 CF identity changed")
    if a.attrs.get("units") != "1e-9" or "dry air" not in a.attrs.get("long_name", ""):
        failures.append("CH4 must be a dry-air mole fraction in 1e-9")
    release = str(ds.attrs.get("release", ""))
    if not re.fullmatch(r"v\d+r\d+", release):
        failures.append("Missing or invalid CAMS release")
    requested_version = batch.api_request["version"][0]
    if requested_version != "latest" and release != requested_version:
        failures.append("CAMS release differs from requested version")
    if "TM5" not in str(ds.attrs.get("source", "")):
        failures.append("Unexpected simulation source")
    p = pd.Period(f"{batch.year}-{batch.month:02d}", "M")
    expected = pd.date_range(p.start_time, periods=p.days_in_month, freq="D")
    times = pd.DatetimeIndex(ds.time.values)
    if not times.equals(expected):
        failures.append("Daily means must cover exactly every day of the requested month")
    _grid_check(ds, cfg, failures)
    levels = np.asarray(ds.level.values)
    if not np.array_equal(levels, np.arange(1, cfg["ghg_inversion"]["levels"] + 1)):
        failures.append("Unexpected or reordered model levels")
    required = {
        "cell_area": ("latitude", "longitude"),
        "ps": ("time", "latitude", "longitude"),
        "hyam": ("level",),
        "hybm": ("level",),
        "altitude": ("time", "hlevel", "latitude", "longitude"),
    }
    for name, dims in required.items():
        if name not in ds or ds[name].dims != dims:
            failures.append(f"Missing or malformed auxiliary field {name}")
    if "hybm" in ds and not float(ds.hybm[0]) > float(ds.hybm[-1]):
        failures.append("Lowest model level must be first")
    if "hlevel" in ds.sizes and ds.sizes["hlevel"] != ds.sizes.get("level", -2) + 1:
        failures.append("Hybrid layer interfaces do not match the levels")
    if failures:
        return {"status": "FAIL", "failures": failures, "warnings": warnings}
    with dask.config.set(scheduler="synchronous"):
        minimum, maximum, finite, area_positive, pressure_positive = dask.compute(
            a.min(), a.max(), np.isfinite(a).all(), (ds.cell_area > 0).all(), (ds.ps > 0).all()
        )
    minimum, maximum = float(minimum), float(maximum)
    if not bool(finite) or minimum <= 0:
        failures.append("CH4 contains missing, infinite or nonpositive values")
    if not bool(area_positive) or not bool(pressure_positive):
        failures.append("Invalid area or surface pressure")
    if maximum > 5000:
        warnings.append("CH4 exceeds 5000 ppb in some cells; review scientific quality")
    return {
        "status": "FAIL" if failures else "WARNING" if warnings else "PASS",
        "failures": failures,
        "warnings": warnings,
        "resolved_release": release,
        "dimensions": dict(a.sizes),
        "units": "1e-9 mol/mol dry air (ppb)",
        "first_time": str(times.min()),
        "last_time": str(times.max()),
        "minimum_ppb": minimum,
        "maximum_ppb": maximum,
    }


def validate_file(path, batch, cfg):
    try:
        if Path(path).stat().st_size < cfg["qc"]["minimum_bytes"]:
            raise ValueError("File too small")
        with open_raw(
            path,
            Path(cfg["data_dir"]) / "interim",
            chunks=cfg["ghg_inversion"]["chunks"],
            netcdf_engine=cfg["netcdf_engine"],
        ) as ds:
            return _inspect_ch4(ds, batch, cfg)
    except Exception as exc:
        return {"status": "FAIL", "failures": [f"{type(exc).__name__}: {exc}"], "warnings": []}


def import_file(cfg, source):
    source = Path(source).resolve()
    match = FILE_RE.fullmatch(source.name)
    if not match:
        raise ValueError("Expected a cams73_*_ch4_conc_first_guess_dm_YYYYMM.nc file")
    version, year_month = match.groups()
    batch = build_batch(cfg, f"{year_month[:4]}-{year_month[4:]}", version)
    qc = validate_file(source, batch, cfg)
    if qc["status"] == "FAIL":
        raise ValueError("Local CH4 file failed QC: " + "; ".join(qc["failures"]))
    checksum = sha256(source)
    target = Path(batch.filepath)
    target.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(target) + ".lock"):
        if target.exists():
            if sha256(target) != checksum:
                raise ValueError("Managed CH4 file exists with a different checksum")
        else:
            temp = target.with_name(target.name + ".part")
            if temp.exists():
                temp.unlink()
            shutil.copyfile(source, temp)
            if sha256(temp) != checksum:
                raise ValueError("CH4 copy checksum mismatch")
            os.replace(temp, target)
        m = manifest(cfg)
        m.add(batch)
        qc.update(request_origin="local_import_reconstructed", source_filename=source.name)
        m.set(
            batch.key,
            "validated",
            checksum=checksum,
            filesize=target.stat().st_size,
            download_date=now(),
            qc_json=json.dumps(qc),
            error=None,
        )
    return batch, qc


def _release(row):
    return json.loads(row.get("qc_json") or "{}").get("resolved_release")


def processed_rows(cfg: dict, version: str = "v25r1", observations: str = "first_guess",
                   start: str | None = None, end: str | None = None) -> list[dict]:
    """Read verified CH4 partitions in a month range without changing the manifest."""
    first, last = _month_bounds(start, end)
    database = Path(source_config(cfg)["metadata_dir"]) / "downloads.sqlite"
    if not database.is_file():
        return []
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        all_rows = [dict(row) for row in conn.execute("SELECT * FROM downloads")]
    rows = [
        row
        for row in all_rows
        if row["status"] == "processed"
        and row["dataset"] == DATASET
        and _release(row) == version
        and json.loads(row["api_request"])["input_observations"] == [observations]
        and (first is None or (row["year"], row["month"]) >= (first.year, first.month))
        and (last is None or (row["year"], row["month"]) <= (last.year, last.month))
    ]
    for row in rows:
        path = Path(row["processed_path"] or "")
        if not path.is_file() or sha256(path) != row["processed_checksum"]:
            raise ValueError("Processed CH4 checksum mismatch")
    if len({(r["year"], r["month"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate processed CH4 months for one release")
    return rows


def _month_bounds(start, end):
    def parse(value):
        if value is None:
            return None
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(value)):
            raise ValueError(f"Invalid month {value!r}; expected YYYY-MM")
        return pd.Period(value, freq="M")

    first, last = parse(start), parse(end)
    if first is not None and last is not None and first > last:
        raise ValueError("start must not be after end")
    return first, last


def _available_day_range(cfg, version):
    database = Path(source_config(cfg)["metadata_dir"]) / "downloads.sqlite"
    if not database.is_file():
        return None
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT year,month,qc_json FROM downloads WHERE status='processed'"
        ).fetchall()
    periods = sorted(pd.Period(f"{year}-{month:02d}", freq="M")
                     for year, month, qc in rows
                     if json.loads(qc or "{}").get("resolved_release") == version)
    return (periods[0].start_time.date(), periods[-1].end_time.date(),
            {str(period) for period in periods}) if periods else None


def process_batch(cfg, batch):
    m = manifest(cfg)
    row = m.get(batch.key)
    if not row or not m.intact(row):
        raise ValueError("Processing requires a checksum-verified CH4 original")
    qc = json.loads(row["qc_json"] or "{}")
    if qc.get("status") == "FAIL" or not qc.get("resolved_release"):
        raise ValueError("CH4 validation and release are required")
    release = qc["resolved_release"]
    folder = (
        Path(cfg["data_dir"])
        / "processed/ghg_inversion/ch4/first_guess"
        / release
        / "daily_mean"
        / str(batch.year)
    )
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"{batch.month:02d}_{batch.key[:12]}_{row['checksum'][:12]}.nc"
    with FileLock(str(output) + ".lock"):
        if (
            output.is_file()
            and row.get("processed_path") == str(output)
            and row.get("processed_checksum") == sha256(output)
        ):
            if row["status"] != "processed":
                m.set(batch.key, "processed", processing_error=None)
            return output
        with open_raw(
            batch.filepath,
            Path(cfg["data_dir"]) / "interim",
            chunks=cfg["ghg_inversion"]["chunks"],
            netcdf_engine=cfg["netcdf_engine"],
        ) as raw:
            a = raw.CH4.rename("ch4")
            a.attrs.update(
                original_units="1e-9",
                units="ppb",
                mole_fraction_basis="dry_air",
                conversion_equation="1 source unit (1e-9 mol/mol) = 1 ppb",
                source_level_type="model_profile",
                cell_methods="time: mean (daily); area: mean",
            )
            keep = (
                "cell_area",
                "ps",
                "hyam",
                "hybm",
                "hyai",
                "hybi",
                "altitude",
                "longitude_bounds",
                "latitude_bounds",
            )
            out = xr.Dataset({"ch4": a, **{name: raw[name] for name in keep if name in raw}})
            out.attrs = {
                "source": SOURCE,
                "dataset": DATASET,
                "release": release,
                "input_observations": "first_guess",
                "time_aggregation": "daily_mean",
                "api_request": json.dumps(batch.api_request, sort_keys=True),
                "request_origin": qc.get("request_origin", "ADS"),
                "raw_sha256": row["checksum"],
                "raw_file": str(batch.filepath),
                "processed_at": now(),
                "history": "Decoded packed CH4; retained 34 model levels and vertical auxiliaries",
            }
            for variable in out.variables:
                out[variable].encoding = {}
            encoding = {
                name: {
                    "zlib": True,
                    "complevel": 4,
                    "dtype": "float32",
                    "chunksizes": tuple(
                        min(out.sizes[dim], cfg["ghg_inversion"]["chunks"].get(dim, 1))
                        for dim in out[name].dims
                    ),
                }
                for name in ("ch4", "ps", "altitude", "cell_area")
                if name in out
            }
            temp = output.with_name(output.name + ".part")
            with dask.config.set(scheduler="synchronous"):
                out.to_netcdf(temp, engine=cfg["netcdf_engine"], encoding=encoding)
        with xr.open_dataset(temp, engine=cfg["netcdf_engine"]) as check:
            expected_sizes = {
                "time": pd.Period(f"{batch.year}-{batch.month:02d}").days_in_month,
                "level": cfg["ghg_inversion"]["levels"],
                "latitude": cfg["ghg_inversion"]["grid"]["latitude"],
                "longitude": cfg["ghg_inversion"]["grid"]["longitude"],
            }
            if check.ch4.sizes != expected_sizes:
                raise ValueError("Processed CH4 dimensions changed")
            if not np.isfinite(check.ch4.isel(time=0, level=0)).all().item():
                raise ValueError("Processed CH4 first field is not finite")
        os.replace(temp, output)
        m.set(batch.key, "processed", processed_path=str(output), processed_checksum=sha256(output))
    return output


def _store_root(cfg, version, observations="first_guess"):
    return (Path(cfg["data_dir"]) / "processed/ghg_inversion/ch4" / observations
            / version / "daily_mean/zarr")


def consolidate(cfg, version="v25r1", observations="first_guess"):
    rows = processed_rows(cfg, version, observations)
    if not rows:
        raise ValueError("No processed CH4 months for this release")
    root = _store_root(cfg, version, observations)
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / "writer.lock")):
        index = {"source": SOURCE, "dataset": DATASET, "release": version,
                 "input_observations": observations, "temporal_resolution": "daily_mean",
                 "updated_at": now(), "years": {}}
        for year in sorted({r["year"] for r in rows}):
            subset = sorted((r for r in rows if r["year"] == year), key=lambda r: r["month"])
            payload = json.dumps([(r["key"], r["processed_checksum"]) for r in subset])
            digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
            name = f"{year}-{digest}.zarr"
            target = root / name
            if not target.exists():
                with xr.open_mfdataset([r["processed_path"] for r in subset],
                                       engine=cfg["netcdf_engine"], combine="by_coords",
                                       chunks=cfg["ghg_inversion"]["chunks"],
                                       data_vars="minimal", coords="minimal",
                                       compat="equals", join="exact") as ds:
                    ds.attrs.update(source=SOURCE, release=version, input_observations=observations,
                                    months_present=json.dumps([r["month"] for r in subset]))
                    for variable in ds.variables:
                        ds[variable].encoding = {}
                    temp = root / (name + ".part-" + uuid.uuid4().hex)
                    with dask.config.set(scheduler="synchronous"):
                        ds.to_zarr(temp, mode="w", consolidated=True, zarr_format=2)
                    with xr.open_zarr(temp, consolidated=True) as check:
                        if check.ch4.sizes != ds.ch4.sizes:
                            raise ValueError("CH4 Zarr dimensions changed")
                    os.replace(temp, target)
            index["years"][str(year)] = {"path": name, "generation": digest,
                                          "months": [r["month"] for r in subset]}
        temp_index = root / "index.json.part"
        temp_index.write_text(json.dumps(index, indent=2))
        os.replace(temp_index, root / "index.json")
    return root / "index.json"


@contextmanager
def open_processed(cfg: dict, version: str = "v25r1", observations: str = "first_guess",
                   start: str | None = None,
                   end: str | None = None) -> Iterator[tuple[xr.Dataset, list[dict]]]:
    rows = sorted(
        processed_rows(cfg, version, observations, start, end),
        key=lambda r: (r["year"], r["month"]),
    )
    if not rows:
        raise ValueError("No verified processed CH4 files for this release")
    chunks = {**cfg["ghg_inversion"]["chunks"],
              "time": max(31, cfg["ghg_inversion"]["chunks"].get("time", 1))}
    with xr.open_mfdataset(
        [r["processed_path"] for r in rows], engine=cfg["netcdf_engine"],
        combine="by_coords", chunks=chunks, data_vars="minimal", coords="minimal",
        compat="equals", join="exact",
    ) as ds:
        yield ds, rows


def complete_months(a: xr.DataArray) -> list[pd.Period]:
    """Return months with every daily timestamp exactly once."""
    times = pd.DatetimeIndex(a.time.values)
    return [
        period
        for period in sorted(set(times.to_period("M")))
        if times[times.to_period("M") == period].equals(
            pd.date_range(period.start_time, periods=period.days_in_month, freq="D")
        )
    ]


def complete_years(months: list[pd.Period]) -> list[int]:
    """Return calendar years containing twelve complete months."""
    return [
        year for year in sorted({p.year for p in months})
        if {p.month for p in months if p.year == year} == set(range(1, 13))
    ]


def monthly_field(a: xr.DataArray, period: pd.Period) -> xr.DataArray:
    return a.sel(time=str(period)).mean("time", keep_attrs=True)


def annual_field(a: xr.DataArray, year: int) -> xr.DataArray:
    return a.sel(time=str(year)).mean("time", keep_attrs=True)


def period_field(a: xr.DataArray) -> xr.DataArray:
    return a.mean("time", keep_attrs=True)


def std_field(a: xr.DataArray) -> xr.DataArray:
    """Population standard deviation over available daily means (ddof=0)."""
    return a.std("time", ddof=0, keep_attrs=True)


def monthly_series(a: xr.DataArray) -> xr.DataArray:
    parts = [monthly_field(a, p).expand_dims(time=[p.start_time]) for p in complete_months(a)]
    return xr.concat(parts, dim="time") if parts else a.isel(time=slice(0, 0))


def annual_series(a: xr.DataArray) -> xr.DataArray:
    years = complete_years(complete_months(a))
    parts = [annual_field(a, y).expand_dims(time=[pd.Timestamp(y, 1, 1)]) for y in years]
    return xr.concat(parts, dim="time") if parts else a.isel(time=slice(0, 0))


def reference_cycle(a: xr.DataArray, years: list[int]) -> xr.DataArray:
    """Equal weight per complete reference year within each calendar month."""
    if len(years) < 2 or not set(years) <= set(complete_years(complete_months(a))):
        raise ValueError("Reference requires at least two complete calendar years")
    fields = []
    for month in range(1, 13):
        yearly = [monthly_field(a, pd.Period(f"{year}-{month:02d}", freq="M"))
                  for year in years]
        fields.append(xr.concat(yearly, dim="reference_year").mean(
            "reference_year", keep_attrs=True
        ).expand_dims(month=[month]))
    return xr.concat(fields, dim="month")


def anomaly_field(field: xr.DataArray, reference: xr.DataArray) -> xr.DataArray:
    result = field - reference
    result.attrs = {**field.attrs, "units": "ppb", "statistic": "CH4 anomaly"}
    return result


def anomaly_series(a: xr.DataArray, reference: xr.DataArray) -> xr.DataArray:
    monthly = monthly_series(a)
    return monthly.groupby("time.month") - reference


def _annual_reference(reference: xr.DataArray, year: int) -> xr.DataArray:
    days = xr.DataArray(
        [pd.Period(f"{year}-{m:02d}", freq="M").days_in_month for m in range(1, 13)],
        dims="month", coords={"month": range(1, 13)},
    )
    return reference.weighted(days).mean("month", keep_attrs=True)


def _coverage(a, start=None, end=None, date=None):
    times = pd.DatetimeIndex(a.time.values)
    if date:
        expected = pd.DatetimeIndex([pd.Timestamp(date)])
    else:
        first = pd.Period(start, "M").start_time if start else times.min().to_period("M").start_time
        last = (pd.Period(end, "M").end_time.normalize() if end
                else times.max().to_period("M").end_time.normalize())
        expected = pd.date_range(first, last, freq="D")
    return {"days_available": len(times), "days_expected": len(expected),
            "missing_days": [str(t.date()) for t in expected.difference(times)]}


def _map_bounds(fields, family, scale):
    if scale == "shared":
        values = np.concatenate([field.values.ravel() for _, _, field in fields])
        lo, hi = np.percentile(values, [2, 98])
        bounds = [(float(lo), float(hi))] * len(fields)
    else:
        bounds = [tuple(map(float, np.percentile(field.values, [2, 98])))
                  for _, _, field in fields]
    if family == "anomaly":
        bounds = [(-max(abs(lo), abs(hi)) or -1.0, max(abs(lo), abs(hi)) or 1.0)
                  for lo, hi in bounds]
    for lo, hi in bounds:
        if not np.isfinite([lo, hi]).all() or lo >= hi:
            raise ValueError(f"CH4 {family} map has no finite increasing colour range")
    return bounds


def _check_map_overwrite(path, name, family, period, previous, current):
    if not path.is_file():
        return
    prior_map = next((item for item in (previous or {}).get("maps", [])
                      if item.get("file") == name), None)
    same = (prior_map is not None
            and prior_map.get("family") == family
            and prior_map.get("period") == period
            and previous.get("release") == current["release"]
            and previous.get("level") == current["level"]
            and previous.get("bbox") == current["bbox"])
    if family == "latest":
        same = same and previous.get("selected_months") == current["selected_months"]
    if family in {"climatology", "anomaly"}:
        same = (same and previous.get("baseline") == current["baseline"]
                and previous.get("reference_years") == current["reference_years"])
    if not same:
        raise ValueError(f"Refusing to overwrite {path}: existing PNG has another provenance")


def analyze(
    cfg: dict, level: int, output: str | Path, version: str = "v25r1",
    observations: str = "first_guess", lat: float = -23.5505, lon: float = -46.6333,
    bbox=None, maps: bool = True, start: str | None = None, end: str | None = None,
    date: str | None = None, map_families: list[str] | None = None,
    baseline_start: str | None = None, baseline_end: str | None = None,
    scale: str = "shared",
) -> dict:
    """Analyze verified CH4 days; maps and tables use the same selected interval."""
    _month_bounds(start, end)
    if date and (start or end):
        raise ValueError("date is exclusive with start/end")
    if date:
        bounds = _available_day_range(cfg, version)
        try:
            valid_date = (bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date))
                          and pd.Timestamp(date).strftime("%Y-%m-%d") == date)
        except ValueError:
            valid_date = False
        if not valid_date or (bounds and (not bounds[0] <= pd.Timestamp(date).date() <= bounds[1]
                                          or date[:7] not in bounds[2])):
            detail = f"; first_day={bounds[0]}, last_day={bounds[1]}" if bounds else ""
            raise ValueError(f"Date {date} unavailable; expected YYYY-MM-DD{detail}")
    if scale not in ("shared", "per-map"):
        raise ValueError("scale must be shared or per-map")
    families = list(map_families if map_families is not None else (["day"] if date else ["latest"]))
    if not maps:
        families = []
    valid_families = {"latest", "day", "monthly", "annual", "period", "climatology",
                      "anomaly", "std", "all"}
    if not set(families) <= valid_families:
        raise ValueError("Unknown CH4 map family")
    all_requested = "all" in families
    if all_requested:
        families = ["day", "monthly", "annual", "period", "climatology", "anomaly", "std"]
    if "anomaly" in families and not all_requested and not (baseline_start and baseline_end):
        raise ValueError("anomaly maps require --baseline-start and --baseline-end")
    if bool(baseline_start) != bool(baseline_end):
        raise ValueError("baseline-start and baseline-end must be provided together")
    _month_bounds(baseline_start, baseline_end)
    month = date[:7] if date else None
    with open_processed(cfg, version, observations, start or month, end or month) as (ds, rows):
        if level not in ds.level.values:
            raise ValueError(f"Model level {level} unavailable")
        full = ds.ch4.sel(level=level, drop=True)
        available = pd.DatetimeIndex(full.time.values)
        if date:
            if pd.Timestamp(date) not in available:
                raise ValueError(
                    f"Date {date} unavailable; first_day={available.min().date()}, "
                    f"last_day={available.max().date()}"
                )
            full = full.sel(time=[date])
        a = subset_bbox(full, *bbox) if bbox is not None else full
        if a.nbytes <= 64 * 1024**2:
            with dask.config.set(scheduler="synchronous"):
                a = a.compute()
            if bbox is None:
                full = a
        area = subset_bbox(ds.cell_area, *bbox) if bbox is not None else ds.cell_area
        months = complete_months(a)
        years = complete_years(months)
        seen_months = sorted(set(pd.DatetimeIndex(a.time.values).to_period("M")))
        seen_years = sorted({p.year for p in seen_months})
        provenance = {"source": SOURCE, "release": version,
                      "input_observations": observations, "level": level,
                      "units": "ppb dry-air mole fraction", "bbox": bbox,
                      "processed_sha256": [r["processed_checksum"] for r in rows]}
        output = Path(output)
        previous_report = (
            json.loads((output / "analysis.json").read_text(encoding="utf-8"))
            if (output / "analysis.json").is_file() else None
        )
        if families and output.is_dir() and any(output.glob("*.png")):
            prior_baseline = (previous_report or {}).get("baseline") or {}
            incompatible = (
                previous_report is None
                or previous_report.get("release") != version
                or previous_report.get("level") != level
                or previous_report.get("bbox") != bbox
                or previous_report.get("selected_months") != [str(p) for p in seen_months]
                or (any(f in families for f in ("anomaly", "climatology"))
                    and (prior_baseline.get("start"), prior_baseline.get("end"))
                    != (baseline_start, baseline_end))
            )
            if incompatible:
                raise ValueError(
                    "Output contains maps from another selection; choose a new directory"
                )
        with dask.config.set(scheduler="synchronous"):
            daily_da = a.weighted(area).mean(("latitude", "longitude"), keep_attrs=True).compute()
            point = extract_point(full, lat, lon).compute()
        output.mkdir(parents=True, exist_ok=True)
        daily = daily_da.to_dataframe(name="ch4_ppb").reset_index()
        daily.attrs = provenance
        save_table(daily, output / "area_daily.csv")
        point_frame = point.to_dataframe(name="ch4_ppb").reset_index()
        point_frame.attrs = {**provenance, **point.attrs}
        save_table(point_frame, output / "point_daily.csv")

        monthly = pd.DataFrame(
            [{"time": p.start_time, "ch4_ppb": float(daily_da.sel(time=str(p)).mean()),
              "days": p.days_in_month} for p in months],
            columns=["time", "ch4_ppb", "days"],
        )
        monthly.attrs = {**provenance, "aggregation": "complete calendar months only"}
        save_table(monthly, output / "area_monthly.csv")
        if years:
            annual = pd.DataFrame(
                [{"year": y, "ch4_ppb": float(daily_da.sel(time=str(y)).mean()),
                  "days": 366 if pd.Timestamp(y, 12, 31).is_leap_year else 365} for y in years]
            )
            annual.attrs = {**provenance, "aggregation": "complete calendar years only"}
            save_table(annual, output / "area_annual.csv")

        reference = None
        reference_years = []
        baseline_rows = []
        if baseline_start and baseline_end:
            try:
                with open_processed(cfg, version, observations, baseline_start, baseline_end) as (
                    baseline_ds, baseline_rows
                ):
                    baseline_a = baseline_ds.ch4.sel(level=level, drop=True)
                    if bbox is not None:
                        baseline_a = subset_bbox(baseline_a, *bbox)
                    if baseline_a.nbytes <= 64 * 1024**2:
                        with dask.config.set(scheduler="synchronous"):
                            baseline_a = baseline_a.compute()
                    reference_years = complete_years(complete_months(baseline_a))
                    if len(reference_years) >= 2:
                        with dask.config.set(scheduler="synchronous"):
                            reference = reference_cycle(baseline_a, reference_years).compute()
            except ValueError as exc:
                if "No verified processed CH4" not in str(exc):
                    raise
        else:
            reference_years = years
            if len(years) >= 2:
                with dask.config.set(scheduler="synchronous"):
                    reference = reference_cycle(a, years).compute()
        baseline_info = (
            {"start": baseline_start, "end": baseline_end,
             "complete_years": reference_years, "reference_years": reference_years,
             "processed_sha256": [r["processed_checksum"] for r in baseline_rows],
             "annual_weighting": "target calendar year's month lengths"}
            if baseline_start and baseline_end else None
        )
        if reference is not None:
            with dask.config.set(scheduler="synchronous"):
                area_reference = (
                    reference.weighted(area).mean(("latitude", "longitude"), keep_attrs=True)
                    .compute()
                )
            cycle_frame = area_reference.to_dataframe(name="ch4_ppb").reset_index()
            cycle_frame["n_years"] = len(reference_years)
            cycle_frame.attrs = {**provenance, "reference_years": reference_years,
                                 "baseline": baseline_info}
            save_table(cycle_frame, output / "area_climatology.csv")
            monthly_anomaly = monthly.copy()
            monthly_anomaly["ch4_ppb"] -= monthly_anomaly["time"].dt.month.map(
                dict(zip(cycle_frame.month, cycle_frame.ch4_ppb))
            )
            monthly_anomaly.attrs = cycle_frame.attrs
            save_table(monthly_anomaly, output / "area_anomaly_monthly.csv")
            if years:
                annual_anomaly = annual.copy()
                annual_anomaly["ch4_ppb"] = [
                    float(daily_da.sel(time=str(y)).mean()) -
                    float(_annual_reference(area_reference, y)) for y in years
                ]
                annual_anomaly.attrs = cycle_frame.attrs
                save_table(annual_anomaly, output / "area_anomaly_annual.csv")

        fields = {family: [] for family in families}
        skipped = []
        period_name = f"{seen_months[0]}_{seen_months[-1]}"
        latest_day = pd.Timestamp(a.time.values[-1])
        if "latest" in fields:
            fields["latest"].append(("latest_day.png", str(latest_day.date()), a.isel(time=-1)))
            if months:
                fields["latest"].append(("latest_complete_month.png", str(months[-1]),
                                         monthly_field(a, months[-1])))
        if "day" in fields:
            fields["day"].append((f"day_{latest_day:%Y-%m-%d}.png",
                                  str(latest_day.date()), a.isel(time=-1)))
        if "monthly" in fields:
            fields["monthly"] = [(f"month_{p}.png", str(p), monthly_field(a, p)) for p in months]
            for p in seen_months:
                if p not in months:
                    skipped.append({"family": "monthly", "period": str(p),
                                    "reason": "month lacks one or more daily values"})
        if "annual" in fields:
            fields["annual"] = [(f"annual_{y}.png", str(y), annual_field(a, y)) for y in years]
            for y in seen_years:
                if y not in years:
                    skipped.append({"family": "annual", "period": str(y),
                                    "reason": "year lacks twelve complete months"})
        if "period" in fields:
            fields["period"] = [(f"period_{period_name}.png", period_name, period_field(a))]
        if "std" in fields:
            if a.sizes["time"] >= 2:
                fields["std"] = [(f"std_period_{period_name}.png", period_name, std_field(a))]
            else:
                skipped.append({"family": "std", "period": period_name,
                                "reason": "at least two days are required"})
        if "climatology" in fields:
            if reference is None:
                skipped.append({"family": "climatology", "period": period_name,
                                "reason": "at least two complete reference years are required"})
            else:
                fields["climatology"] = [
                    (f"climatology_{m:02d}.png", f"calendar month {m:02d}",
                     reference.sel(month=m, drop=True)) for m in range(1, 13)
                ]
        if "anomaly" in fields:
            if reference is None or not (baseline_start and baseline_end):
                skipped.append({"family": "anomaly", "period": period_name,
                                "reason": "explicit baseline with two complete years is required"})
            else:
                for p in months:
                    fields["anomaly"].append((
                        f"anomaly_month_{p}.png", str(p),
                        anomaly_field(monthly_field(a, p),
                                      reference.sel(month=p.month, drop=True)),
                    ))
                for y in years:
                    fields["anomaly"].append((f"anomaly_annual_{y}.png", str(y),
                                              anomaly_field(annual_field(a, y),
                                                            _annual_reference(reference, y))))
                if not fields["anomaly"]:
                    skipped.append({"family": "anomaly", "period": period_name,
                                    "reason": "no complete target month or year"})

        rendered, map_scales, map_scale = [], {}, None
        for family, candidates in fields.items():
            if not candidates:
                continue
            with dask.config.set(scheduler="synchronous"):
                computed = [(name, period, field.compute()) for name, period, field in candidates]
            if family == "latest":
                reference_field = computed[-1][2]
                lower, upper = np.percentile(reference_field.values, [2, 98])
                if not np.isfinite([lower, upper]).all() or lower >= upper:
                    raise ValueError("CH4 latest map has no finite increasing colour range")
                bounds = [(float(lower), float(upper))] * len(computed)
                map_scale = {"lower_ppb": float(lower), "upper_ppb": float(upper),
                             "method": "2nd and 98th percentiles of latest complete-month field"
                             if months else "2nd and 98th percentiles of latest daily field"}
            else:
                bounds = _map_bounds(computed, family, scale)
            for (name, period, field), (lower, upper) in zip(computed, bounds):
                method = "legacy latest shared" if family == "latest" else f"{scale} p2/p98"
                title = (
                    f"CH4 {version}, level {level}, anomaly vs "
                    f"{baseline_start}..{baseline_end}, {period}"
                    if family == "anomaly"
                    else f"CH4 {version}, level {level}, {period} (clipped scale)"
                )
                _check_map_overwrite(
                    output / name, name, family, period, previous_report,
                    {"release": version, "level": level, "bbox": bbox,
                     "selected_months": [str(p) for p in seen_months],
                     "baseline": baseline_info, "reference_years": reference_years},
                )
                plot_map(field, output / name, title=title, anomaly=family == "anomaly",
                         vmin=lower, vmax=upper)
                entry = {"file": name, "family": family, "period": period,
                         "vmin": lower, "vmax": upper, "scale_method": method}
                rendered.append(entry)
                map_scales[name] = {**entry, "method": method}
        report = {
            **provenance, "schema_version": 2, "requested_start": start,
            "requested_end": end, "requested_date": date,
            "selected_months": [str(p) for p in seen_months], "selected_years": seen_years,
            "first_day": str(a.time.values[0]), "last_day": str(a.time.values[-1]),
            "complete_months": [str(p) for p in months], "complete_years": years,
            "baseline": baseline_info, "maps": rendered, "skipped": skipped,
            "reference_years": reference_years if reference is not None else [],
            "map_scales": map_scales, "coverage": _coverage(a, start, end, date),
            "files": [r["processed_path"] for r in rows],
            "interpretation": "model layer, not a station observation or surface flux; "
                              "temporal standard deviation uses ddof=0",
            "map_color_scale": map_scale,
        }
        temporary = output / "analysis.json.part"
        temporary.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        os.replace(temporary, output / "analysis.json")
        LOG.info("CH4 analysis: %d months, %d maps, %d skipped",
                 len(seen_months), len(rendered), len(skipped))
        return report


def download(cfg, batches, client=None):
    c = source_config(cfg)
    results = []
    for batch in batches:
        result = download_batch(c, batch, client=client, validator=validate_file)
        if result["status"] != "failed":
            try:
                result["processed"] = str(process_batch(cfg, batch))
            except Exception as exc:
                error = safe_error(exc)
                manifest(cfg).set(batch.key, "validated", processing_error=error)
                result.update(status="processing_failed", error=error)
        results.append(result)
        if result["status"] in ("failed", "processing_failed"):
            break
    return results
