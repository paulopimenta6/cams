import numpy as np
import pandas as pd
import xarray as xr

from .extraction import area_mean, subset_bbox


def check_monthly(da):
    t = pd.DatetimeIndex(da.time.values)
    if (
        t.has_duplicates
        or not t.is_monotonic_increasing
        or not t.equals(pd.date_range(t.min(), t.max(), freq="MS"))
    ):
        raise ValueError("Expected contiguous monthly means with month-start timestamps")


def annual_mean(da, require_complete=True):
    check_monthly(da)
    days = da.time.dt.days_in_month
    out = (da * days).resample(time="YS").sum(skipna=False) / days.resample(time="YS").sum()
    count = xr.ones_like(da.time, dtype=int).resample(time="YS").sum()
    if require_complete:
        out = out.where(count == 12, drop=True)
    out.attrs = {
        **da.attrs,
        "cell_methods": "time: mean (weighted by calendar days; complete years only)",
    }
    return out


def climatology(da, start, end):
    check_monthly(da)
    first, last = pd.Period(start, "M"), pd.Period(end, "M")
    actual = pd.DatetimeIndex(da.time.values).to_period("M")
    if first > last or first < actual.min() or last > actual.max():
        raise ValueError("Requested baseline is not fully available")
    baseline = da.sel(time=slice(str(first), str(last)))
    if baseline.sizes["time"] < 12 or len(set(baseline.time.dt.month.values)) != 12:
        raise ValueError("Reference period must cover every calendar month")
    cl = baseline.groupby("time.month").mean("time", skipna=False, keep_attrs=True)
    cl.attrs.update(
        baseline_start=start,
        baseline_end=end,
        climatology_method="equal weights across years for each calendar month",
    )
    return cl


def anomalies(da, start, end):
    cl = climatology(da, start, end)
    out = da.groupby("time.month") - cl
    out.attrs = {**da.attrs, "baseline_start": start, "baseline_end": end}
    return out


def linear_trend(da):
    """Descriptive OLS slope per tropical year. No iid significance/p-values claimed."""
    check_monthly(da)
    years = (da.time.values - da.time.values[0]) / np.timedelta64(1, "D") / 365.2425
    a = da.assign_coords(time=years)
    out = a.polyfit("time", deg=1, skipna=False).polyfit_coefficients.sel(degree=1, drop=True)
    out.attrs = {
        "units": da.attrs.get("units", "") + " year-1",
        "method": "descriptive OLS",
        "limitation": "seasonality, serial correlation, coverage and observational-system changes not adjusted; not causal inference",
    }
    return out


def summaries(da, bbox=None, quantiles=(0.05, 0.5, 0.95)):
    if bbox is not None:
        da = subset_bbox(da, *bbox)
    # Only the small time axis is gathered for exact percentiles; spatial chunks retained.
    quant = da.chunk({"time": -1}).quantile(quantiles, dim="time", skipna=False, keep_attrs=True)
    return {
        "global_monthly": area_mean(da),
        "global_annual": annual_mean(area_mean(da)),
        "zonal_mean": da.mean("longitude", keep_attrs=True),
        "trend": linear_trend(da),
        "percentiles": quant,
        "minimum": da.min("time", keep_attrs=True),
        "maximum": da.max("time", keep_attrs=True),
        "std": da.std("time", ddof=0, keep_attrs=True),
    }
