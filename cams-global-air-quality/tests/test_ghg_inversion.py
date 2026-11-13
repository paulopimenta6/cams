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
from cams_air_quality.storage import sha256


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


def synthetic_ch4(path, missing_day=False, wrong_unit=False, reversed_levels=False,
                  period="2024-09"):
    month = pd.Period(period, freq="M")
    times = pd.date_range(month.start_time, periods=month.days_in_month, freq="D")
    if missing_day:
        times = times.delete(4)
    levels = [3, 2, 1] if reversed_levels else [1, 2, 3]
    latitudes = [-1.0, 0.0, 1.0]
    longitudes = [-2.0, -1.0, 0.0, 1.0]
    offset = (month.year - 2024) * 10 + month.month - 9
    base = np.full((len(times), 3, 3, 4), 1900.0 + offset, dtype="float32")
    base[:, 1] = 1800 + offset
    base[:, 2] = 1000 + offset
    base[:, 0, 1, 1] = 2000 + offset
    ds = xr.Dataset(
        {
            "CH4": (("time", "level", "latitude", "longitude"), base,
                    {"standard_name": "mole_fraction_of_methane_in_air",
                     "long_name": "mole fraction of methane in dry air",
                     "units": "kg/kg" if wrong_unit else "1e-9"}),
            "ps": (("time", "latitude", "longitude"),
                   np.full((len(times), 3, 4), 101325.0, dtype="float32")),
            "altitude": (("time", "hlevel", "latitude", "longitude"),
                         np.broadcast_to(
                             np.array([0, 100, 200, 300], dtype="float32")[None, :, None, None],
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


def prepared_months(cfg, periods):
    """Create tiny verified processed partitions without raw files or network."""
    m = ghg.manifest(cfg)
    for period in periods:
        p = pd.Period(period, freq="M")
        batch = ghg.build_batch(cfg, p)
        path = (Path(cfg["data_dir"]) / "processed/ghg_inversion/ch4/first_guess/v25r1"
                / "daily_mean" / str(p.year) / f"{p.month:02d}.nc")
        path.parent.mkdir(parents=True, exist_ok=True)
        time = pd.date_range(p.start_time, periods=p.days_in_month, freq="D")
        spatial = np.arange(12, dtype="float32").reshape(3, 4)
        base = 1850 + (p.year - 2022) * 15 + p.month * 2
        values = (base + spatial[None]
                  + np.arange(len(time))[:, None, None] * (0.1 + spatial[None] * 0.01))
        ds = xr.Dataset(
            {"ch4": (("time", "latitude", "longitude"), values.astype("float32"),
                      {"units": "ppb"}),
             "cell_area": (("latitude", "longitude"), np.ones((3, 4), dtype="float32"))},
            coords={"time": time, "latitude": [-1.0, 0.0, 1.0],
                    "longitude": [-2.0, -1.0, 0.0, 1.0]},
        )
        ds = ds.expand_dims(level=[1, 2, 3]).transpose(
            "time", "level", "latitude", "longitude", missing_dims="ignore"
        )
        ds["cell_area"] = ds.cell_area.isel(level=0, drop=True)
        ds.to_netcdf(path, engine="h5netcdf")
        m.add(batch)
        m.set(batch.key, "processed", checksum="synthetic-raw-absent", filesize=0,
              qc_json=json.dumps({"status": "PASS", "resolved_release": "v25r1"}),
              processed_path=str(path), processed_checksum=sha256(path))


@pytest.fixture
def fake_maps(monkeypatch):
    def render(field, path, **kwargs):
        path = Path(path)
        path.write_bytes(b"SYNTHETIC PNG")
        return path

    monkeypatch.setattr(ghg, "plot_map", render)


def test_selected_months_exclude_later_release(ch4_cfg, tmp_path, fake_maps):
    prepared_months(ch4_cfg, ["2023-01", "2023-02", "2023-03", "2023-04", "2024-09"])
    rows = ghg.processed_rows(ch4_cfg, start="2023-01", end="2023-04")
    assert len(rows) == 4
    report = ghg.analyze(ch4_cfg, 1, tmp_path / "selected", start="2023-01",
                         end="2023-04", map_families=["all"])
    assert report["selected_months"] == ["2023-01", "2023-02", "2023-03", "2023-04"]
    assert not list((tmp_path / "selected").glob("*2024*"))
    assert len(list((tmp_path / "selected").glob("month_2023-*.png"))) == 4
    assert (tmp_path / "selected/period_2023-01_2023-04.png").is_file()
    assert (tmp_path / "selected/std_period_2023-01_2023-04.png").is_file()
    assert {s["family"] for s in report["skipped"]} >= {"annual", "climatology", "anomaly"}
    assert report["schema_version"] == 2 and report["map_scales"]
    assert all("method" in scale for scale in report["map_scales"].values())
    assert report["requested_start"] == "2023-01"


def test_full_year_reference_anomaly_and_scales(ch4_cfg, tmp_path, fake_maps):
    prepared_months(ch4_cfg, [str(p) for p in pd.period_range("2022-01", "2023-12")])
    shared = ghg.analyze(ch4_cfg, 1, tmp_path / "shared", start="2022-01",
                         end="2023-12", map_families=["all"],
                         baseline_start="2022-01", baseline_end="2023-12")
    assert (tmp_path / "shared/annual_2022.png").is_file()
    assert (tmp_path / "shared/climatology_01.png").is_file()
    assert (tmp_path / "shared/anomaly_month_2022-01.png").is_file()
    assert (tmp_path / "shared/anomaly_annual_2023.png").is_file()
    assert shared["complete_years"] == [2022, 2023]
    assert shared["baseline"]["reference_years"] == [2022, 2023]
    assert (tmp_path / "shared/area_annual.csv.metadata.json").is_file()
    assert (tmp_path / "shared/area_climatology.csv.metadata.json").is_file()
    assert all(np.isfinite([m["vmin"], m["vmax"]]).all() for m in shared["maps"])
    per_map = ghg.analyze(ch4_cfg, 1, tmp_path / "per_map", start="2022-01",
                          end="2023-12", map_families=["monthly"], scale="per-map")
    assert (shared["map_scales"]["month_2022-01.png"]["vmin"]
            != per_map["map_scales"]["month_2022-01.png"]["vmin"])


def test_date_no_maps_and_legacy(ch4_cfg, tmp_path, fake_maps):
    prepared_months(ch4_cfg, ["2024-09"])
    day = ghg.analyze(ch4_cfg, 1, tmp_path / "day", date="2024-09-12")
    assert [m["file"] for m in day["maps"]] == ["day_2024-09-12.png"]
    assert day["coverage"]["days_available"] == 1
    assert not list((tmp_path / "day").glob("month_*.png"))
    none = ghg.analyze(ch4_cfg, 1, tmp_path / "none", maps=False)
    assert not none["maps"] and not list((tmp_path / "none").glob("*.png"))
    assert (tmp_path / "none/area_daily.csv").is_file()
    legacy = ghg.analyze(ch4_cfg, 1, tmp_path / "legacy")
    assert {m["file"] for m in legacy["maps"]} == {
        "latest_day.png", "latest_complete_month.png"
    }
    assert legacy["map_color_scale"] is not None
    with pytest.raises(ValueError, match="baseline"):
        ghg.analyze(ch4_cfg, 1, tmp_path / "bad", map_families=["anomaly"])
    with pytest.raises(ValueError, match="first_day=.*last_day"):
        ghg.analyze(ch4_cfg, 1, tmp_path / "missing", date="2024-09-31")


def test_single_reference_year_skips_climatology_and_anomaly(ch4_cfg, tmp_path,
                                                              fake_maps):
    prepared_months(ch4_cfg, [str(p) for p in pd.period_range("2022-01", "2022-12")])
    report = ghg.analyze(ch4_cfg, 1, tmp_path / "one_year", map_families=["annual",
                         "climatology", "anomaly"], baseline_start="2022-01",
                         baseline_end="2022-12")
    assert (tmp_path / "one_year/annual_2022.png").is_file()
    assert not list((tmp_path / "one_year").glob("climatology_*.png"))
    assert not list((tmp_path / "one_year").glob("anomaly_*.png"))
    assert {item["family"] for item in report["skipped"]} == {"climatology", "anomaly"}


def test_one_day_std_skipped_and_bbox_point(ch4_cfg, tmp_path, fake_maps):
    prepared_months(ch4_cfg, ["2024-09"])
    report = ghg.analyze(ch4_cfg, 1, tmp_path / "bbox", bbox=[1, -1, 0, 0],
                         lat=-1, lon=-2, map_families=["period"])
    assert report["bbox"] == [1, -1, 0, 0]
    point = pd.read_csv(tmp_path / "bbox/point_daily.csv")
    area = pd.read_csv(tmp_path / "bbox/area_daily.csv")
    assert not np.isclose(point.ch4_ppb.iloc[0], area.ch4_ppb.iloc[0])
    one_day = ghg.analyze(ch4_cfg, 1, tmp_path / "std_one_day", date="2024-09-01",
                          map_families=["std"])
    assert any(s["family"] == "std" for s in one_day["skipped"])


def test_latest_map_does_not_overwrite_other_period(ch4_cfg, tmp_path, fake_maps):
    prepared_months(ch4_cfg, ["2023-01", "2024-09"])
    output = tmp_path / "same_output"
    ghg.analyze(ch4_cfg, 1, output, start="2023-01", end="2023-01")
    before = (output / "area_daily.csv").read_bytes()
    with pytest.raises(ValueError, match="another selection"):
        ghg.analyze(ch4_cfg, 1, output, start="2024-09", end="2024-09")
    assert (output / "area_daily.csv").read_bytes() == before
