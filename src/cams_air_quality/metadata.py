import json
import subprocess

from . import __version__
from .storage import now


def code_version(root):
    try:
        rev = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True
        ).strip()
        return rev + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return f"package-{__version__}"


def provenance(batch, row, cfg):
    return {
        "source": "EAC4",
        "product": "CAMS Global Reanalysis EAC4",
        "ifs_cycle": "CY42R1",
        "dataset": batch.dataset,
        "api_request": json.dumps(batch.api_request, sort_keys=True),
        "raw_file": row["filepath"],
        "raw_sha256": row["checksum"],
        "download_date": row["download_date"] or "unknown",
        "processed_at": now(),
        "code_version": code_version(cfg["root"]),
        "catalog_sha256": batch.catalog_sha256,
        "temporal_resolution": batch.temporal_resolution,
        "source_level_type": batch.level_type,
        "source_level": str(batch.level),
        "horizontal_resolution_degrees": cfg["grid"]["spacing_degrees"],
        "coordinate_system": "geographic latitude/longitude on ECMWF model sphere; preserve GRIB earth-shape metadata; not an asserted WGS84 datum",
        "history": "decode; verify level; normalize dimensions; explicit registry unit conversion; partitioned NetCDF4",
    }
