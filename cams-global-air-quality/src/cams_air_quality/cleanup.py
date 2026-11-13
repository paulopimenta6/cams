"""Conservative cleanup of known generated files and manifest reconciliation."""

import logging
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from .storage import Manifest, sha256

SCOPES = {"reports", "interim", "processed", "raw", "manifest", "zarr-stale",
          "tmp", "logs", "catalog", "cache"}
ALL = {"reports", "interim", "processed", "zarr-stale", "tmp", "logs",
       "catalog", "cache"}
PROTECTED = {".git", ".venv", "envs", "node_modules", ".agents", ".codex"}
LOG = logging.getLogger("camsaq.cleanup")


def _scopes(scopes, execute):
    chosen = set(scopes)
    if not chosen or not chosen <= SCOPES | {"all", "everything"}:
        raise ValueError("Unknown or missing cleanup scope")
    if chosen & {"all", "everything"}:
        if len(chosen) != 1:
            raise ValueError("all/everything cannot be combined with other scopes")
        if "everything" in chosen and not execute:
            raise ValueError("everything requires --yes")
        return ALL | ({"raw", "manifest"} if "everything" in chosen else set())
    return chosen


def _root(cfg):
    root = Path(cfg["root"]).absolute()
    if root.is_symlink():
        raise ValueError("Cleanup root must not be a symlink")
    return root


def _safe(root, path):
    path = Path(path).absolute()
    if path == root or root not in path.parents:
        raise ValueError(f"Refusing target outside cleanup root: {path}")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Refusing symlink: {current}")
        current = current.parent
    if path.exists() and path.resolve() != path:
        raise ValueError(f"Refusing redirected target: {path}")
    return path


def _files(path):
    if path.is_symlink():
        raise ValueError(f"Refusing symlink: {path}")
    if path.is_file():
        yield path
    elif path.is_dir():
        for base, dirs, files in os.walk(path, followlinks=False):
            base = Path(base)
            for name in dirs + files:
                if (base / name).is_symlink():
                    raise ValueError(f"Refusing symlink: {base / name}")
            for name in files:
                yield base / name


def _item(root, path, kind):
    path = _safe(root, path)
    if not path.exists():
        return None
    return {"path": str(path), "kind": kind,
            "bytes": sum(file.stat().st_size for file in _files(path))}


def _tracked(root, path):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", str(path.relative_to(root))],
            capture_output=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _report_files(root):
    reports = root / "reports"
    if reports.is_symlink():
        raise ValueError(f"Refusing symlink: {reports}")
    candidates = []
    for pattern in ("ch4_inversion*", "one_year", "automatic_notebooks", "notebook_maps",
                    "exploratory", "troubleshooting", "map*.png", "regional_no2.csv*",
                    "sao_paulo_pm25.parquet*"):
        candidates.extend(reports.glob(pattern) if reports.exists() else [])
    for candidate in candidates:
        for file in _files(candidate):
            if file.suffix.lower() != ".md" and not _tracked(root, file):
                yield file


def _stale(root, data, product):
    base = data / "processed" / ("ghg_inversion" if product == "ch4" else "eac4")
    if not base.exists():
        return []
    found = []
    for folder in base.rglob("zarr"):
        if folder.is_symlink() or not folder.is_dir():
            continue
        indexes = list(folder.rglob("index.json"))
        for index in indexes:
            _safe(root, index)
            import json

            content = json.loads(index.read_text(encoding="utf-8"))
            active = set()
            for year, info in content.get("years", {}).items():
                name = info.get("path", "")
                target = _safe(root, index.parent / name)
                if target.parent != index.parent or not target.is_dir():
                    raise ValueError(
                        f"{product}: index {index} references missing/unsafe {year}: {name}"
                    )
                active.add(target.name)
            for candidate in index.parent.iterdir():
                if candidate.is_dir() and (
                    candidate.name.endswith(".zarr") or ".part-" in candidate.name
                ) and candidate.name not in active:
                    found.append(candidate)
    return found


def _walk_managed(roots):
    for base in roots:
        if base.exists() and not base.is_symlink():
            for directory, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = [d for d in dirs if d not in PROTECTED]
                for file in files:
                    yield Path(directory) / file


