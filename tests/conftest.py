from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cams_air_quality.catalog import load_snapshot
from cams_air_quality.config import load_config

ROOT = Path(__file__).resolve().parents[1]


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
def snap():
    return load_snapshot(ROOT / "evidence", "monthly")


@pytest.fixture
def subdaily():
    return load_snapshot(ROOT / "evidence", "subdaily")


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
