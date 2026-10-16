import pytest

from telemetry.geo import haversine_m


def test_same_point_is_zero():
    assert haversine_m(-24.0, 31.5, -24.0, 31.5) == 0.0


def test_one_degree_of_latitude():
    assert haversine_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(111_195, rel=1e-4)


def test_symmetric():
    there = haversine_m(-24.0, 31.5, -25.0, 32.0)
    back = haversine_m(-25.0, 32.0, -24.0, 31.5)
    assert there == pytest.approx(back)
