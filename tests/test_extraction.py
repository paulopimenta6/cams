import pytest
from conftest import dataset

from cams_air_quality.extraction import area_mean, area_weights, extract_point, subset_bbox


def test_negative_longitude():
    d = dataset()
    p = extract_point(d, 0, -90)
    assert p.longitude.item() == 270
    assert p.attrs["distance_km_approx"] == pytest.approx(0)


def test_antimeridian():
    d = dataset()
    out = subset_bbox(d, 90, 170, -90, -170)
    assert out.longitude.values.tolist() == [180]


def test_full_globe_bbox():
    assert subset_bbox(dataset(), 90, -180, -90, 180).sizes["longitude"] == 4


def test_latitude_order():
    d = dataset()
    a = subset_bbox(d, 10, -180, -10, 180)
    b = subset_bbox(d.sortby("latitude"), 10, -180, -10, 180)
    assert a.latitude.values.tolist() == b.latitude.values.tolist() == [0.0]


def test_area_mean_and_poles():
    d = dataset().pm2p5
    assert float(area_mean(d)[0]) == pytest.approx(2e-8)
    w = area_weights(d)
    assert float(w.sum()) == pytest.approx(2)
    assert bool((w > 0).all())


def test_invalid_bbox():
    with pytest.raises(ValueError):
        subset_bbox(dataset(), -10, 0, 10, 20)
    with pytest.raises(ValueError):
        subset_bbox(dataset(), 10, 10, 0, 20)
