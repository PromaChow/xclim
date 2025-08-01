from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from xclim.core.options import set_options
from xclim.core.units import convert_units_to
from xclim.core.utils import uses_dask
from xclim.indices import helpers
from xclim.testing.helpers import assert_lazy


@pytest.mark.parametrize("method,rtol", [("spencer", 5e3), ("simple", 1e2)])
def test_solar_declinaton(method, rtol):
    # Expected values from https://gml.noaa.gov/grad/solcalc/azel.html
    times = xr.DataArray(
        pd.to_datetime(["1793-01-21T10:22:00", "1969-07-20T20:17:40", "2022-05-20T16:55:48"]),
        dims=("time",),
    )
    exp = [-19.83, 20.64, 20.00]
    np.testing.assert_allclose(
        helpers.solar_declination(times, method=method),
        np.deg2rad(exp),
        atol=rtol * 2 * np.deg2rad(23.44),  # % of the possible range
    )


@pytest.mark.parametrize("method", ["spencer", "simple"])
def test_extraterrestrial_radiation(method):
    # Expected values from https://www.engr.scu.edu/~emaurer/tools/calc_solar_cgi.pl
    # This source is not authoritative, thus the large rtol
    times = xr.DataArray(
        xr.date_range("1900-01-01", "1900-01-03", freq="D"),
        dims=("time",),
        name="time",
    )
    lat = xr.DataArray(
        [48.8656, 29.5519, -54],
        dims=("time",),
        coords={"time": times},
        attrs={"units": "degree_north"},
    )
    exp = [99.06, 239.98, 520.01]
    np.testing.assert_allclose(
        convert_units_to(helpers.extraterrestrial_solar_radiation(times, lat, method=method), "W m-2"),
        exp,
        rtol=3e-2,
    )


