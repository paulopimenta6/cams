import argparse
import json
import logging
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from .catalog import fetch_catalog, load_snapshot
from .config import load_config
from .downloader import download_batch, safe_error
from .inventory import inventory
from .processing import batch_from_row, consolidate, open_database, process_batch
from .requests import estimate, plan_batches
from .storage import Manifest, sha256
from .validation import validate_file


def parser():
    p = argparse.ArgumentParser(
        prog="camsaq", description="CAMS EAC4 reproducible historical archive"
    )
    p.add_argument("--config", default="config/config.yaml")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("inventory", "plan", "download-monthly", "download-subdaily", "update", "smoke"):
        c = sub.add_parser(name)
        c.add_argument("--start")
        c.add_argument("--end")
        c.add_argument("--pollutants", nargs="+")
        if name not in ("download-monthly", "download-subdaily", "update"):
            c.add_argument("--kind", choices=["monthly", "subdaily"], default="monthly")
        if name in ("inventory", "plan"):
            c.add_argument(
                "--offline-evidence", help="Explicit historical snapshot, never live availability"
            )
        if name in ("download-monthly", "download-subdaily", "update"):
            c.add_argument("--max-batches", type=int)
            c.add_argument("--retry-failed", action="store_true")
    sub.add_parser("validate")
    c = sub.add_parser("process")
    c.add_argument("--kind", choices=["monthly", "subdaily"], default="monthly")
    c = sub.add_parser("consolidate")
    c.add_argument("--kind", choices=["monthly", "subdaily"], default="monthly")
    for name in ("extract-point", "extract-region"):
        c = sub.add_parser(name)
        c.add_argument("--pollutant", required=True)
        c.add_argument("--output", required=True)
        if name == "extract-point":
            c.add_argument("--lat", required=True, type=float)
            c.add_argument("--lon", required=True, type=float)
        else:
            c.add_argument("--bbox", nargs=4, required=True, type=float)
    c = sub.add_parser("map")
    c.add_argument("--pollutant", required=True)
    c.add_argument("--date", required=True)
    c.add_argument("--output", default="reports/map.png")
    c.add_argument("--coastlines", action="store_true")
    c = sub.add_parser("analyze")
    c.add_argument("--baseline-start", required=True)
    c.add_argument("--baseline-end", required=True)
    c.add_argument("--output", default="reports/exploratory")
    ch4 = sub.add_parser("ch4", help="CAMS greenhouse-gas inversion CH4, separate from EAC4")
    actions = ch4.add_subparsers(dest="ch4_command", required=True)
    for name in ("plan", "download"):
        c = actions.add_parser(name)
        c.add_argument("--start", required=True, help="First month, YYYY-MM")
        c.add_argument("--end", help="Last month, YYYY-MM; defaults to start")
        c.add_argument("--version", help="Pinned CAMS release; default from config")
    c = actions.add_parser("import", help="Validate and archive an existing CAMS73 NetCDF")
    c.add_argument("--file", required=True)
    actions.add_parser("validate")
    actions.add_parser("process")
    c = actions.add_parser("consolidate")
    c.add_argument("--version", help="Resolved release; default from config")
    c = actions.add_parser("analyze")
    c.add_argument("--version", help="Resolved release; default from config")
    c.add_argument("--level", type=int, required=True, help="Explicit model layer: 1 is lowest")
    c.add_argument("--output", default="reports/ch4_inversion")
    c.add_argument("--lat", type=float, default=-23.5505)
    c.add_argument("--lon", type=float, default=-46.6333)
    c.add_argument("--bbox", nargs=4, type=float, metavar=("N", "W", "S", "E"))
    c.add_argument("--no-maps", action="store_true")
    return p


