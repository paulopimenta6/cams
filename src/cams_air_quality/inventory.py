from pathlib import Path

import pandas as pd

from .storage import Manifest


def inventory(cfg, batches):
    manifest = Manifest(Path(cfg["metadata_dir"]) / "downloads.sqlite")
    rows = {r["key"]: r for r in manifest.rows()}
    records = []
    for v in sorted({b.variable for b in batches}):
        expected = [b for b in batches if b.variable == v]
        present = [b for b in expected if b.key in rows and manifest.intact(rows[b.key])]
        dates = [f"{b.year:04d}-{b.month:02d}" for b in present]
        missing = [f"{b.year:04d}-{b.month:02d}" for b in expected if b not in present]
        records.append(
            {
                "pollutant": v,
                "expected_first": f"{expected[0].year}-{expected[0].month:02d}",
                "expected_last": f"{expected[-1].year}-{expected[-1].month:02d}",
                "first_date": min(dates) if dates else None,
                "last_date": max(dates) if dates else None,
                "months_expected": len(expected),
                "months_available": len(present),
                "missing": len(missing),
                "missing_months": ",".join(missing),
                "files": len(present),
                "bytes": sum(rows[b.key]["filesize"] for b in present),
                "status": "COMPLETE" if not missing else "EMPTY" if not present else "INCOMPLETE",
            }
        )
    return pd.DataFrame(records)