class TestDayLength:
    @staticmethod
    def data_setup(lats: np.ndarray, start_date: str = "1992-12-01", end_date: str = "1994-01-01"):
        time_data = xr.date_range(start_date, end_date, freq="D", calendar="standard")
        data = xr.DataArray(
            np.ones((time_data.size, len(lats))),
            dims=("time", "lat"),
            coords={"time": time_data, "lat": lats},
        )
        data.lat.attrs["units"] = "degree_north"
        return data

    @pytest.mark.parametrize("method, infill", [("spencer", False), ("spencer", True), ("simple", False)])
    def test_day_lengths(self, method, infill):
        data = self.data_setup(lats=np.array([-60, -45, -30, 0, 30, 45, 60, 80]))
        dl = helpers.day_lengths(dates=data.time, lat=data.lat, method=method, infill_polar_days=infill)

        events = dict(
            solstice=[
                ["1992-12-21", [18.49, 15.43, 13.93, 12.0, 10.07, 8.57, 5.51, 0.0 if infill else np.nan]],
                ["1993-06-21", [5.51, 8.57, 10.07, 12.0, 13.93, 15.43, 18.49, 24.0 if infill else np.nan]],
                ["1993-12-21", [18.49, 15.43, 13.93, 12.0, 10.07, 8.57, 5.51, 0.0 if infill else np.nan]],
            ],
            equinox=[
                ["1993-03-20", [12] * 8]
            ],  # True equinox on 1993-03-20 at 14:41 GMT. Some relative tolerance is needed.
        )

        for event, evaluations in events.items():
            for e in evaluations:
                if event == "solstice":
                    np.testing.assert_array_almost_equal(dl.sel(time=e[0]).transpose(), np.array(e[1]), 2)
                elif event == "equinox":
                    np.testing.assert_allclose(dl.sel(time=e[0]).transpose(), np.array(e[1]), rtol=2e-1)

    @pytest.mark.parametrize(
        "method, cap_value, results",
        [
            ("huglin", np.nan, [np.nan, 1.04, 1.03, 1.0, 1.03, 1.04, np.nan, np.nan]),
            ("interpolated", np.nan, [np.nan, 1.03, 1.02, 1.0, 1.02, 1.03, np.nan, np.nan]),
            ("interpolated", 1.06, [1.06, 1.03, 1.02, 1.0, 1.02, 1.03, 1.06, 1.06]),
        ],
    )
    def test_huglin_day_length_latitude_coefficient(self, method, cap_value, results):
        data = self.data_setup(lats=np.array([-60, -45, -43.5, 0, 43.5, 45, 60, 80]))
        k = helpers.huglin_day_length_latitude_coefficient(lat=data.lat, method=method, cap_value=cap_value)

        np.testing.assert_array_almost_equal(k, np.array(results), decimal=2)

    @pytest.mark.parametrize(
        "method, start_date, end_date, freq, floor, results",
        [
            (
                "gladstones",
                "04-01",
                "11-01",
                "YS",
                False,
                [0.75, 0.86, 0.91, 0.95, 0.97, 1.0, 1.02, 1.04, 1.06, 1.09, 1.12, 1.18, 1.29],
            ),
            (
                "gladstones",
                "04-01",
                "11-01",
                "YS-JAN",
                True,
                [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.02, 1.04, 1.06, 1.09, 1.12, 1.18, 1.29],
            ),
            (
                "gladstones",
                "10-01",
                "04-01",
                "YS-JUL",
                True,
                [1.18, 1.06, 1.01, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            ),
            (
                "jones",
                "04-01",
                "11-01",
                "YS-JAN",
                False,
                [0.79, 0.89, 0.94, 0.97, 1.0, 1.02, 1.04, 1.05, 1.07, 1.1, 1.13, 1.18, 1.28],
            ),
            (
                "jones",
                "04-01",
                "11-01",
                "YS",
                True,
                [1.0, 1.0, 1.0, 1.0, 1.0, 1.02, 1.04, 1.05, 1.07, 1.1, 1.13, 1.18, 1.28],
            ),
            (
                "jones",
                "10-01",
                "04-01",
                "YS-JUL",
                False,
                [1.18, 1.07, 1.02, 0.99, 0.97, 0.95, 0.93, 0.91, 0.89, 0.86, 0.83, 0.78, 0.67],
            ),
            # Incomplete growing season; Raise a ValueError
            (
                "jones",
                "04-01",
                "11-01",
                "YS-JUL",
                False,
                None,
            ),
        ],
    )
    def test_jones_day_length_latitude_coefficient(self, method, start_date, end_date, freq, floor, results):
        if freq == "YS-JUL":
            setup_dates = {"start_date": "1992-08-01", "end_date": "1993-06-01"}
        else:
            setup_dates = {}

        data = self.data_setup(lats=np.linspace(-65, 65, 13, endpoint=True), **setup_dates)
        if results is None:
            with pytest.raises(ValueError):
                helpers.jones_day_length_latitude_coefficient(
                    dates=data.time,
                    lat=data.lat,
                    start_date=start_date,
                    end_date=end_date,
                    freq=freq,
                    method=method,
                    floor=floor,
                )
        else:
            k = helpers.jones_day_length_latitude_coefficient(
                dates=data.time,
                lat=data.lat,
                start_date=start_date,
                end_date=end_date,
                freq=freq,
                method=method,
                floor=floor,
            )
            np.testing.assert_array_almost_equal(k.transpose()[0], results, 2)

    @pytest.mark.parametrize("constrain", [None, "20 degree_north"])
    def test_gladstones_day_length(self, constrain):
        data = self.data_setup(lats=np.linspace(-65, 65, 13, endpoint=True))
        k = helpers.gladstones_day_length_latitude_coefficient(dates=data.time, lat=data.lat, constrain=constrain)

        events = dict(
            solstice=[
                ["1992-12-21", [1.42, 1.14, 1.03, 0.95, 0.9, 0.85, 1.31, 1.24, 1.17, 1.08, 0.96, 0.77, 0.32]],
                ["1993-06-21", [0.31, 0.77, 0.96, 1.08, 1.17, 1.24, 0.81, 0.85, 0.9, 0.95, 1.03, 1.14, 1.42]],
                ["1993-12-21", [1.42, 1.14, 1.03, 0.95, 0.9, 0.85, 1.31, 1.24, 1.17, 1.08, 0.96, 0.77, 0.32]],
            ],
            equinox=[
                ["1993-03-20", [1.0] * 13]
            ],  # True equinox on 1993-03-20 at 14:41 GMT. Some relative tolerance is needed.
        )

        if constrain == "20 degree_north":
            for entry in events["solstice"]:
                entry[1][5:8] = [1.0] * 3

        for event, evaluations in events.items():
            for e in evaluations:
                if event == "solstice":
                    np.testing.assert_array_almost_equal(k.sel(time=e[0]).transpose(), np.array(e[1]), 2)
                elif event == "equinox":
                    np.testing.assert_allclose(k.sel(time=e[0]).transpose(), np.array(e[1]), rtol=2e-1)


@pytest.mark.parametrize("calendar", ["standard", "noleap"])
def test_cosine_of_solar_zenith_angle(calendar):
    time = xr.date_range("1900-01-01T00:30", "1900-01-03", freq="h", calendar=calendar)
    time = xr.DataArray(time, dims=("time",), coords={"time": time}, name="time")
    lat = xr.DataArray([0, 45, 70], dims=("site",), name="lat", attrs={"units": "degree_north"})
    lon = xr.DataArray([-40, 0, 80], dims=("site",), name="lon", attrs={"units": "degree_east"})
    dec = helpers.solar_declination(time)

    czda = helpers.cosine_of_solar_zenith_angle(time, dec, lat, lon, stat="average", sunlit=True)
    # Data Generated with PyWGBT
    # raw = coszda(
    #     (time + pd.Timedelta('30 m')).data,
    #     convert_units_to(lat, 'rad').data[np.newaxis, :],
    #     convert_units_to(lon, 'rad').data[np.newaxis, :],
    #     1
    # )
    # exp_cza = xr.DataArray(
    #               raw,
    #               dims=('time', 'd', 'site'),
    #               coords={'lat': lat, 'lon': lon, 'time': time}
    #           ).squeeze('d')
    exp_czda = np.array(
        [
            [0.0, 0.0610457, 0.0],
            [0.09999178, 0.18221077, 0.0],
            [0.31387116, 0.285383, 0.0],
            [0.52638271, 0.35026199, 0.0],
            [0.70303168, 0.37242693, 0.0],
        ]
    )
    np.testing.assert_allclose(czda[7:12, :], exp_czda, rtol=1e-3)

    # Same code as above, but with function "cosza".
    cza = helpers.cosine_of_solar_zenith_angle(time, dec, lat, lon, stat="average", sunlit=False)
    exp_cza = np.array(
        [
            [-0.83153798, -0.90358335, -0.34065474],
            [-0.90358299, -0.83874813, -0.26062708],
            [-0.91405234, -0.73561867, -0.18790995],
            [-0.86222963, -0.60121893, -0.12745608],
        ]
    )
    np.testing.assert_allclose(cza[:4, :], exp_cza, rtol=1e-3)


@pytest.mark.parametrize(["in_chunks", "exp_chunks"], [(60, 6 * (2,)), (30, 12 * (1,)), (-1, (12,))])
def test_resample_map(tas_series, in_chunks, exp_chunks):
    pytest.importorskip("flox")
    tas = tas_series(365 * [1]).chunk(time=in_chunks)
    with assert_lazy:
        out = helpers.resample_map(tas, "time", "MS", lambda da: da.mean("time"), map_blocks=True)
    assert out.chunks[0] == exp_chunks
    out.load()  # Trigger compute to see if it actually works


def test_resample_map_dataset(tas_series, pr_series):
    pytest.importorskip("flox")
    tas = tas_series(3 * 365 * [1], start="2000-01-01").chunk(time=365)
    pr = pr_series(3 * 365 * [1], start="2000-01-01").chunk(time=365)
    ds = xr.Dataset({"pr": pr, "tas": tas})
    with set_options(resample_map_blocks=True):
        with assert_lazy:
            out = helpers.resample_map(
                ds,
                "time",
                "YS",
                lambda da: da.mean("time"),
            )
    assert out.chunks["time"] == (1, 1, 1)
    out.load()


def test_resample_map_passthrough(tas_series):
    tas = tas_series(365 * [1])
    with assert_lazy:
        out = helpers.resample_map(tas, "time", "MS", lambda da: da.mean("time"))
    assert not uses_dask(out)


@pytest.mark.parametrize("calendar", [None, "standard"])
def test_make_hourly_temperature(tasmax_series, tasmin_series, calendar):
    tasmax = tasmax_series(np.array([20]), units="degC", calendar=calendar)
    tasmin = tasmin_series(np.array([0]), units="degC", calendar=calendar).expand_dims(lat=[0])

    tasmin.lat.attrs["units"] = "degree_north"
    tas_hourly = helpers.make_hourly_temperature(tasmax, tasmin)
    assert tas_hourly.attrs["units"] == "degC"
    assert tas_hourly.time.size == 24
    expected = np.array(
        [
            0.0,
            3.90180644,
            7.65366865,
            11.11140466,
            14.14213562,
            16.62939225,
            18.47759065,
            19.61570561,
            20.0,
            19.61570561,
            18.47759065,
            16.62939225,
            14.14213562,
            10.32039099,
            8.0848137,
            6.49864636,
            5.26831939,
            4.26306907,
            3.41314202,
            2.67690173,
            2.02749177,
            1.44657476,
            0.92107141,
            0.44132444,
        ]
    )
    np.testing.assert_allclose(tas_hourly.isel(lat=0).values, expected)
