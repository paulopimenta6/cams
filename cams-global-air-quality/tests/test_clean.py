"""Cleanup safety tests use synthetic temporary roots only."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock
from test_ghg_inversion import synthetic_ch4

from cams_air_quality import ghg_inversion as ghg
from cams_air_quality.cleanup import clean, resolve_targets
from cams_air_quality.cli import main, run_ch4_command
from cams_air_quality.storage import Manifest


@pytest.fixture
def ch4_cfg(cfg):
    cfg["ghg_inversion"]["grid"] = {
        "latitude": 3, "longitude": 4, "spacing_degrees": 1.0, "global": False,
    }
    cfg["ghg_inversion"]["levels"] = 3
    cfg["ghg_inversion"]["chunks"] = {"time": 1, "level": 1, "latitude": 3,
                                          "longitude": 4}
    return cfg


def _prepared(cfg, tmp_path):
    source = synthetic_ch4(
        tmp_path / "cams73_v25r1_ch4_conc_first_guess_dm_202409.nc"
    )
    batch, _ = ghg.import_file(cfg, source)
    processed = ghg.process_batch(cfg, batch)
    return batch, processed


def test_dry_run_reports_bytes_without_changes(cfg, tmp_path):
    file = tmp_path / "data/interim/unpacked/sample.nc"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"12345")
    before = set(tmp_path.rglob("*"))
    report = clean(cfg, ["interim"], "all", execute=False)
    assert report["bytes"] == 5 and report["count"] == 1
    assert report["deleted"] == [] and file.read_bytes() == b"12345"
    assert set(tmp_path.rglob("*")) == before
    assert resolve_targets(cfg, ["interim"], "all") == report["items"]


def test_cli_json_dry_run_creates_no_directories(tmp_path, capsys):
    project = tmp_path / "project"
    config = project / "config"
    config.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "config"
    (config / "config.yaml").write_text((source / "config.yaml").read_text())
    (config / "pollutants.yaml").write_text((source / "pollutants.yaml").read_text())
    file = project / "reports/ch4_inversion_test/generated.csv"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"synthetic")
    assert main(["--config", str(config / "config.yaml"), "clean", "--scope",
                 "reports", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["execute"] is False and report["bytes"] == len(b"synthetic")
    assert file.is_file()
    assert not (project / "data").exists()
    assert not (project / "metadata").exists()
    assert not (project / "logs").exists()


def test_reports_whitelist_git_and_markdown(cfg, tmp_path):
    reports = tmp_path / "reports"
    folder = reports / "ch4_inversion_run"
    folder.mkdir(parents=True)
    tracked = folder / "tracked.csv"
    tracked.write_text("keep")
    removable = folder / "generated.csv"
    removable.write_text("remove")
    markdown = folder / "notes.md"
    markdown.write_text("keep")
    phase_report = reports / "PHASE1_REPORT.md"
    phase_report.write_text("keep")
    strange = reports / "personal.csv"
    strange.write_text("keep")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "reports/ch4_inversion_run/tracked.csv"],
                   check=True)
    report = clean(cfg, ["reports"], "all", execute=True)
    assert not report["errors"]
    assert not removable.exists()
    assert tracked.exists() and markdown.exists() and strange.exists()
    assert phase_report.exists()


def test_processed_ch4_reconstructs_from_verified_raw(ch4_cfg, tmp_path):
    batch, processed = _prepared(ch4_cfg, tmp_path)
    report = clean(ch4_cfg, ["processed"], "ch4", execute=True)
    assert not report["errors"]
    row = ghg.manifest(ch4_cfg).get(batch.key)
    assert row["status"] == "validated"
    assert row["processed_path"] is None and Path(batch.filepath).is_file()
    assert not processed.exists()
    rebuilt = ghg.process_batch(ch4_cfg, batch)
    assert rebuilt.is_file()


def test_raw_and_processed_cleaned_validate_skips(ch4_cfg, tmp_path, capsys):
    batch, _ = _prepared(ch4_cfg, tmp_path)
    report = clean(ch4_cfg, ["raw", "processed"], "ch4", execute=True)
    assert not report["errors"]
    row = ghg.manifest(ch4_cfg).get(batch.key)
    assert row["status"] == "cleaned" and row["processed_path"] is None
    assert run_ch4_command(SimpleNamespace(ch4_command="validate"), ch4_cfg) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
    with pytest.raises(ValueError, match="No verified processed CH4"):
        ghg.analyze(ch4_cfg, 1, tmp_path / "analysis", maps=False)
    source = tmp_path / "cams73_v25r1_ch4_conc_first_guess_dm_202409.nc"
    Path(batch.filepath).parent.mkdir(parents=True)
    Path(batch.filepath).write_bytes(source.read_bytes())
    result = ghg.download(ch4_cfg, [batch], client=SimpleNamespace())
    assert result[0]["status"] == "recovered"
    assert ghg.manifest(ch4_cfg).get(batch.key)["status"] == "processed"


def test_raw_only_keeps_processed_and_warns(ch4_cfg, tmp_path, capsys):
    batch, processed = _prepared(ch4_cfg, tmp_path)
    clean(ch4_cfg, ["raw"], "ch4", execute=True)
    row = ghg.manifest(ch4_cfg).get(batch.key)
    assert row["status"] == "processed" and processed.is_file()
    assert run_ch4_command(SimpleNamespace(ch4_command="validate"), ch4_cfg) == 0
    assert "raw_missing_processed_intact" in capsys.readouterr().out
    with ghg.manifest(ch4_cfg).connect() as conn:
        events = conn.execute("SELECT status FROM events WHERE key=?", (batch.key,)).fetchall()
    assert "raw_removed" in [event[0] for event in events]


def test_manifest_backup_and_idempotence(cfg, tmp_path):
    db = tmp_path / "metadata/downloads.sqlite"
    Manifest(db)
    first = clean(cfg, ["manifest"], "eac4", execute=True)
    assert not first["errors"] and not db.exists()
    backup = Path(first["backups"][0])
    assert backup.exists() and backup.name.startswith("downloads.sqlite.bak-")
    second = clean(cfg, ["manifest"], "eac4", execute=True)
    assert second["count"] == 0 and second["bytes"] == 0


def test_everything_ch4_keeps_eac4_and_backs_up(cfg, tmp_path):
    ch4_db = tmp_path / "metadata/ghg_inversion/downloads.sqlite"
    eac4_db = tmp_path / "metadata/downloads.sqlite"
    Manifest(ch4_db)
    Manifest(eac4_db)
    raw = tmp_path / "data/raw/ghg_inversion/ch4.nc"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"synthetic")
    preview = clean(cfg, ["all"], "ch4", execute=False)
    assert not any(item["path"] in {str(raw), str(ch4_db)} for item in preview["items"])
    report = clean(cfg, ["everything"], "ch4", execute=True)
    assert not report["errors"]
    assert not ch4_db.exists() and not raw.exists()
    assert eac4_db.exists()
    assert len(report["backups"]) == 1


def test_zarr_stale_preserves_active_and_rejects_missing(cfg, tmp_path):
    root = tmp_path / "data/processed/eac4/monthly/zarr/scope"
    active = root / "2023-current.zarr"
    old = root / "2023-old.zarr"
    partial = root / "2024-new.zarr.part-token"
    for folder in (active, old, partial):
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"data")
    index = root / "index.json"
    index.write_text(json.dumps({"years": {"2023": {"path": active.name}}}))
    report = clean(cfg, ["zarr-stale"], "all", execute=True)
    assert not report["errors"]
    assert active.exists() and not old.exists() and not partial.exists()
    index.write_text(json.dumps({"years": {"2023": {"path": "missing.zarr"}}}))
    (root / "another.zarr").mkdir()
    blocked = clean(cfg, ["zarr-stale"], "all", execute=True)
    assert blocked["errors"] and (root / "another.zarr").exists()
    ch4_root = tmp_path / "data/processed/ghg_inversion/ch4/first_guess/v25r1/daily_mean/zarr"
    (ch4_root / "2023-current.zarr").mkdir(parents=True)
    (ch4_root / "2023-old.zarr").mkdir()
    (ch4_root / "index.json").write_text(json.dumps({
        "years": {"2023": {"path": "2023-current.zarr"}}
    }))
    partial = clean(cfg, ["zarr-stale"], "all", execute=True)
    assert partial["errors"] and not (ch4_root / "2023-old.zarr").exists()
    assert (root / "another.zarr").exists()


def test_tmp_skips_held_lock(cfg, tmp_path):
    folder = tmp_path / "data/raw/eac4"
    folder.mkdir(parents=True)
    lock = folder / "batch.lock"
    partial = folder / "batch.part"
    corrupt = folder / "batch.corrupt-123"
    partial.write_bytes(b"x")
    corrupt.write_bytes(b"x")
    with FileLock(str(lock), timeout=0):
        report = clean(cfg, ["tmp"], "all", execute=True)
        assert lock.exists() and report["skipped"]
    assert not partial.exists() and not corrupt.exists()


def test_processed_active_lock_aborts_and_symlink_is_refused(cfg, tmp_path):
    folder = tmp_path / "data/processed/ghg_inversion"
    folder.mkdir(parents=True)
    file = folder / "partition.nc"
    file.write_bytes(b"synthetic")
    with FileLock(str(file) + ".lock", timeout=0):
        blocked = clean(cfg, ["processed"], "ch4", execute=True)
        assert blocked["errors"] and file.exists()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "keep.nc").write_bytes(b"do not delete")
    (folder / "linked").symlink_to(outside, target_is_directory=True)
    blocked = clean(cfg, ["processed"], "ch4", execute=True)
    assert blocked["errors"] and (outside / "keep.nc").is_file()
    assert file.is_file()


def test_product_filter_and_everything_requirement(cfg, tmp_path):
    ch4 = tmp_path / "data/processed/ghg_inversion/ch4.nc"
    eac4 = tmp_path / "data/processed/eac4/pm25.nc"
    for file in (ch4, eac4):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"data")
    clean(cfg, ["processed"], "ch4", execute=True)
    assert not ch4.exists() and eac4.exists()
    clean(cfg, ["processed"], "eac4", execute=True)
    assert not eac4.exists()
    with pytest.raises(ValueError, match="requires --yes"):
        clean(cfg, ["everything"], "ch4", execute=False)
