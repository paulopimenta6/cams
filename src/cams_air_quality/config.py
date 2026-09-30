from pathlib import Path

import yaml


def load_config(path="config/config.yaml"):
    path = Path(path).resolve()
    with path.open() as f:
        cfg = yaml.safe_load(f)
    cfg["root"] = str((path.parent / cfg["root"]).resolve())
    for key in ("data_dir", "metadata_dir", "log_dir"):
        cfg[key] = str((Path(cfg["root"]) / cfg[key]).resolve())
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)
    with (path.parent / cfg["pollutants_file"]).open() as f:
        cfg["registry"] = yaml.safe_load(f)["pollutants"]
    if not 1 <= cfg["workers"] <= 4:
        raise ValueError("workers must be 1..4 (ADS conservative concurrency)")
    if cfg.get("netcdf_engine", "h5netcdf") not in ("h5netcdf", "netcdf4"):
        raise ValueError("Unsupported NetCDF backend")
    if cfg["data_format"] not in ("grib", "netcdf_zip"):
        raise ValueError("Use a data_format exposed by the current ADS form")
    if not set(cfg["pollutants"]) <= cfg["registry"].keys():
        raise ValueError("Unknown pollutant in configuration")
    if cfg.get("area") is not None:
        from .extraction import check_bbox

        check_bbox(cfg["area"])
    return cfg
