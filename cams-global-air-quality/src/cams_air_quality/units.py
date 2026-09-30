"""Conversions are explicit; never derive monthly mean(q*rho) from mean(q)*mean(rho)."""

import numpy as np
import xarray as xr


def canonical(unit):
    compact = unit.replace(" ", "").replace("**", "^").replace("µ", "u").replace("μ", "u")
    aliases = {
        "kgm^-3": "kg m-3",
        "kgm-3": "kg m-3",
        "kg/m^3": "kg m-3",
        "kg/m3": "kg m-3",
        "kgkg^-1": "kg kg-1",
        "kgkg-1": "kg kg-1",
        "kg/kg": "kg kg-1",
        "ugm-3": "ug m-3",
        "ug/m3": "ug m-3",
        "ugm^-3": "ug m-3",
        "Pa": "Pa",
        "K": "K",
    }
    return aliases.get(compact, unit)


def standardize(da, spec):
    original = da.attrs.get("units", "")
    if canonical(original) != spec["original_units"]:
        raise ValueError(f"Unexpected units {original!r}; expected {spec['original_units']}")
    if spec["conversion"] == "mass_concentration":
        if (spec["original_units"], spec["desired_units"]) != ("kg m-3", "ug m-3"):
            raise ValueError("Unsupported mass concentration conversion")
        out = da * 1e9
        equation = "C[ug m-3] = C[kg m-3] * 1e9"
    elif spec["conversion"] == "identity" and spec["desired_units"] == spec["original_units"]:
        out = da.copy(deep=False)
        equation = "identity (no conversion)"
    else:
        raise ValueError("Unknown conversion; extend registry and tests explicitly")
    out.attrs = {
        **da.attrs,
        "original_units": original,
        "units": spec["desired_units"],
        "conversion_equation": equation,
        "assumptions": spec["assumptions"],
        "cams_variable": spec["cams_variable"],
        "long_name": spec["long_name"],
    }
    return out


def mixing_ratio_to_concentration(q, density):
    """Instantaneous q [kg/kg moist air] * collocated rho [kg/m3] * 1e9.

    Inputs must have identical coordinates, dimensions and sampling. Does not
    support monthly inputs: monthly averaging must occur AFTER this multiplication.
    """
    if canonical(q.attrs.get("units", "")) != "kg kg-1":
        raise ValueError("q must carry kg kg-1 units")
    if canonical(density.attrs.get("units", "")) != "kg m-3":
        raise ValueError("density must carry kg m-3 units")
    if "mean" in q.attrs.get("cell_methods", ""):
        raise ValueError("Cannot reconstruct mean(q*rho) from monthly mean inputs")
    if q.dims != density.dims:
        raise ValueError("Density and mixing ratio must have identical dimensions")
    q, density = xr.align(q, density, join="exact")
    if bool(((density <= 0) | ~np.isfinite(density)).any().compute()):
        raise ValueError("Density must be finite and positive")
    out = q * density * 1e9
    out.attrs = {
        **q.attrs,
        "units": "ug m-3",
        "original_units": "kg kg-1",
        "conversion_equation": "C = q * rho_air * 1e9",
        "assumptions": "instantaneous collocated fields; same moist-air mass basis",
    }
    return out


def moist_air_density(pressure, temperature, specific_humidity):
    """Ideal mixture: rho = p/[Rd*T*(1+(Rv/Rd-1)*qv)].

    p in Pa, T in K, qv in kg/kg moist air; same model level/time/grid.
    Neglects condensate loading, all inputs must be collocated, not 2m T with ML60 p.
    """
    for v, u in [(pressure, "Pa"), (temperature, "K"), (specific_humidity, "kg kg-1")]:
        if canonical(v.attrs.get("units", "")) != u:
            raise ValueError(f"Expected {u}")
    if not (pressure.dims == temperature.dims == specific_humidity.dims):
        raise ValueError("Thermodynamic fields must be collocated")
    p, t, q = xr.align(pressure, temperature, specific_humidity, join="exact")
    invalid = (p <= 0) | (t <= 0) | (q < 0) | (q >= 1)
    invalid |= ~np.isfinite(p) | ~np.isfinite(t) | ~np.isfinite(q)
    if bool(invalid.any().compute()):
        raise ValueError("Nonphysical thermodynamic inputs")
    rho = p / (287.05 * t * (1 + (461.5 / 287.05 - 1) * q))
    rho.attrs = {
        "units": "kg m-3",
        "long_name": "Ideal moist-air density",
        "assumptions": "ideal gas; condensate loading neglected",
    }
    return rho
