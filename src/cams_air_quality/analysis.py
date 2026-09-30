"""Real-data exploratory report; never fabricates CAMS observations."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .extraction import area_mean, extract_point, save_table
from .maps import plot_map
from .processing import open_database
from .statistics import annual_mean, anomalies, check_monthly, climatology


def explore(cfg, output, baseline_start, baseline_end):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with open_database(cfg) as ds:
        for variable in ("pm25", "no2", "o3"):
            a = ds[variable]
            check_monthly(a)
            global_series = area_mean(a)
            frame = global_series.to_dataframe().reset_index()
            frame.attrs = {**a.attrs, "spatial_weighting": "spherical area", "source": "EAC4"}
            save_table(frame, out / f"{variable}_global.csv")
            cl = climatology(global_series, baseline_start, baseline_end)
            cl.to_netcdf(out / f"{variable}_climatology.nc", engine=cfg["netcdf_engine"])
            fig, ax = plt.subplots(figsize=(11, 4))
            global_series.plot(ax=ax)
            ax.set_title(f"{variable}: global area-weighted monthly mean")
            fig.savefig(out / f"{variable}_timeseries.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            fig, ax = plt.subplots(figsize=(8, 4))
            cl.plot(ax=ax, marker="o")
            ax.set_title(f"{variable}: climatology {baseline_start} to {baseline_end}")
            fig.savefig(out / f"{variable}_seasonality.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            # Time-weighted period mean; explicit baseline and calendar duration.
            weights = a.time.dt.days_in_month
            mean_map = a.weighted(weights).mean("time", keep_attrs=True)
            plot_map(
                mean_map,
                out / f"{variable}_mean_map.png",
                title=f"{variable}: period mean (calendar-day weighted)",
            )
            if variable == "pm25":
                annual = annual_mean(anomalies(global_series, baseline_start, baseline_end))
                f = annual.to_dataframe(name="pm25_anomaly").reset_index()
                f.attrs = annual.attrs
                save_table(f, out / "pm25_annual_anomalies.csv")
                fig, ax = plt.subplots(figsize=(11, 4))
                annual.plot(ax=ax)
                ax.axhline(0, color="black", lw=0.5)
                fig.savefig(out / "pm25_annual_anomalies.png", dpi=150, bbox_inches="tight")
                plt.close(fig)
        sp = extract_point(ds[[v for v in cfg["pollutants"] if v in ds]], -23.5505, -46.6333)
        f = sp.to_dataframe().reset_index()
        f.attrs = {**sp.attrs, "units": {v: ds[v].attrs.get("units") for v in cfg["pollutants"]}}
        save_table(f, out / "sao_paulo_nearest_cell.parquet")
        report = {
            "source": "EAC4",
            "first": str(ds.time.values.min()),
            "last": str(ds.time.values.max()),
            "baseline": [baseline_start, baseline_end],
            "nearest_cell": sp.attrs,
            "caveats": [
                "Not station observations",
                "Global mean is not population exposure",
                "Gases retained in kg/kg",
                "Exploratory descriptive analysis; no causal inference",
            ],
        }
        (out / "analysis.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "README.md").write_text(
        "# Análise exploratória EAC4\n\nProdutos calculados apenas dos dados reais presentes no índice Zarr. Consulte analysis.json e metadados dos CSV/Parquet.\n"
    )
