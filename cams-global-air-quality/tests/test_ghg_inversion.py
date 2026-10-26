"""CH4 inversion tests use tiny synthetic files, never ADS observations."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cams_air_quality import ghg_inversion as ghg
from cams_air_quality.catalog import CatalogError


@pytest.fixture
def ch4_cfg(cfg):
    cfg["ghg_inversion"]["grid"] = {
        "latitude": 3,
        "longitude": 4,
        "spacing_degrees": 1.0,
        "global": False,
    }
    cfg["ghg_inversion"]["levels"] = 3
    cfg["ghg_inversion"]["chunks"] = {"time": 1, "level": 1, "latitude": 3, "longitude": 4}
    return cfg


@pytest.fixture
def ch4_snap():
    request = {
        "variable": ["methane"],
        "quantity": ["concentration"],
        "input_observations": ["first_guess"],
        "time_aggregation": ["daily_mean"],
        "version": ["latest", "v25r1"],
        "year": ["2024"],
        "month": ["09"],
    }
    return {
        "form": [{"name": k, "details": {"values": v}} for k, v in request.items()],
        "constraints": [request],
        "sha256": "synthetic-form",
    }


def synthetic_ch4(path, missing_day=False, wrong_unit=False, reversed_levels=False):
    times = pd.date_range("2024-09-01", "2024-09-30", freq="D")
    if missing_day:
        times = times.delete(4)
    levels = [3, 2, 1] if reversed_levels else [1, 2, 3]
    latitudes = [-1.0, 0.0, 1.0]
    longitudes = [-2.0, -1.0, 0.0, 1.0]
    base = np.full((len(times), 3, 3, 4), 1900.0, dtype="float32")
    base[:, 1] = 1800
    base[:, 2] = 1000
    base[:, 0, 1, 1] = 2000
    ds = xr.Dataset(
        {
            "CH4": (("time", "level", "latitude", "longitude"), base,
                    {"standard_name": "mole_fraction_of_methane_in_air",
                     "long_name": "mole fraction of methane in dry air",
                     "units": "kg/kg" if wrong_unit else "1e-9"}),
            "ps": (("time", "latitude", "longitude"),
                   np.full((len(times), 3, 4), 101325.0, dtype="float32")),
            "altitude": (("time", "hlevel", "latitude", "longitude"),
                         np.broadcast_to(np.array([0, 100, 200, 300], dtype="float32")[None, :, None, None],
                                         (len(times), 4, 3, 4)).copy()),
            "cell_area": (("latitude", "longitude"), np.ones((3, 4), dtype="float32")),
            "hyam": (("level",), np.zeros(3)),
            "hybm": (("level",), np.array([0.99, 0.5, 0.01])),
            "hyai": (("hlevel",), np.zeros(4)),
            "hybi": (("hlevel",), np.array([1.0, 0.8, 0.2, 0.0])),
        },
        coords={"time": times, "level": levels, "hlevel": [1, 2, 3, 4],
                "latitude": latitudes, "longitude": longitudes},
        attrs={"source": "TM5-MP 4D-Var", "release": "v25r1", "Conventions": "CF-1.6",
               "test_data": "SYNTHETIC: not CAMS observations"},
    )
    ds.to_netcdf(path, engine="scipy")
    return path


def test_exact_ads_selection(ch4_cfg, ch4_snap):
    batches = ghg.plan_batches(ch4_cfg, ch4_snap, "2024-09")
    assert len(batches) == 1
    assert batches[0].api_request == {
        "variable": ["methane"], "quantity": ["concentration"],
        "input_observations": ["first_guess"], "time_aggregation": ["daily_mean"],
        "version": ["v25r1"], "year": ["2024"], "month": ["09"],
    }
    assert ghg.estimate(batches)["estimated_raw_GiB"] > 0.4
    with pytest.raises(CatalogError):
        ghg.plan_batches(ch4_cfg, ch4_snap, "2024-10")
    with pytest.raises(ValueError):
        ghg.plan_batches(ch4_cfg, ch4_snap, "2024-10", "2024-09")


@pytest.mark.parametrize("change", ["missing_day", "wrong_unit", "reversed_levels"])
def test_ch4_qc_rejects_bad_file(ch4_cfg, tmp_path, change):
    path = synthetic_ch4(tmp_path / "bad.nc", **{change: True})
    batch = ghg.build_batch(ch4_cfg, "2024-09", "latest")
    assert ghg.validate_file(path, batch, ch4_cfg)["status"] == "FAIL"


def test_import_process_analysis_and_isolation(ch4_cfg, tmp_path):
    source = synthetic_ch4(tmp_path / "cams73_latest_ch4_conc_first_guess_dm_202409.nc")
    batch, qc = ghg.import_file(ch4_cfg, source)
    assert qc["status"] == "PASS"
    assert qc["request_origin"] == "local_import_reconstructed"
    assert Path(batch.filepath).read_bytes() == source.read_bytes()
    assert ghg.import_file(ch4_cfg, source)[0].key == batch.key
    output = ghg.process_batch(ch4_cfg, batch)
    with xr.open_dataset(output, engine="h5netcdf") as ds:
        assert ds.ch4.shape == (30, 3, 3, 4)
        assert ds.ch4.attrs["units"] == "ppb"
        assert ds.ch4.attrs["mole_fraction_basis"] == "dry_air"
        assert "hybm" in ds and "ps" in ds and "altitude" in ds
    assert ghg.process_batch(ch4_cfg, batch) == output
    index = ghg.consolidate(ch4_cfg, "v25r1")
    assert json.loads(index.read_text())["years"]["2024"]["months"] == [9]
    report = ghg.analyze(ch4_cfg, 1, tmp_path / "analysis", lat=0, lon=-1, maps=False)
    assert report["complete_months"] == ["2024-09"]
    monthly = pd.read_csv(tmp_path / "analysis/area_monthly.csv")
    assert len(monthly) == 1 and monthly.iloc[0].days == 30
    assert 1900 < monthly.iloc[0].ch4_ppb < 1910
    assert not (tmp_path / "metadata/downloads.sqlite").exists()
    with pytest.raises(ValueError, match="Model level"):
        ghg.analyze(ch4_cfg, 34, tmp_path / "invalid", maps=False)


def test_mocked_ads_download(ch4_cfg, ch4_snap, tmp_path, monkeypatch):
    source = synthetic_ch4(tmp_path / "payload.nc")
    payload = source.read_bytes()

    def transfer(url, target, expected, timeout):
        assert expected == len(payload)
        Path(target).write_bytes(payload)

    monkeypatch.setattr("cams_air_quality.downloader.download_range", transfer)
    asset = SimpleNamespace(location="https://example.invalid/ch4", content_length=len(payload))
    remote = SimpleNamespace(request_id="synthetic-job", status="successful",
                             get_results=lambda: asset)
    client = SimpleNamespace(submit=lambda dataset, request: remote)
    batch = ghg.plan_batches(ch4_cfg, ch4_snap, "2024-09")[0]
    result = ghg.download(ch4_cfg, [batch], client=client)
    assert result[0]["status"] == "validated"
    assert Path(result[0]["processed"]).is_file()
    assert ghg.manifest(ch4_cfg).get(batch.key)["status"] == "processed"
