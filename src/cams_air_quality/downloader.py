"""Restartable ADS jobs and byte-range downloads with atomic verified commits."""

import json
import logging
import os
import random
import shutil
import time
from pathlib import Path

import requests
from filelock import FileLock

from .storage import Manifest, now, sha256
from .validation import validate_file

LOG = logging.getLogger("camsaq")


def make_client(cfg):
    from ecmwf.datastores import Client

    return Client(
        url=cfg["api_url"],
        timeout=cfg["http_timeout"],
        progress=False,
        maximum_tries=1,
        sleep_max=cfg["poll_seconds"],
    )


def safe_error(exc):
    # Do not write bearer tokens, signed URLs or response bodies to logs.
    if isinstance(exc, requests.HTTPError):
        return f"HTTP {exc.response.status_code if exc.response is not None else 'error'}; consult ADS jobs/profile/licence"
    if isinstance(exc, (ValueError, FileNotFoundError, TimeoutError)):
        return str(exc).split("https://")[0][:400]
    return type(exc).__name__


def download_range(url, target, expected, timeout):
    """Resume only when asset URL/size match; validate Content-Range and full length.

    Signed location is stored only as a SHA256 fingerprint, never as plaintext.
    An expired/refreshed URL restarts that partial payload, preserving job identity.
    """
    import hashlib

    target = Path(target)
    sidecar = Path(str(target) + ".json")
    identity = {"asset_sha256": hashlib.sha256(url.encode()).hexdigest(), "expected": expected}
    previous = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    offset = (
        target.stat().st_size
        if target.exists() and all(previous.get(k) == v for k, v in identity.items())
        else 0
    )
    if offset > expected:
        offset = 0
    if offset == expected and expected > 0:
        return
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        if previous.get("etag"):
            headers["If-Range"] = previous["etag"]
    with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        if r.status_code == 206:
            if not r.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                raise ValueError("Inconsistent resumed Content-Range")
            total = r.headers["Content-Range"].split("/")[-1]
            if total != str(expected):
                raise ValueError("Changed remote payload length")
        else:
            offset = 0
        sidecar.write_text(json.dumps({**identity, "etag": r.headers.get("ETag")}))
        with target.open("ab" if offset else "wb") as f:
            for block in r.iter_content(1024 * 1024):
                if block:
                    f.write(block)
            f.flush()
            os.fsync(f.fileno())
    if target.stat().st_size != expected:
        raise IOError("Incomplete payload size; partial retained for resume")


def download_batch(cfg, batch, client=None):
    manifest = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    manifest.add(batch)
    path = Path(batch.filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=1):
        row = manifest.get(batch.key)
        if manifest.intact(row):
            return {"key": batch.key, "status": "skipped", "bytes": row["filesize"]}
        # Recover completed file after crash between atomic rename and SQL commit.
        if path.exists():
            qc = validate_file(path, batch, cfg)
            if qc["status"] != "FAIL" and (not row["checksum"] or sha256(path) == row["checksum"]):
                manifest.set(
                    batch.key,
                    "validated",
                    checksum=sha256(path),
                    filesize=path.stat().st_size,
                    qc_json=json.dumps(qc),
                    error=None,
                    download_date=row["download_date"] or now(),
                )
                return {"key": batch.key, "status": "recovered"}
            path.rename(path.with_name(path.name + f".corrupt-{time.time_ns()}"))
        part = Path(str(path) + ".part")
        started = time.monotonic()
        for attempt in range(cfg["retry_attempts"]):
            try:
                if client is None:
                    client = make_client(cfg)
                row = manifest.get(batch.key)
                remote = None
                if row["remote_id"]:
                    try:
                        remote = client.get_remote(row["remote_id"])
                    except requests.HTTPError as exc:
                        if exc.response is None or exc.response.status_code not in (404, 410):
                            raise
                        manifest.set(batch.key, "requested", remote_id=None)
                if remote is None:
                    remote = client.submit(batch.dataset, batch.api_request)
                    manifest.set(batch.key, "requested", remote_id=remote.request_id, error=None)
                deadline = time.monotonic() + cfg["job_timeout_seconds"]
                while True:
                    status = remote.status
                    if status == "successful":
                        break
                    if status in ("failed", "dismissed"):
                        manifest.set(batch.key, "failed", remote_id=None)
                        raise ValueError(f"ADS remote job {status}")
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "ADS job polling deadline reached; remote id retained for resume"
                        )
                    time.sleep(cfg["poll_seconds"])
                results = remote.get_results()
                size = int(results.content_length)
                if size < cfg["qc"]["minimum_bytes"]:
                    raise ValueError("Empty/small remote asset")
                if size > cfg["max_download_gib"] * 2**30:
                    raise ValueError("Batch exceeds configured size limit")
                if (
                    shutil.disk_usage(path.parent).free
                    < size * cfg["storage_copies"] + cfg["min_free_disk_gib"] * 2**30
                ):
                    raise ValueError("Insufficient free disk for batch and processing reserve")
                manifest.set(batch.key, "downloading", filesize=size)
                download_range(results.location, part, size, cfg["http_timeout"])
                manifest.set(
                    batch.key, "downloaded", download_date=now(), filesize=part.stat().st_size
                )
                qc = validate_file(part, batch, cfg)
                manifest.set(batch.key, "downloaded", qc_json=json.dumps(qc))
                if qc["status"] == "FAIL":
                    part.rename(part.with_name(part.name + f".corrupt-{time.time_ns()}"))
                    raise ValueError("Payload QC failed: " + "; ".join(qc["failures"]))
                checksum = sha256(part)
                os.replace(part, path)
                Path(str(part) + ".json").unlink(missing_ok=True)
                manifest.set(batch.key, "validated", checksum=checksum, error=None)
                LOG.info(
                    json.dumps(
                        {
                            "timestamp": now(),
                            "dataset": batch.dataset,
                            "variable": batch.variable,
                            "year": batch.year,
                            "month": batch.month,
                            "request": batch.api_request,
                            "status": "validated",
                            "download_size": size,
                            "elapsed_seconds": time.monotonic() - started,
                            "retry": attempt,
                        }
                    )
                )
                return {"key": batch.key, "status": "validated", "bytes": size}
            except Exception as exc:
                error = safe_error(exc)
                manifest.set(batch.key, "failed", error=error)
                LOG.error(
                    json.dumps(
                        {
                            "timestamp": now(),
                            "dataset": batch.dataset,
                            "variable": batch.variable,
                            "year": batch.year,
                            "month": batch.month,
                            "request": batch.api_request,
                            "status": "failed",
                            "elapsed_seconds": time.monotonic() - started,
                            "error": error,
                            "retry": attempt,
                        }
                    )
                )
                permanent = isinstance(exc, (FileNotFoundError, ValueError, TimeoutError)) or (
                    isinstance(exc, requests.HTTPError)
                    and exc.response is not None
                    and exc.response.status_code in (400, 401, 403, 404, 422)
                )
                if permanent or attempt + 1 == cfg["retry_attempts"]:
                    return {"key": batch.key, "status": "failed", "error": error}
                time.sleep(min(60, cfg["backoff_seconds"] * 2**attempt) + random.random())