def _cache_paths(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        directory = Path(directory)
        kept = []
        for name in dirs:
            if name in PROTECTED:
                continue
            path = directory / name
            if name in {".pytest_cache", ".ruff_cache", "__pycache__", "build", "dist"} \
                    or name.endswith(".egg-info"):
                yield path
            else:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            if re.search(r"\.py[cod]$", name):
                yield directory / name


def _discover(cfg, scopes, product, execute):
    chosen = _scopes(scopes, execute)
    if product not in {"ch4", "eac4", "all"}:
        raise ValueError("product must be ch4, eac4 or all")
    root = _root(cfg)
    data = _safe(root, cfg["data_dir"])
    metadata = _safe(root, cfg["metadata_dir"])
    logs = _safe(root, cfg["log_dir"])
    products = ("ch4", "eac4") if product == "all" else (product,)
    paths = []
    errors = []
    product_errors = []
    blocked_products = set()

    def add(path, kind):
        try:
            item = _item(root, path, kind)
            if item is not None:
                paths.append(item)
        except ValueError as exc:
            errors.append(str(exc))

    if "reports" in chosen:
        try:
            for file in _report_files(root):
                add(file, "reports")
        except ValueError as exc:
            errors.append(str(exc))
    if "interim" in chosen:
        add(data / "interim/unpacked", "interim")
        interim = data / "interim"
        if interim.is_dir():
            for folder in interim.rglob("*"):
                if folder.is_symlink():
                    errors.append(f"Refusing symlink: {folder}")
                    continue
                if folder.is_dir() and not any(folder.iterdir()):
                    add(folder, "interim-empty")
    for name in products:
        folder = "ghg_inversion" if name == "ch4" else "eac4"
        if "processed" in chosen:
            add(data / "processed" / folder, f"processed:{name}")
        if "raw" in chosen:
            add(data / "raw" / folder, f"raw:{name}")
        if "manifest" in chosen:
            db = (metadata / "ghg_inversion/downloads.sqlite" if name == "ch4"
                  else metadata / "downloads.sqlite")
            for candidate in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
                add(candidate, f"manifest:{name}")
    if "zarr-stale" in chosen:
        for name in ("ch4", "eac4"):
            try:
                for path in _stale(root, data, name):
                    add(path, f"zarr-stale:{name}")
            except (ValueError, OSError, KeyError) as exc:
                message = f"zarr-stale blocked for {name}: {exc}"
                errors.append(message)
                product_errors.append(message)
                blocked_products.add(name)
                paths = [p for p in paths if p["kind"] != f"zarr-stale:{name}"]
    if "tmp" in chosen:
        for file in _walk_managed((data, metadata, logs, root / "reports")):
            if (file.name.endswith((".part", ".part.json", ".lock"))
                    or ".corrupt-" in file.name):
                add(file, "tmp")
    if "logs" in chosen:
        for file in logs.glob("*.log*"):
            if file.name.endswith(".log") or ".log." in file.name:
                add(file, "logs")
    if "catalog" in chosen:
        for file in (metadata / "catalog").glob("*.json"):
            add(file, "catalog")
    if "cache" in chosen:
        for path in _cache_paths(root):
            add(path, "cache")
    blocked_roots = [
        data / sub / ("ghg_inversion" if name == "ch4" else "eac4")
        for name in blocked_products for sub in ("raw", "processed")
    ]
    paths = [
        item for item in paths
        if not any(item["kind"] == f"{kind}:{name}"
                   for name in blocked_products
                   for kind in ("raw", "processed", "manifest", "zarr-stale"))
        and not any(Path(item["path"]).is_relative_to(folder) for folder in blocked_roots)
    ]
    # A directory target takes precedence over any item nested inside it.
    paths.sort(key=lambda p: (len(Path(p["path"]).parts), p["path"]))
    selected = []
    for item in paths:
        if not any(Path(parent["path"]) in Path(item["path"]).parents
                   or parent["path"] == item["path"] for parent in selected):
            selected.append(item)
    return selected, errors, product_errors


def resolve_targets(cfg: dict, scopes: list[str], product: str) -> list[dict]:
    """List existing targets with byte estimates; never alter files or SQLite."""
    items, errors, _ = _discover(cfg, scopes, product, execute=False)
    if errors:
        raise ValueError("; ".join(errors))
    return items


def _active_lock(path):
    try:
        lock = FileLock(str(path), timeout=0)
        with lock:
            return False
    except Timeout:
        return True


def _locks_for(item):
    path = Path(item["path"])
    if path.is_dir():
        locks = [file for file in _files(path) if file.name.endswith(".lock")]
        sibling = Path(str(path) + ".lock")
        if sibling.exists():
            locks.append(sibling)
        return locks
    return [path] if path.name.endswith(".lock") else [Path(str(path) + ".lock")]


def _backup_manifest(path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(path.name + f".bak-{stamp}")
    temporary = target.with_name(target.name + ".part")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(temporary) as destination:
            source.backup(destination)
    os.replace(temporary, target)
    return str(target)


def _sqlite_busy(path):
    try:
        with sqlite3.connect(path, timeout=0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        return False
    except sqlite3.OperationalError:
        return True


def reconcile_manifest(cfg: dict, product: str, removed_kinds: set[str]) -> None:
    """Update existing rows after raw/processed deletion, preserving intact derivatives."""
    if not ({"raw", "processed"} & removed_kinds):
        return
    root = _root(cfg)
    metadata = _safe(root, cfg["metadata_dir"])
    path = (metadata / "ghg_inversion/downloads.sqlite" if product == "ch4"
            else metadata / "downloads.sqlite")
    if not path.is_file():
        return
    manifest = Manifest(path)
    for row in manifest.rows():
        raw = Path(row["filepath"])
        processed = Path(row["processed_path"]) if row["processed_path"] else None
        raw_ok = raw.is_file() and bool(row["checksum"]) and sha256(raw) == row["checksum"]
        processed_ok = (processed is not None and processed.is_file()
                        and bool(row["processed_checksum"])
                        and sha256(processed) == row["processed_checksum"])
        if "processed" in removed_kinds and row["processed_path"] and not processed_ok:
            if raw_ok:
                manifest.set(row["key"], "validated", processed_path=None,
                             processed_checksum=None, processing_error=None, error=None)
            else:
                manifest.set(row["key"], "cleaned", processed_path=None,
                             processed_checksum=None, processing_error=None,
                             error="Processed derivative removed; verified raw is unavailable")
        elif "raw" in removed_kinds and not raw_ok and processed_ok:
            manifest.event(row["key"], "raw_removed", {"filepath": str(raw)})
        elif "raw" in removed_kinds and not raw_ok and not processed_ok \
                and row["status"] != "cleaned":
            manifest.set(row["key"], "cleaned", processed_path=None,
                         processed_checksum=None, processing_error=None,
                         error="Raw removed and no intact processed derivative remains")


def clean(cfg: dict, scopes: list[str], product: str, execute: bool,
          force: bool = False, manifest_backup: bool = True) -> dict:
    """Preview by default; execute only explicit known targets after safety checks."""
    items, errors, product_errors = _discover(cfg, scopes, product, execute=execute)
    report = {"execute": bool(execute), "items": items,
              "count": len(items), "bytes": sum(item["bytes"] for item in items),
              "deleted": [], "skipped": [], "backups": [], "errors": errors}
    if not execute:
        return report
    root = _root(cfg)
    # Reject active writers before any destructive operation.
    for item in items:
        if item["kind"].split(":")[0] in {"processed", "raw", "zarr-stale", "manifest"}:
            for lock in _locks_for(item):
                if lock.exists() and _active_lock(lock) and not force:
                    report["errors"].append(f"Active lock {lock}; use --force to override")
        if item["kind"].startswith("manifest:") and Path(item["path"]).name == "downloads.sqlite":
            if _sqlite_busy(item["path"]) and not force:
                report["errors"].append(
                    f"Active SQLite writer {item['path']}; use --force to override"
                )
    if any(error not in product_errors for error in report["errors"]):
        return report
    manifest_paths = [Path(item["path"]) for item in items
                      if item["kind"].startswith("manifest:")
                      and Path(item["path"]).name == "downloads.sqlite"]
    if manifest_backup:
        for path in manifest_paths:
            try:
                report["backups"].append(_backup_manifest(path))
            except (OSError, sqlite3.Error) as exc:
                report["errors"].append(f"Manifest backup failed for {path}: {exc}")
        if any(error not in product_errors for error in report["errors"]):
            return report
    removed = {"ch4": set(), "eac4": set()}
    for item in items:
        path = Path(item["path"])
        try:
            _safe(root, path)
            if item["kind"] == "tmp" and path.name.endswith(".lock") \
                    and _active_lock(path):
                report["skipped"].append({"path": str(path), "reason": "lock is held"})
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            report["deleted"].append(str(path))
            LOG.info("Removed generated target %s", path)
            if ":" in item["kind"]:
                kind, name = item["kind"].split(":", 1)
                if kind in {"raw", "processed"}:
                    removed[name].add(kind)
        except (OSError, ValueError) as exc:
            report["errors"].append(f"Could not remove {path}: {exc}")
    for database in manifest_paths:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                try:
                    _safe(root, sidecar)
                    sidecar.unlink()
                    report["deleted"].append(str(sidecar))
                except (OSError, ValueError) as exc:
                    report["errors"].append(f"Could not remove {sidecar}: {exc}")
    for name, kinds in removed.items():
        if kinds and not any(str(p).endswith("downloads.sqlite") and
                             ("ghg_inversion" in str(p)) == (name == "ch4")
                             for p in manifest_paths):
            reconcile_manifest(cfg, name, kinds)
    # Remove only empty generated parents, never user directories with content.
    for folder in (Path(cfg["data_dir"]) / "interim", root / "reports/ch4_inversion"):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return report
