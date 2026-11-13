import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cams_air_quality.catalog import load_snapshot
from cams_air_quality.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_snapshot(tmp_path, cfg, kind):
    """Create a tiny ADS-shaped catalog in tmp_path; never use missing real evidence."""
    years = [str(year) for year in range(2003, 2026)]
    months = [f"{month:02d}" for month in range(1, 13)]
    times = [f"{hour:02d}:00" for hour in range(0, 24, 3)]
    variables = [spec["cams_variable"] for spec in cfg["registry"].values()]
    fields = {"variable": variables, "data_format": ["grib", "netcdf_zip"],
              "model_level": ["60"], "time": ["00:00"] if kind == "monthly" else times}
    if kind == "monthly":
        fields.update(year=years, month=months, product_type=["monthly_mean"])
    form = [{"name": name, "details": {"values": values}}
            for name, values in fields.items()]
    constraints = []
    for name, spec in cfg["registry"].items():
        row = {"variable": [spec["cams_variable"]],
               "time": ["00:00"] if kind == "monthly" else times}
        if spec["level_type"] == "model":
            row["model_level"] = [str(spec["level"])]
        if kind == "monthly":
            row.update(year=years, month=months, product_type=["monthly_mean"])
        else:
            row["date"] = ["2003-01-01/2025-12-31"]
        constraints.append(row)
    collection = {"id": cfg["sources"]["EAC4"][kind],
                  "extent": {"temporal": {"interval": [[
                      "2003-01-01T00:00:00Z", "2025-12-31T00:00:00Z"
                  ]]}}}
    directory = tmp_path / f"synthetic-{kind}-evidence"
    directory.mkdir()
    for name, data in (("collection", collection), ("form", form),
                       ("constraints", constraints)):
        (directory / f"{kind}.{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return load_snapshot(directory, kind)


@pytest.fixture
def cfg(tmp_path):
    c = load_config(ROOT / "config/config.yaml")
    c.update(
        root=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        metadata_dir=str(tmp_path / "metadata"),
        log_dir=str(tmp_path / "logs"),
        backoff_seconds=0,
        min_free_disk_gib=0,
        workers=1,
        poll_seconds=0,
    )
    for k in ["data_dir", "metadata_dir", "log_dir"]:
        Path(c[k]).mkdir()
    c["grid"] = {"latitude": 3, "longitude": 4, "spacing_degrees": 90.0}
    c["chunks"] = {"time": 1, "latitude": 3, "longitude": 4}
    return c


@pytest.fixture
def snap(tmp_path, cfg):
    return _synthetic_snapshot(tmp_path, cfg, "monthly")


@pytest.fixture
def subdaily(tmp_path, cfg):
    return _synthetic_snapshot(tmp_path, cfg, "subdaily")


def dataset(name="pm2p5", units="kg m**-3", times=None, level=None):
    times = pd.to_datetime(["2003-01-01"]) if times is None else times
    dims = ("time", "latitude", "longitude")
    a = xr.DataArray(
        np.full((len(times), 3, 4), 2e-8, dtype="float32"),
        dims=dims,
        coords={
            "time": times,
            "latitude": [90.0, 0.0, -90.0],
            "longitude": [0.0, 90.0, 180.0, 270.0],
        },
        attrs={"units": units, "test_data": "SYNTHETIC: not CAMS observations"},
    )
    if level is not None:
        a = a.expand_dims(hybrid=[level])
    return a.to_dataset(name=name)
