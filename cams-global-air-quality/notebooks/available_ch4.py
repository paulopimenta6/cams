"""Read-only, coverage-aware helpers for CAMS73 CH4 notebooks."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import dask
import pandas as pd
import xarray as xr

from cams_air_quality import ghg_inversion as ghg
from cams_air_quality.extraction import extract_point, subset_bbox
from cams_air_quality.maps import plot_map
from cams_air_quality.storage import sha256


def inventory(cfg: dict, version: str | None = None,
              observations: str = "first_guess") -> tuple[list[dict], pd.DataFrame]:
    """Report CH4 manifest rows and accept only checksum-verified partitions."""
    database = Path(cfg["metadata_dir"]) / "ghg_inversion/downloads.sqlite"
    columns = ["year", "month", "release", "status", "path", "checksum", "complete",
               "days", "n_levels", "first_time", "last_time"]
    if not database.is_file():
        return [], pd.DataFrame(columns=columns)
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        stored = [dict(row) for row in conn.execute("SELECT * FROM downloads ORDER BY year,month")]
    accepted, report = [], []
    wanted = version or cfg["ghg_inversion"]["version"]
    for row in stored:
        if row["dataset"] != ghg.DATASET:
            continue
        request = json.loads(row["api_request"])
        if request.get("input_observations") != [observations]:
            continue
        release = ghg._release(row)
        if release != wanted:
            continue
        path = Path(row["processed_path"]) if row["processed_path"] else None
        entry = {"year": row["year"], "month": row["month"], "release": release,
                 "status": row["status"], "path": str(path) if path else "",
                 "checksum": row["processed_checksum"], "complete": False,
                 "days": 0, "n_levels": 0, "first_time": None, "last_time": None}
        if row["status"] == "processed":
            if path is None or not path.is_file():
                entry["status"] = "processed_file_missing"
            elif not row["processed_checksum"] or sha256(path) != row["processed_checksum"]:
                entry["status"] = "checksum_failed"
            else:
                with xr.open_dataset(path, engine=cfg["netcdf_engine"]) as ds:
                    period = pd.Period(f"{row['year']}-{row['month']:02d}", freq="M")
                    times = pd.DatetimeIndex(ds.time.values)
                    entry.update(days=len(times), n_levels=ds.sizes.get("level", 0),
                                 first_time=str(times.min()) if len(times) else None,
                                 last_time=str(times.max()) if len(times) else None,
                                 complete=times.equals(pd.date_range(
                                     period.start_time, periods=period.days_in_month, freq="D"
                                 )))
                    if "ch4" not in ds or ds.ch4.attrs.get("units") != "ppb":
                        entry["status"] = "incompatible_partition"
                    else:
                        entry["status"] = "ready"
                        accepted.append(row)
        report.append(entry)
    duplicates = pd.DataFrame(accepted)
    if not duplicates.empty:
        bad = set(zip(
            duplicates.loc[duplicates.duplicated(["year", "month"], keep=False), "year"],
            duplicates.loc[duplicates.duplicated(["year", "month"], keep=False), "month"],
        ))
        if bad:
            accepted = [row for row in accepted if (row["year"], row["month"]) not in bad]
            for entry in report:
                if (entry["year"], entry["month"]) in bad:
                    entry["status"] = "ambiguous_month"
    return accepted, pd.DataFrame(report, columns=columns)


@contextmanager
def open_level(cfg: dict, level: int, version: str | None = None,
               start: str | None = None, end: str | None = None):
    """Open only verified months and one explicit model layer, without SQL writes."""
    release = version or cfg["ghg_inversion"]["version"]
    with ghg.open_processed(cfg, release, start=start, end=end) as (ds, rows):
        if level not in ds.level.values:
            raise ValueError(f"Model level {level} unavailable")
        selected = xr.Dataset({"ch4": ds.ch4.sel(level=level, drop=True),
                               "cell_area": ds.cell_area})
        provenance = {"source": ghg.SOURCE, "release": release, "level": level,
                      "observations": "first_guess", "units": "ppb dry-air mole fraction",
                      "files": [row["processed_path"] for row in rows],
                      "processed_sha256": [row["processed_checksum"] for row in rows]}
        yield selected, rows, provenance


def coverage(rows: list[dict]) -> dict:
    """Summarize complete months/years and missing months between endpoints."""
    periods = sorted(pd.Period(f"{row['year']}-{row['month']:02d}", freq="M") for row in rows)
    complete = sorted(pd.Period(f"{row['year']}-{row['month']:02d}", freq="M")
                      for row in rows if row.get("complete"))
    expected = pd.period_range(periods[0], periods[-1], freq="M") if periods else []
    years = ghg.complete_years(complete)
    return {"complete_months": [str(p) for p in complete], "complete_years": years,
            "missing_months": [str(p) for p in expected if p not in periods],
            "incomplete_months": [str(p) for p in periods if p not in complete],
            "months_needed_for_annual": {
                str(y): [f"{y}-{m:02d}" for m in range(1, 13)
                         if pd.Period(f"{y}-{m:02d}", freq="M") not in complete]
                for y in sorted({p.year for p in periods}) if y not in years
            }}


def global_series(ds_level: xr.Dataset, area: xr.DataArray | None = None) -> xr.DataArray:
    """Daily area-weighted CH4 mean; area defaults to the dataset cell areas."""
    weights = area if area is not None else ds_level.cell_area
    with dask.config.set(scheduler="synchronous"):
        return ds_level.ch4.weighted(weights).mean(
            ("latitude", "longitude"), keep_attrs=True
        ).compute()


def point_series(ds_level: xr.Dataset, lat: float, lon: float) -> xr.DataArray:
    with dask.config.set(scheduler="synchronous"):
        return extract_point(ds_level.ch4, lat, lon).compute()


def monthly_series(a: xr.DataArray) -> xr.DataArray:
    return ghg.monthly_series(a)


def annual_series(a: xr.DataArray) -> xr.DataArray:
    return ghg.annual_series(a)


def reference_cycle(a: xr.DataArray, years: list[int]) -> xr.DataArray:
    return ghg.reference_cycle(a, years)


def anomaly_series(a: xr.DataArray, reference: xr.DataArray) -> xr.DataArray:
    return ghg.anomaly_series(a, reference)


def temporal_std(a: xr.DataArray) -> xr.DataArray:
    return ghg.std_field(a)


def map_field(field: xr.DataArray, path: Path, title: str,
              vmin: float | None = None, vmax: float | None = None) -> Path:
    return plot_map(field, path, title=title, vmin=vmin, vmax=vmax)


def selected_area(ds_level: xr.Dataset, bbox=None) -> xr.Dataset:
    """Subset CH4 and its cell areas to the same requested rectangle."""
    if bbox is None:
        return ds_level
    return xr.Dataset({"ch4": subset_bbox(ds_level.ch4, *bbox),
                       "cell_area": subset_bbox(ds_level.cell_area, *bbox)})
