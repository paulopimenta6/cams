import pytest
import xarray as xr

from cams_air_quality.units import mixing_ratio_to_concentration, moist_air_density, standardize


def a(x, unit):
    return xr.DataArray([x], dims="time", coords={"time": [0]}, attrs={"units": unit})


def test_pm_conversion(cfg):
    out = standardize(a(2e-8, "kg m**-3"), cfg["registry"]["pm25"])
    assert out.item() == pytest.approx(20)
    assert out.attrs["units"] == "ug m-3"


def test_gas_identity(cfg):
    out = standardize(a(1e-9, "kg kg**-1"), cfg["registry"]["co"])
    assert out.item() == 1e-9


def test_units_must_match(cfg):
    with pytest.raises(ValueError):
        standardize(a(1, "ug m-3"), cfg["registry"]["pm25"])


def test_density_and_gas():
    rho = moist_air_density(a(101325, "Pa"), a(300, "K"), a(0, "kg/kg"))
    assert rho.item() == pytest.approx(101325 / (287.05 * 300))
    out = mixing_ratio_to_concentration(a(1e-9, "kg/kg"), rho)
    assert out.item() == pytest.approx(rho.item())
    moist = moist_air_density(a(101325, "Pa"), a(300, "K"), a(0.02, "kg/kg"))
    assert moist.item() < rho.item()


def test_no_monthly_density_conversion():
    q = a(1e-9, "kg/kg")
    q.attrs["cell_methods"] = "time: mean"
    with pytest.raises(ValueError):
        mixing_ratio_to_concentration(q, a(1.2, "kg m-3"))


def test_alignment_and_negative():
    with pytest.raises(ValueError):
        mixing_ratio_to_concentration(a(1e-9, "kg/kg"), a(-1, "kg m-3"))
    with pytest.raises(ValueError):
        mixing_ratio_to_concentration(a(1e-9, "kg/kg"), a(1, "kg m-3").assign_coords(time=[1]))
    with pytest.raises(ValueError):
        moist_air_density(a(1000, "Pa"), a(-1, "K"), a(0, "kg/kg"))
