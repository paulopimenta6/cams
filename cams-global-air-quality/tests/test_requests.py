import copy

import pandas as pd
import pytest

from cams_air_quality.catalog import CatalogError, available_months
from cams_air_quality.requests import build_batch, estimate, plan_batches


def test_monthly_current_schema(cfg, snap):
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    assert b.api_request == {
        "variable": ["particulate_matter_2.5um"],
        "data_format": "grib",
        "year": ["2003"],
        "month": ["01"],
        "product_type": ["monthly_mean"],
        "time": ["00:00"],
    }
    assert "model_level" not in b.api_request
    assert "/2003/01/" in b.filepath


@pytest.mark.parametrize("v", ["co", "no2", "so2", "o3"])
def test_model_60(cfg, snap, v):
    b = build_batch(cfg, snap, v, "2003-01", "monthly")
    assert b.api_request["model_level"] == ["60"]
    assert "pressure_level" not in b.api_request


def test_leap_month(cfg, subdaily):
    b = build_batch(cfg, subdaily, "pm25", "2004-02", "subdaily")
    assert b.api_request["date"] == "2004-02-01/2004-02-29"
    assert len(b.api_request["time"]) == 8
    assert estimate(cfg, [b])["fields"] == 29 * 8


def test_no_guessed_last_year(cfg, snap):
    s = copy.deepcopy(snap)
    s["collection"]["extent"]["temporal"]["interval"][0][1] = "2026-02-28T00:00:00Z"
    # Separate allowed row: prevents Cartesian-product bug that invents March-Dec 2026.
    rows = copy.deepcopy(s["constraints"])
    for r in rows:
        r.update(year=["2026"], month=["01", "02"])
    s["constraints"] += rows
    periods = available_months(s, cfg["registry"]["pm25"], "monthly")
    assert periods[-1] == pd.Period("2026-02")
    assert pd.Period("2026-03") not in periods


def test_partial_subdaily_month_excluded(cfg, subdaily):
    s = copy.deepcopy(subdaily)
    s["collection"]["extent"]["temporal"]["interval"][0][1] = "2026-02-15T00:00:00Z"
    for r in s["constraints"]:
        r["date"] = ["2003-01-01/2026-02-15"]
    assert available_months(s, cfg["registry"]["pm25"], "subdaily")[-1] == pd.Period("2026-01")


def test_unknown_variable_rejected(cfg, snap):
    cfg["registry"]["pm25"]["cams_variable"] = "imaginary"
    with pytest.raises(CatalogError):
        build_batch(cfg, snap, "pm25", "2003-01", "monthly")


def test_period_limits(cfg, snap):
    with pytest.raises(ValueError):
        plan_batches(cfg, snap, "monthly", "2020-02", "2020-01")
    with pytest.raises(ValueError):
        plan_batches(cfg, snap, "monthly", end="2099-12")


def test_request_identity(cfg, snap):
    a = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    b = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    assert a.key == b.key and a.filepath == b.filepath
    cfg["area"] = [10, -10, -10, 10]
    c = build_batch(cfg, snap, "pm25", "2003-01", "monthly")
    assert c.key != a.key and c.filepath != a.filepath


def test_incomplete_time_constraints_rejected(cfg, subdaily):
    s = copy.deepcopy(subdaily)
    for row in s["constraints"]:
        row["time"] = ["00:00"]
    with pytest.raises(CatalogError):
        available_months(s, cfg["registry"]["pm25"], "subdaily")