def run_ch4_command(args, cfg):
    from . import ghg_inversion as ghg

    cmd = args.ch4_command
    version = getattr(args, "version", None) or cfg["ghg_inversion"]["version"]
    if cmd in ("plan", "download"):
        snap = ghg.fetch_ch4_catalog(cfg)
        batches = ghg.plan_batches(cfg, snap, args.start, args.end, version)
        resources = ghg.estimate(batches, cfg["storage_copies"])
        print(json.dumps({"estimate": resources, "requests": [b.to_dict() for b in batches]}, indent=2))
        if cmd == "plan":
            return 0
        need = resources["planning_disk_GiB"] + cfg["min_free_disk_gib"]
        if shutil.disk_usage(cfg["data_dir"]).free / 2**30 < need:
            raise ValueError("Insufficient disk for selected CH4 months")
        results = ghg.download(cfg, batches)
        print(json.dumps(results, indent=2))
        if any(r["status"] in ("failed", "processing_failed") for r in results):
            return 1
        m = ghg.manifest(cfg)
        releases = {
            ghg._release(row)
            for result in results
            if (row := m.get(result["key"])) and row["status"] == "processed"
        }
        for release in releases - {None}:
            print(ghg.consolidate(cfg, release))
        return 0
    if cmd == "import":
        batch, qc = ghg.import_file(cfg, args.file)
        processed = ghg.process_batch(cfg, batch)
        index = ghg.consolidate(cfg, qc["resolved_release"])
        print(json.dumps({"raw": batch.filepath, "processed": str(processed),
                          "index": str(index), "qc": qc}, indent=2))
        return 0
    if cmd == "validate":
        m = ghg.manifest(cfg)
        records = []
        for row in m.rows():
            batch = batch_from_row(row)
            qc = ghg.validate_file(row["filepath"], batch, cfg)
            previous = json.loads(row["qc_json"] or "{}")
            qc.update({k: previous[k] for k in ("request_origin", "source_filename") if k in previous})
            if qc["status"] != "FAIL" and row["checksum"] and sha256(row["filepath"]) != row["checksum"]:
                qc["status"] = "FAIL"
                qc["failures"].append("Stored raw checksum mismatch")
            status = "failed" if qc["status"] == "FAIL" else (
                "processed" if row["status"] == "processed" else "validated"
            )
            fields = {"qc_json": json.dumps(qc), "error": "; ".join(qc["failures"]) or None}
            if status != "failed":
                fields.update(checksum=sha256(row["filepath"]),
                              filesize=Path(row["filepath"]).stat().st_size)
            m.set(row["key"], status, **fields)
            records.append({"key": row["key"], **qc})
        print(json.dumps(records, indent=2))
        return int(any(r["status"] == "FAIL" for r in records))
    if cmd == "process":
        outputs = []
        for row in ghg.manifest(cfg).rows():
            if row["status"] in ("validated", "processed"):
                outputs.append(str(ghg.process_batch(cfg, batch_from_row(row))))
        print(json.dumps(outputs, indent=2))
        return 0
    if cmd == "consolidate":
        print(ghg.consolidate(cfg, version))
        return 0
    if cmd == "analyze":
        report = ghg.analyze(cfg, args.level, args.output, version, lat=args.lat, lon=args.lon,
                             bbox=args.bbox, maps=not args.no_maps)
        print(json.dumps(report, indent=2, default=str))
        return 0
    raise ValueError(cmd)


def run_one(cfg, b):
    result = download_batch(cfg, b)
    if result["status"] != "failed":
        try:
            result["processed"] = str(process_batch(cfg, b))
        except Exception as exc:
            m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
            m.set(b.key, "validated", processing_error=safe_error(exc))
            result.update(status="processing_failed", error=safe_error(exc))
    return result


