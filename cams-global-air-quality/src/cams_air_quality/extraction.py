import numpy as np
import xarray as xr


def check_bbox(bbox):
    if len(bbox) != 4:
        raise ValueError("bbox must be [north,west,south,east]")
    n, w, s, e = bbox
    if (
        not all(np.isfinite(bbox))
        or not -90 <= s <= n <= 90
        or not (-180 <= w <= 180 and -180 <= e <= 180)
    ):
        raise ValueError("Invalid bounding box")


def subset_bbox(ds, north, west, south, east):
    check_bbox([north, west, south, east])
    lat = (ds.latitude >= south) & (ds.latitude <= north)
    lon = (ds.longitude + 180) % 360 - 180
    if abs(east - west) == 360:
        mask = xr.ones_like(lon, dtype=bool)
    else:
        mask = ((lon >= west) & (lon <= east)) if west <= east else ((lon >= west) | (lon <= east))
    out = ds.where(lat & mask, drop=True)
    if not out.sizes.get("latitude") or not out.sizes.get("longitude"):
        raise ValueError("Bounding box contains no grid-cell centres")
    return out


def extract_point(ds, lat, lon):
    if (
        not np.isfinite(lat)
        or not np.isfinite(lon)
        or not -90 <= lat <= 90
        or not -180 <= lon <= 360
    ):
        raise ValueError("Invalid geographic coordinate")
    # Great-circle nearest centre: correct across antimeridian and at high latitudes.
    latr = np.deg2rad(ds.latitude.values)
    dlon = np.deg2rad((ds.longitude.values - lon + 180) % 360 - 180)
    cosine = (
        np.sin(np.deg2rad(lat)) * np.sin(latr)[:, None]
        + np.cos(np.deg2rad(lat)) * np.cos(latr)[:, None] * np.cos(dlon)[None, :]
    )
    i, j = np.unravel_index(np.argmax(cosine), cosine.shape)
    out = ds.isel(latitude=i, longitude=j)
    out.attrs = {
        **ds.attrs,
        "requested_latitude": lat,
        "requested_longitude": lon,
        "selected_latitude": float(ds.latitude[i]),
        "selected_longitude": float(ds.longitude[j]),
        "distance_km_approx": float(6371 * np.arccos(np.clip(cosine[i, j], -1, 1))),
        "extraction": "nearest grid-cell centre; not a monitoring station",
    }
    return out


def area_weights(ds):
    """Exact spherical strip areas (including half-sized polar caps), regular grid.

    Valid for cell-centre regional masks; not a polygon intersection weighting.
    """
    lat = ds.latitude
    v = lat.values
    step = (
        float(abs(v[1] - v[0]))
        if len(v) > 1
        else float(ds.attrs.get("horizontal_resolution_degrees", 0.75))
    )
    lower = np.maximum(-90, v - step / 2)
    upper = np.minimum(90, v + step / 2)
    return xr.DataArray(
        np.sin(np.deg2rad(upper)) - np.sin(np.deg2rad(lower)),
        dims="latitude",
        coords={"latitude": lat},
    )


def area_mean(da):
    result = da.weighted(area_weights(da)).mean(("latitude", "longitude"), keep_attrs=True)
    result.attrs = {
        **da.attrs,
        "spatial_aggregation": "spherical cell-area weighted mean; not population weighted",
    }
    return result


def get_timeseries(cfg, pollutant, lat, lon):
    from .processing import open_database

    with open_database(cfg) as ds:
        selected = extract_point(ds[[pollutant]], lat, lon)
        frame = selected[pollutant].to_dataframe().reset_index()
        frame.attrs = {**selected.attrs, "units": ds[pollutant].attrs.get("units")}
        return frame


def get_region_timeseries(cfg, pollutant, bbox):
    from .processing import open_database

    with open_database(cfg) as ds:
        selected = subset_bbox(ds[pollutant], *bbox)
        frame = area_mean(selected).to_dataframe().reset_index()
        frame.attrs = {
            **selected.attrs,
            "bbox": bbox,
            "aggregation": "area weighted over selected cell centres",
        }
        return frame


def save_table(frame, path):
    import json
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False, engine="fastparquet")
    elif path.suffix == ".csv":
        frame.to_csv(path, index=False)
    else:
        raise ValueError("Use CSV or Parquet")
    path.with_suffix(path.suffix + ".metadata.json").write_text(
        json.dumps(frame.attrs, indent=2, default=str)
    )
