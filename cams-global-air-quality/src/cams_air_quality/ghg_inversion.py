"""Separate CAMS greenhouse-gas inversion archive for daily CH4 profiles."""

import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

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


def _processed_rows(cfg, version, observations="first_guess"):
    rows = [
        row
        for row in manifest(cfg).rows()
        if row["status"] == "processed"
        and row["dataset"] == DATASET
        and _release(row) == version
        and json.loads(row["api_request"])["input_observations"] == [observations]
    ]
    for row in rows:
        path = Path(row["processed_path"] or "")
        if not path.is_file() or sha256(path) != row["processed_checksum"]:
            raise ValueError("Processed CH4 checksum mismatch")
    if len({(r["year"], r["month"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate processed CH4 months for one release")
    return rows


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
            if check.ch4.sizes != {"time": pd.Period(f"{batch.year}-{batch.month:02d}").days_in_month,
                                   "level": cfg["ghg_inversion"]["levels"],
                                   "latitude": cfg["ghg_inversion"]["grid"]["latitude"],
                                   "longitude": cfg["ghg_inversion"]["grid"]["longitude"]}:
                raise ValueError("Processed CH4 dimensions changed")
            if not np.isfinite(check.ch4.isel(time=0, level=0)).all().item():
                raise ValueError("Processed CH4 first field is not finite")
        os.replace(temp, output)
        m.set(batch.key, "processed", processed_path=str(output), processed_checksum=sha256(output))
    return output


def _store_root(cfg, version, observations="first_guess"):
    return Path(cfg["data_dir"]) / "processed/ghg_inversion/ch4" / observations / version / "daily_mean/zarr"


def consolidate(cfg, version="v25r1", observations="first_guess"):
    rows = _processed_rows(cfg, version, observations)
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
            digest = hashlib.sha256(json.dumps([(r["key"], r["processed_checksum"]) for r in subset]).encode()).hexdigest()[:16]
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
def open_processed(cfg, version="v25r1", observations="first_guess"):
    rows = sorted(_processed_rows(cfg, version, observations), key=lambda r: (r["year"], r["month"]))
    if not rows:
        raise ValueError("No verified processed CH4 files for this release")
    with xr.open_mfdataset([r["processed_path"] for r in rows], engine=cfg["netcdf_engine"],
                           combine="by_coords", chunks=cfg["ghg_inversion"]["chunks"],
                           data_vars="minimal", coords="minimal", compat="equals", join="exact") as ds:
        yield ds, rows


def analyze(cfg, level, output, version="v25r1", observations="first_guess",
            lat=-23.5505, lon=-46.6333, bbox=None, maps=True):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with open_processed(cfg, version, observations) as (ds, rows):
        if level not in ds.level.values:
            raise ValueError(f"Model level {level} unavailable")
        a = ds.ch4.sel(level=level, drop=True)
        if bbox is not None:
            a = subset_bbox(a, *bbox)
            area = subset_bbox(ds.cell_area, *bbox)
        else:
            area = ds.cell_area
        with dask.config.set(scheduler="synchronous"):
            global_daily = a.weighted(area).mean(("latitude", "longitude"), keep_attrs=True).compute()
        daily = global_daily.to_dataframe(name="ch4_ppb").reset_index()
        provenance = {"source": SOURCE, "release": version, "input_observations": observations,
                      "level": level, "units": "ppb dry-air mole fraction", "bbox": bbox,
                      "processed_sha256": [r["processed_checksum"] for r in rows]}
        daily.attrs = provenance
        save_table(daily, output / "area_daily.csv")
        point = extract_point(ds.ch4.sel(level=level, drop=True), lat, lon)
        point_frame = point.to_dataframe(name="ch4_ppb").reset_index()
        point_frame.attrs = {**provenance, **point.attrs}
        save_table(point_frame, output / "point_daily.csv")
        complete = []
        for period in sorted(set(pd.DatetimeIndex(a.time.values).to_period("M"))):
            part = a.sel(time=str(period))
            if pd.DatetimeIndex(part.time.values).equals(
                pd.date_range(period.start_time, periods=period.days_in_month, freq="D")
            ):
                complete.append(period)
        monthly_rows = []
        for period in complete:
            values = daily.loc[pd.DatetimeIndex(daily.time).to_period("M") == period, "ch4_ppb"]
            monthly_rows.append({"time": period.start_time, "ch4_ppb": float(values.mean()),
                                 "days": period.days_in_month})
        monthly = pd.DataFrame(monthly_rows, columns=["time", "ch4_ppb", "days"])
        monthly.attrs = {**provenance, "aggregation": "complete calendar months only"}
        save_table(monthly, output / "area_monthly.csv")
        map_scale = None
        if maps:
            latest = pd.Timestamp(a.time.values[-1])
            reference = (
                a.sel(time=str(complete[-1])).mean("time", keep_attrs=True)
                if complete else a.isel(time=-1)
            )
            with dask.config.set(scheduler="synchronous"):
                lower, upper = np.nanpercentile(reference.compute().values, [2, 98]).tolist()
            if lower >= upper:
                raise ValueError("CH4 map has no usable colour range")
            map_scale = {"lower_ppb": lower, "upper_ppb": upper,
                         "method": "2nd and 98th percentiles of latest complete-month field"
                         if complete else "2nd and 98th percentiles of latest daily field"}
            plot_map(a.isel(time=-1), output / "latest_day.png",
                     title=f"CH4 {version}, level {level}, {latest:%Y-%m-%d} (clipped scale)",
                     vmin=lower, vmax=upper)
            if complete:
                period = complete[-1]
                plot_map(reference, output / "latest_complete_month.png",
                         title=f"CH4 {version}, level {level}, {period} (clipped scale)",
                         vmin=lower, vmax=upper)
        report = {**provenance, "first_day": str(a.time.values[0]),
                  "last_day": str(a.time.values[-1]),
                  "complete_months": [str(p) for p in complete],
                  "files": [r["processed_path"] for r in rows],
                  "interpretation": "model layer, not a station observation or surface flux",
                  "map_color_scale": map_scale}
        (output / "analysis.json").write_text(json.dumps(report, indent=2, default=str))
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