def download_plan(cfg, batches, max_batches=None, retry_failed=False):
    m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    selected = []
    for b in batches:
        r = m.get(b.key)
        if retry_failed and (not r or r["status"] != "failed"):
            continue
        if r and m.intact(r) and r["status"] == "processed":
            # process_batch checks processed checksums and current conversion policy too.
            process_batch(cfg, b)
            continue
        selected.append(b)
    if max_batches is not None:
        if max_batches < 1:
            raise ValueError("max-batches must be positive")
        selected = selected[:max_batches]
    resources = estimate(cfg, selected)
    print(json.dumps(resources, indent=2))
    need = resources["planning_disk_GiB"] + cfg["min_free_disk_gib"]
    if shutil.disk_usage(cfg["data_dir"]).free / 2**30 < need:
        raise ValueError(
            "Insufficient disk for selected plan: use --max-batches or a larger data_dir"
        )
    if not selected:
        return []
    # First real request for every vertical representation must pass before bulk work.
    pilots = []
    for representation in sorted({b.level_type for b in selected}):
        pilots.append(next(b for b in selected if b.level_type == representation))
    results = []
    for b in pilots:
        r = run_one(cfg, b)
        results.append(r)
        if r["status"] in ("failed", "processing_failed"):
            return results
    remaining = [b for b in selected if b not in pilots]
    if cfg["workers"] == 1:
        for b in remaining:
            r = run_one(cfg, b)
            results.append(r)
            if r.get("error", "").startswith(("HTTP 401", "HTTP 403", "Insufficient free disk")):
                break
    else:
        # Process isolation avoids the netCDF/HDF5 thread-safety pitfalls.
        with ProcessPoolExecutor(max_workers=cfg["workers"]) as pool:
            results.extend(pool.map(partial(run_one, cfg), remaining, chunksize=1))
    return results


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[
                logging.FileHandler(Path(cfg["log_dir"]) / "camsaq.log"),
                logging.StreamHandler(),
            ],
        )
        cmd = args.command
        if cmd == "ch4":
            return run_ch4_command(args, cfg)
        m = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
        if cmd in ("inventory", "plan", "download-monthly", "download-subdaily", "update", "smoke"):
            kind = "subdaily" if cmd == "download-subdaily" else getattr(args, "kind", "monthly")
            offline = getattr(args, "offline_evidence", None)
            snap = load_snapshot(offline, kind) if offline else fetch_catalog(cfg, kind)
            batches = plan_batches(cfg, snap, kind, args.start, args.end, args.pollutants)
            if cmd == "plan":
                payload = {
                    "availability": "OFFLINE SNAPSHOT" if offline else "LIVE ADS",
                    "estimate": estimate(cfg, batches),
                    "requests": [b.to_dict() for b in batches],
                }
                folder = Path(cfg["metadata_dir"])
                (folder / f"plan-{kind}.json").write_text(json.dumps(payload, indent=2))
                print(json.dumps(payload["estimate"], indent=2))
                return 0
            if cmd == "inventory":
                frame = inventory(cfg, batches)
                frame.to_csv(Path(cfg["metadata_dir"]) / f"inventory-{kind}.csv", index=False)
                print("Availability:", "OFFLINE SNAPSHOT" if offline else "LIVE ADS")
                print(frame.drop(columns="missing_months").to_string(index=False))
                return 0
            if cmd == "smoke":
                # First available month, one selected variable (default PM2.5).
                name = (args.pollutants or ["pm25"])[0]
                batches = [next(b for b in batches if b.variable == name)]
            results = download_plan(
                cfg,
                batches,
                getattr(args, "max_batches", None),
                getattr(args, "retry_failed", False),
            )
            print(json.dumps(results, indent=2))
            failed = any(r["status"] in ("failed", "processing_failed") for r in results)
            frame = inventory(cfg, batches)
            frame.to_csv(Path(cfg["metadata_dir"]) / f"inventory-{kind}.csv", index=False)
            # Full completed monthly plans become analytical datasets automatically.
            if not failed and cmd != "smoke" and all(frame["missing"] == 0) and not args.pollutants:
                consolidate(cfg, kind)
            return 1 if failed else 0
        if cmd == "validate":
            records = []
            for r in m.rows():
                b = batch_from_row(r)
                qc = validate_file(r["filepath"], b, cfg)
                if (
                    qc["status"] != "FAIL"
                    and r["checksum"]
                    and sha256(r["filepath"]) != r["checksum"]
                ):
                    qc.update(status="FAIL")
                    qc["failures"].append("Stored checksum mismatch")
                status = (
                    "failed"
                    if qc["status"] == "FAIL"
                    else "processed"
                    if r["status"] == "processed"
                    else "validated"
                )
                fields = {"qc_json": json.dumps(qc), "error": "; ".join(qc["failures"]) or None}
                if status != "failed":
                    fields.update(
                        checksum=sha256(r["filepath"]), filesize=Path(r["filepath"]).stat().st_size
                    )
                m.set(b.key, status, **fields)
                records.append({"key": b.key, **qc})
            target = Path(cfg["metadata_dir"]) / "qc-report.json"
            target.write_text(json.dumps(records, indent=2))
            print(f"{len(records)} files inspected: {target}")
            return int(any(x["status"] == "FAIL" for x in records))
        if cmd == "process":
            for r in m.rows():
                if (
                    r["status"] in ("validated", "processed")
                    and r["temporal_resolution"] == args.kind
                ):
                    process_batch(cfg, batch_from_row(r))
        elif cmd == "consolidate":
            print(consolidate(cfg, args.kind))
        elif cmd.startswith("extract-"):
            from .extraction import get_region_timeseries, get_timeseries, save_table

            f = (
                get_timeseries(cfg, args.pollutant, args.lat, args.lon)
                if cmd == "extract-point"
                else get_region_timeseries(cfg, args.pollutant, args.bbox)
            )
            save_table(f, args.output)
            print(args.output)
        elif cmd == "map":
            from .maps import plot_map

            with open_database(cfg) as ds:
                field = ds[args.pollutant].sel(time=args.date)
                if field.sizes.get("time", 0) == 1:
                    field = field.isel(time=0, drop=True)
                plot_map(field, args.output, coastlines=args.coastlines)
            print(args.output)
        elif cmd == "analyze":
            from .analysis import explore

            explore(cfg, args.output, args.baseline_start, args.baseline_end)
        return 0
    except Exception as exc:
        print(f"ERROR: {safe_error(exc)}", file=sys.stderr)
        return 1
