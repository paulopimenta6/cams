"""Execute the CH4 notebooks with a full two-year synthetic archive."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks"))

import execute_notebooks as harness  # noqa: E402


def test_ch4_notebooks_execute_without_real_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    cfg, configpath = harness._configuration(tmp_path)
    loaded = harness._ch4_fixture(tmp_path, cfg)
    assert loaded["root"] == str(tmp_path)
    results = []
    paths = sorted((ROOT / "notebooks").glob("0[4-6]_*.ipynb"))
    harness._execute(paths, tmp_path, configpath, results, "ch4_complete", fake_maps=True)
    assert len(results) == 3
    outputs = tmp_path / "reports/automatic_notebooks"
    assert all(json.loads(path.read_text()) == [] for path in outputs.rglob("errors.json"))
    assert list(outputs.rglob("inventory.csv"))
    assert list(outputs.rglob("analysis.json"))
    for pattern in ("month_*.png", "annual_*.png", "climatology_*.png",
                    "anomaly_*.png"):
        assert list(outputs.rglob(pattern)), pattern
    manifest = next(outputs.rglob("map_manifest.json"))
    report = json.loads(manifest.read_text())
    assert {item["family"] for item in report["maps"]} >= {
        "monthly", "annual", "climatology", "anomaly"
    }
    assert all(str(path).startswith(str(tmp_path)) for path in outputs.rglob("*.png"))
