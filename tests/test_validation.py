import zipfile

import numpy as np
import pandas as pd
import pytest
from conftest import dataset

from cams_air_quality.requests import build_batch
from cams_air_quality.validation import normalize, validate_file


def test_valid_file(cfg, snap, tmp_path):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    p = tmp_path / "ok.nc"
    dataset().to_netcdf(p, engine="h5netcdf")
    assert validate_file(p, b, cfg)["status"] == "PASS"


@pytest.mark.parametrize(
    "change", ["units", "inf", "nan", "duplicate", "month", "grid", "coordinates"]
)
def test_qc_failures(cfg, snap, tmp_path, change):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    d = dataset()
    if change == "units":
        d.pm2p5.attrs["units"] = "kg kg-1"
    if change == "inf":
        d.pm2p5.values[0, 0, 0] = np.inf
    if change == "nan":
        d.pm2p5.values[:] = np.nan
    if change == "duplicate":
        d = __import__("xarray").concat([d, d], dim="time")
    if change == "month":
        d = d.assign_coords(time=pd.to_datetime(["2003-02-01"]))
    if change == "grid":
        d = d.isel(longitude=slice(0, 2))
    if change == "coordinates":
        d = d.assign_coords(latitude=[91.0, 0.0, -90.0])
    p = tmp_path / "bad.nc"
    d.to_netcdf(p, engine="h5netcdf")
    assert validate_file(p, b, cfg)["status"] == "FAIL"


def test_corrupt(cfg, snap, tmp_path):
    p = tmp_path / "bad.nc"
    p.write_bytes(b"not a netcdf" * 100)
    assert (
        validate_file(p, build_batch(cfg, snap, "pm25", "2003-01", "monthly"), cfg)["status"]
        == "FAIL"
    )


def test_negative_warned_not_clipped(cfg, snap, tmp_path):
    p = tmp_path / "warn.nc"
    d = dataset()
    d.pm2p5.values[0, 0, 0] = -1
    d.to_netcdf(p, engine="h5netcdf")
    assert (
        validate_file(p, build_batch(cfg, snap, "pm25", "2003-01", "monthly"), cfg)["status"]
        == "WARNING"
    )


@pytest.mark.parametrize("level", [1, 59, 137, None])
def test_wrong_gas_level(cfg, level):
    with pytest.raises(ValueError):
        normalize(dataset("co", "kg kg-1", level=level), cfg["registry"]["co"])


def test_correct_gas_level(cfg):
    assert normalize(dataset("co", "kg kg-1", level=60), cfg["registry"]["co"]).dims == (
        "time",
        "latitude",
        "longitude",
    )


def test_three_hour_gap(cfg, subdaily, tmp_path):
    b = build_batch(cfg, subdaily, "pm25", "2003-01", "subdaily")
    d = dataset(times=pd.date_range("2003-01-01", "2003-01-31 21:00", freq="3h"))
    p = tmp_path / "sub.nc"
    d.to_netcdf(p, engine="h5netcdf")
    assert validate_file(p, b, cfg)["status"] == "PASS"
    d.isel(time=slice(1, None)).to_netcdf(p, engine="h5netcdf")
    assert validate_file(p, b, cfg)["status"] == "FAIL"


def test_zip_safe(cfg, snap, tmp_path):
    nc = tmp_path / "source.nc"
    dataset().to_netcdf(nc, engine="h5netcdf")
    p = tmp_path / "data.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.write(nc, "field.nc")
    assert (
        validate_file(p, build_batch(cfg, snap, "pm25", "2003-01", "monthly"), cfg)["status"]
        == "PASS"
    )
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../escape.nc", "evil")
    assert (
        validate_file(p, build_batch(cfg, snap, "pm25", "2003-01", "monthly"), cfg)["status"]
        == "FAIL"
    )


def test_grib_real_codec(cfg, snap, tmp_path):
    # Generated locally using ecCodes sample, explicitly synthetic (not an ADS download).
    import eccodes as ec

    cfg["grid"] = {"latitude": 241, "longitude": 480, "spacing_degrees": 0.75}
    cfg["chunks"] = {"time": 1, "latitude": 121, "longitude": 120}
    h = ec.codes_grib_new_from_samples("regular_ll_sfc_grib1")
    for k, v in {
        "Ni": 480,
        "Nj": 241,
        "latitudeOfFirstGridPointInDegrees": 90.0,
        "latitudeOfLastGridPointInDegrees": -90.0,
        "longitudeOfFirstGridPointInDegrees": 0.0,
        "longitudeOfLastGridPointInDegrees": 359.25,
        "iDirectionIncrementInDegrees": 0.75,
        "jDirectionIncrementInDegrees": 0.75,
        "dataDate": 20030101,
        "dataTime": 0,
        "paramId": 210073,
    }.items():
        ec.codes_set(h, k, v)
    ec.codes_set_values(h, np.full(241 * 480, 2e-8))
    p = tmp_path / "synthetic.grib"
    with p.open("wb") as f:
        ec.codes_write(h, f)
    ec.codes_release(h)
    qc = validate_file(p, build_batch(cfg, snap, "pm25", "2003-01", "monthly"), cfg)
    assert qc["status"] == "PASS", qc


def test_shifted_global_grid(cfg, snap, tmp_path):
    d = dataset().assign_coords(longitude=[0.1, 90.1, 180.1, 270.1])
    p = tmp_path / "shifted.nc"
    d.to_netcdf(p, engine="h5netcdf")
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    assert validate_file(p, b, cfg)["status"] == "FAIL"
