"""Cartopy rendering isolated from NetCDF/Zarr/Parquet native libraries."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


def cell_edges(centres, polar=False):
    centres = np.asarray(centres, dtype=float)
    if centres.size < 2 or not np.all(np.diff(centres) > 0):
        raise ValueError("Map coordinates need at least two ordered centres")
    spacing = np.diff(centres)
    if not np.allclose(spacing, spacing[0]):
        raise ValueError("Map requires a contiguous regular grid")
    edges = np.r_[
        centres[0] - spacing[0] / 2, (centres[:-1] + centres[1:]) / 2, centres[-1] + spacing[-1] / 2
    ]
    return np.clip(edges, -90, 90) if polar else edges


def plot_map(da, path, title=None, anomaly=False, coastlines=False):
    """Render one field in a separate process; atomically publish only on exit code 0."""
    if set(da.dims) != {"latitude", "longitude"}:
        raise ValueError("Map requires a single latitude/longitude field")
    a = da.assign_coords(longitude=(da.longitude + 180) % 360 - 180)
    a = a.sortby("longitude").sortby("latitude").transpose("latitude", "longitude")
    lat_edges = cell_edges(a.latitude.values, polar=True)
    lon_edges = cell_edges(a.longitude.values)
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cams-map-", dir=path.parent) as directory:
        temp = Path(directory)
        np.savez(
            temp / "field.npz",
            values=a.compute().values,
            latitude_edges=lat_edges,
            longitude_edges=lon_edges,
        )
        (temp / "options.json").write_text(
            json.dumps(
                {
                    "title": str(title or da.attrs.get("long_name", da.name)),
                    "units": str(da.attrs.get("units", "")),
                    "anomaly": bool(anomaly),
                    "coastlines": bool(coastlines),
                }
            )
        )
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "cams_air_quality.map_worker",
                str(temp / "field.npz"),
                str(temp / "options.json"),
                str(temp / "map.png"),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if run.returncode != 0:
            raise RuntimeError(f"Map renderer exited {run.returncode}: {run.stderr[-1000:]}")
        os.replace(temp / "map.png", path)
    return path


def render_arrays(
    values, lat_edges, lon_edges, path, title, units, anomaly=False, coastlines=False
):
    """Internal worker; imports Cartopy only inside the isolated rendering process."""
    import matplotlib

    matplotlib.use("Agg")
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt

    # Align the projection seam with a cell boundary. Coordinates below are the
    # exact PlateCarree projected x/y coordinates (degree shift only), not resampled.
    central = float((lon_edges[0] + lon_edges[-1]) / 2)
    projection = ccrs.PlateCarree(central_longitude=central)
    fig = plt.figure(figsize=(12, 5.5))
    try:
        ax = fig.add_subplot(111, projection=projection)
        kw = {"cmap": "RdBu_r" if anomaly else "viridis"}
        if anomaly:
            lim = float(np.nanmax(np.abs(values))) or 1.0
            kw.update(vmin=-lim, vmax=lim)
        mesh = ax.pcolormesh(
            lon_edges - central, lat_edges, values, transform=projection, shading="flat", **kw
        )
        ax.set_xlim(lon_edges[0] - central, lon_edges[-1] - central)
        ax.set_ylim(lat_edges[0], lat_edges[-1])
        if coastlines:
            ax.coastlines(resolution="110m", linewidth=0.5)
        ax.gridlines(draw_labels=True, linewidth=0.25)
        ax.set_title(title)
        fig.colorbar(mesh, ax=ax, label=units, shrink=0.8, pad=0.08)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160, bbox_inches="tight")
    finally:
        plt.close(fig)
    return path
