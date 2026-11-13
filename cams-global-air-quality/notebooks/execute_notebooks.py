"""Run notebooks 01–06 against synthetic archives in temporary directories only."""

import json
import os
import sys
import tempfile
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd
import xarray as xr
import yaml
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks/tests"))
sys.path.insert(0, str(ROOT / "src"))
from test_available_data import fixture_archive  # noqa: E402

from cams_air_quality import ghg_inversion as ghg  # noqa: E402
from cams_air_quality.storage import sha256  # noqa: E402


def _configuration(folder):
    cfg = yaml.safe_load((ROOT / "config/config.yaml").read_text())
    cfg.update(root=str(folder), metadata_dir="metadata", data_dir="data", log_dir="logs")
    (folder / "pollutants.yaml").write_text(
        (ROOT / "config/pollutants.yaml").read_text(), encoding="utf-8"
    )
    path = folder / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return cfg, path


def _ch4_fixture(folder, cfg):
    """Two full years, two model levels and 3x4 cells; no raw/ADS requests."""
    from cams_air_quality.config import load_config

    loaded = load_config(folder / "config.yaml")
    loaded["ghg_inversion"]["grid"] = {"latitude": 3, "longitude": 4,
                                         "spacing_degrees": 1.0, "global": False}
    loaded["ghg_inversion"]["levels"] = 2
    loaded["ghg_inversion"]["chunks"] = {"time": 1, "level": 1,
                                           "latitude": 3, "longitude": 4}
    manifest = ghg.manifest(loaded)
    latitude = [-1.0, 0.0, 1.0]
    longitude = [-2.0, -1.0, 0.0, 1.0]
    for period in pd.period_range("2022-01", "2023-12", freq="M"):
        batch = ghg.build_batch(loaded, period, "v25r1")
        output = (folder / "data/processed/ghg_inversion/ch4/first_guess/v25r1"
                  / "daily_mean" / str(period.year) / f"{period.month:02d}.nc")
        output.parent.mkdir(parents=True, exist_ok=True)
        times = pd.date_range(period.start_time, periods=period.days_in_month, freq="D")
        spatial = np.arange(12, dtype="float32").reshape(3, 4)
        values = (1850 + (period.year - 2022) * 15 + period.month * 2 + spatial[None, None]
                  + np.arange(len(times), dtype="float32")[:, None, None, None]
                  * (0.1 + spatial[None, None] * 0.01))
        values = np.broadcast_to(values, (len(times), 2, 3, 4)).copy()
        values[:, 1] -= 80
        ds = xr.Dataset(
            {"ch4": (("time", "level", "latitude", "longitude"), values,
                      {"units": "ppb", "mole_fraction_basis": "dry_air"}),
             "cell_area": (("latitude", "longitude"), np.ones((3, 4), dtype="float32"))},
            coords={"time": times, "level": [1, 2],
                    "latitude": latitude, "longitude": longitude},
            attrs={"source": "GHG_INVERSION", "release": "v25r1",
                   "test_data": "SYNTHETIC: not CAMS observations"},
        )
        ds.to_netcdf(output, engine="h5netcdf")
        raw = xr.Dataset(
            {"CH4": ds.ch4.assign_attrs(
                standard_name="mole_fraction_of_methane_in_air",
                long_name="mole fraction of methane in dry air", units="1e-9"
            ),
             "cell_area": ds.cell_area,
             "ps": (("time", "latitude", "longitude"),
                    np.full((len(times), 3, 4), 101325, dtype="float32")),
             "altitude": (("time", "hlevel", "latitude", "longitude"),
                          np.zeros((len(times), 3, 3, 4), dtype="float32")),
             "hyam": (("level",), np.zeros(2)),
             "hybm": (("level",), np.array([0.9, 0.1]))},
            coords={"time": times, "level": [1, 2], "hlevel": [1, 2, 3],
                    "latitude": latitude, "longitude": longitude},
            attrs={"source": "TM5-MP 4D-Var", "release": "v25r1",
                   "test_data": "SYNTHETIC: not CAMS observations"},
        )
        raw_path = Path(batch.filepath)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_netcdf(raw_path, engine="h5netcdf")
        manifest.add(batch)
        manifest.set(batch.key, "processed", checksum=sha256(raw_path),
                     filesize=raw_path.stat().st_size, qc_json=json.dumps({"status": "PASS",
                                                     "resolved_release": "v25r1"}),
                     processed_path=str(output), processed_checksum=sha256(output))
    return loaded


def _execute(paths, folder, configpath, results, scenario, fake_maps=False):
    os.environ["CAMSAQ_CONFIG"] = str(configpath)
    for path in paths:
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        if fake_maps:
            notebook.cells.insert(0, nbformat.v4.new_code_cell("""
from pathlib import Path
import requests
from cams_air_quality import ghg_inversion as _ghg_test
def _network_forbidden(*args, **kwargs):
    raise AssertionError('Notebook CH4 attempted a network request')
requests.sessions.Session.request = _network_forbidden
def _synthetic_map(field, path, **kwargs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.imshow(field.values)
    path = Path(path)
    fig.savefig(path)
    plt.close(fig)
    return path
_ghg_test.plot_map = _synthetic_map
"""))
        client = NotebookClient(
            notebook, timeout=600, kernel_name="camsaq",
            resources={"metadata": {"path": str(ROOT)}},
        )
        client.execute()
        nbformat.write(notebook, folder / path.name)
        results.append({"scenario": scenario, "notebook": path.name, "status": "PASS"})
        print(scenario, path.name, "PASS", flush=True)
    for path in folder.rglob("errors.json"):
        assert json.loads(path.read_text()) == [], path


def main():
    os.environ["PYTHONPATH"] = str(ROOT / "src")
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["OMP_NUM_THREADS"] = "1"
    results = []
    scenarios = {
        "empty": {},
        "partial": {"pm25": pd.date_range("2017-04-01", periods=3, freq="MS")},
        "single_year": {"pm25": pd.date_range("2019-01-01", periods=12, freq="MS")},
        "gaps_and_different_variables": {
            "pm25": pd.date_range("2010-01-01", periods=12, freq="MS").append(
                pd.date_range("2012-01-01", periods=12, freq="MS")
            ),
            "pm10": pd.date_range("2012-09-01", periods=3, freq="MS"),
        },
    }
    with tempfile.TemporaryDirectory(prefix="cams-notebook-validation-") as temporary:
        base = Path(temporary)
        for scenario, specs in scenarios.items():
            folder = base / scenario
            folder.mkdir()
            cfg, path = _configuration(folder)
            if specs:
                overrides, _ = fixture_archive(folder, specs)
                cfg.update({k: value for k, value in overrides.items() if k != "registry"})
                path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
            _execute(sorted((ROOT / "notebooks").glob("0[1-3]_*.ipynb")), folder,
                     path, results, scenario)
        folder = base / "ch4_complete"
        folder.mkdir()
        cfg, path = _configuration(folder)
        _ch4_fixture(folder, cfg)
        _execute(sorted((ROOT / "notebooks").glob("0[4-6]_*.ipynb")), folder,
                 path, results, "ch4_complete", fake_maps=True)
        assert list(folder.rglob("inventory.csv"))
        assert list(folder.rglob("annual_*.png"))
        assert list(folder.rglob("month_*.png"))
        assert list(folder.rglob("climatology_*.png"))
        assert list(folder.rglob("anomaly_*.png"))
        assert list(folder.rglob("analysis.json"))
        summary = {"synthetic_only": True, "results": results,
                   "ch4_months": 24, "real_archive_touched": False}
        (base / "notebook_execution_results.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
