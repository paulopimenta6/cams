from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from conftest import dataset

from cams_air_quality.downloader import download_batch
from cams_air_quality.inventory import inventory
from cams_air_quality.processing import consolidate, open_database, process_batch
from cams_air_quality.requests import build_batch, plan_batches
from cams_air_quality.statistics import annual_mean, anomalies, climatology, linear_trend
from cams_air_quality.storage import Manifest, now, sha256


def register(cfg, b):
    p = Path(b.filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    spec = cfg["registry"][b.variable]
    d = dataset(
        spec["aliases"][0],
        spec["original_units"],
        pd.to_datetime([f"{b.year}-{b.month:02d}-01"]),
        spec["level"],
    )
    d.to_netcdf(p, engine="h5netcdf")
    m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    m.add(b)
    m.set(b.key, "validated", checksum=sha256(p), filesize=p.stat().st_size, download_date=now())
    return m


def test_manifest_idempotent(cfg, snap):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    m = register(cfg, b)
    m.add(b)
    assert len(m.rows()) == 1 and m.intact(m.get(b.key))
    Path(b.filepath).write_bytes(b"corrupt")
    assert not m.intact(m.get(b.key))


def test_existing_file_never_downloaded(cfg, snap):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    register(cfg, b)

    class NoNetwork:
        def submit(self, *a):
            raise AssertionError("Should not request existing validated data")

    assert download_batch(cfg, b, NoNetwork())["status"] == "skipped"


def test_crash_recovery(cfg, snap):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    m = register(cfg, b)
    m.set(b.key, "downloaded")
    assert download_batch(cfg, b, object())["status"] == "recovered"


def test_incremental_inventory(cfg, snap):
    bs = plan_batches(cfg, snap, "monthly", "2003-01", "2003-03", ["pm25"])
    register(cfg, bs[0])
    register(cfg, bs[2])
    row = inventory(cfg, bs).iloc[0]
    assert row.months_available == 2 and row.missing == 1 and row.missing_months == "2003-02"


def test_process_consolidate_extract(cfg, snap):
    cfg["pollutants"] = ["pm25", "co"]
    for name in cfg["pollutants"]:
        for month in ["2003-01", "2003-02"]:
            b = build_batch(cfg, snap, name, month, "monthly")
            register(cfg, b)
            p = process_batch(cfg, b)
            assert p.exists() and process_batch(cfg, b) == p
    index = consolidate(cfg)
    assert consolidate(cfg) == index
    with open_database(cfg) as ds:
        assert ds.sizes["time"] == 2
        assert float(ds.pm25[0, 0, 0].compute()) == pytest.approx(20)
        assert ds.co.attrs["units"] == "kg kg-1"
        assert ds.attrs["source"] == "EAC4"
    from cams_air_quality.extraction import get_region_timeseries, get_timeseries, save_table

    f = get_timeseries(cfg, "pm25", 0, -90)
    assert len(f) == 2 and f.attrs["selected_longitude"] == 270
    f = get_region_timeseries(cfg, "co", [90, -180, -90, 180])
    save_table(f, Path(cfg["root"]) / "test.parquet")
    assert (Path(cfg["root"]) / "test.parquet.metadata.json").exists()


def test_consolidation_rejects_unequal_variables(cfg, snap):
    cfg["pollutants"] = ["pm25", "co"]
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    register(cfg, b)
    process_batch(cfg, b)
    with pytest.raises(ValueError, match="Unequal"):
        consolidate(cfg)


def test_statistics_calendar_weighting():
    import numpy as np
    import xarray as xr

    a = xr.DataArray(
        np.arange(24.0),
        dims="time",
        coords={"time": pd.date_range("2003-01-01", periods=24, freq="MS")},
        attrs={"units": "ug m-3"},
    )
    expected = np.average(np.arange(12.0), weights=a.time.dt.days_in_month.values[:12])
    assert float(annual_mean(a)[0]) == pytest.approx(expected)
    cl = climatology(a, "2003-01", "2004-12")
    assert cl.sizes["month"] == 12 and float(cl.sel(month=1)) == 6
    assert float(anomalies(a, "2003-01", "2004-12").mean()) == pytest.approx(0)
    assert 11.9 < float(linear_trend(a)) < 12.1
    with pytest.raises(ValueError):
        annual_mean(a.isel(time=[0, 2, 3]))
    with pytest.raises(ValueError):
        climatology(a, "2003-01", "2003-03")


def test_job_identity_retained_on_timeout(cfg, snap):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    cfg["job_timeout_seconds"] = 0
    remote = SimpleNamespace(request_id="job-123", status="running")

    class Client:
        def submit(self, *a):
            return remote

        def get_remote(self, id):
            assert id == "job-123"
            return remote

    client = Client()
    assert download_batch(cfg, b, client)["status"] == "failed"
    m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    assert m.get(b.key)["remote_id"] == "job-123"
    assert download_batch(cfg, b, client)["status"] == "failed"


def test_download_mocked_full_pipeline(cfg, snap, tmp_path, monkeypatch):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    source = tmp_path / "payload.nc"
    dataset().to_netcdf(source, engine="h5netcdf")
    payload = source.read_bytes()

    def transfer(url, path, size, timeout):
        assert size == len(payload)
        Path(path).write_bytes(payload)

    monkeypatch.setattr("cams_air_quality.downloader.download_range", transfer)
    result = SimpleNamespace(
        content_length=len(payload), location="https://example.invalid/payload"
    )
    remote = SimpleNamespace(request_id="job-abc", status="successful", get_results=lambda: result)
    client = SimpleNamespace(submit=lambda *args: remote)
    assert download_batch(cfg, b, client)["status"] == "validated"
    assert Path(b.filepath).read_bytes() == payload
    assert download_batch(cfg, b, client)["status"] == "skipped"
    assert process_batch(cfg, b).exists()


def test_baseline_not_silently_truncated():
    import numpy as np
    import xarray as xr

    a = xr.DataArray(
        np.ones(12),
        dims="time",
        coords={"time": pd.date_range("2003-01-01", periods=12, freq="MS")},
    )
    with pytest.raises(ValueError, match="not fully available"):
        climatology(a, "2003-01", "2022-12")


def test_analysis_and_map_render(cfg, tmp_path, monkeypatch):
    import numpy as np
    import xarray as xr

    from cams_air_quality.analysis import explore

    times = pd.date_range("2003-01-01", periods=24, freq="MS")
    arrays = {}
    for v in cfg["pollutants"]:
        a = dataset(v, cfg["registry"][v]["desired_units"], times)[v]
        a.values[:] *= (1 + np.arange(24) / 24)[:, None, None]
        arrays[v] = a
    ds = xr.Dataset(arrays, attrs={"source": "SYNTHETIC_TEST_ONLY"})
    monkeypatch.setattr("cams_air_quality.analysis.open_database", lambda cfg: ds)
    out = tmp_path / "synthetic_eda"
    explore(cfg, out, "2003-01", "2004-12")
    assert (out / "pm25_mean_map.png").stat().st_size > 1000
    assert (out / "pm25_annual_anomalies.csv").exists()
    assert (out / "sao_paulo_nearest_cell.parquet").exists()


def test_unexecuted_manifest_portable(cfg, snap, tmp_path):
    from dataclasses import replace

    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    m.add(b)
    m.set(b.key, "failed", error="API key absent")
    moved = replace(b, filepath=str(tmp_path / "new_machine" / "payload.grib"))
    m.add(moved)
    assert m.get(b.key)["filepath"] == moved.filepath


def test_parquet_numeric_roundtrip(tmp_path):
    from cams_air_quality.extraction import save_table

    frame = pd.DataFrame(
        {
            "time": pd.date_range("2003-01-01", periods=3, freq="MS"),
            "pm25": [1.25, float("nan"), 9.5],
        }
    )
    frame.attrs = {"units": "ug m-3", "source": "SYNTHETIC_TEST_ONLY"}
    path = tmp_path / "series.parquet"
    save_table(frame, path)
    actual = pd.read_parquet(path, engine="fastparquet")
    pd.testing.assert_frame_equal(actual, frame)


def test_netcdf4_interoperability(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "interoperable.nc"
    dataset().to_netcdf(path, engine="h5netcdf")
    # Independent netCDF4 reader: confirms the format, not merely the writer API.
    code = """import sys
from netCDF4 import Dataset
with Dataset(sys.argv[1]) as d:
    assert d.data_model == "NETCDF4"
    assert d.variables["pm2p5"].shape == (1,3,4)
    assert abs(float(d.variables["pm2p5"][0,0,0]) - 2e-8) < 1e-12
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True, capture_output=True)


def test_map_polar_cell_edges():
    import numpy as np

    from cams_air_quality.maps import cell_edges

    edges = cell_edges(np.array([-90.0, 0.0, 90.0]), polar=True)
    np.testing.assert_array_equal(edges, [-90.0, -45.0, 45.0, 90.0])
