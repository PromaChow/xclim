"""
Indices Helper Functions Submodule
==================================

Functions that encapsulate logic and can be shared by many indices,
but are not particularly index-like themselves (those should go in the :py:mod:`xclim.indices.generic` module).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from inspect import stack
from typing import Any, Literal, cast

import cf_xarray  # noqa: F401, pylint: disable=unused-import
import cftime
import numba as nb
import numpy as np
import xarray as xr
from xarray import CFTimeIndex

try:
    from xarray.coding.calendar_ops import _datetime_to_decimal_year
except ImportError:
    XR2409 = True
else:
    XR2409 = False

try:
    from flox.xarray import rechunk_for_blockwise

    flox_err = None
except ImportError:
    rechunk_for_blockwise = None

from xclim.core import DayOfYearStr, Quantified
from xclim.core.calendar import ensure_cftime_array, get_calendar, parse_offset, select_time
from xclim.core.options import MAP_BLOCKS, OPTIONS
from xclim.core.units import convert_units_to
from xclim.core.utils import _chunk_like, uses_dask

__all__ = [
    "cosine_of_solar_zenith_angle",
    "day_angle",
    "day_lengths",
    "distance_from_sun",
    "eccentricity_correction_factor",
    "extraterrestrial_solar_radiation",
    "gladstones_day_length_latitude_coefficient",
    "huglin_day_length_latitude_coefficient",
    "jones_day_length_latitude_coefficient",
    "make_hourly_temperature",
    "resample_map",
    "solar_declination",
    "time_correction_for_solar_angle",
    "wind_speed_height_conversion",
]


def _wrap_radians(da):
    with xr.set_options(keep_attrs=True):
        return ((da + np.pi) % (2 * np.pi)) - np.pi


def distance_from_sun(dates: xr.DataArray) -> xr.DataArray:
    """
    Sun-earth distance.

    The distance from sun to earth in astronomical units.

    Parameters
    ----------
    dates : xr.DataArray
        Series of dates and time of days.

    Returns
    -------
    xr.DataArray, [astronomical units]
        Sun-earth distance.

    References
    ----------
    # TODO: Find a way to reference this
    U.S. Naval Observatory:Astronomical Almanac. Washington, D.C.: U.S. Government Printing Office (1985).
    """
    cal = get_calendar(dates)
    if cal == "default":
        cal = "standard"
    days_since = cftime.date2num(ensure_cftime_array(dates), "days since 2000-01-01 12:00:00", calendar=cal)
    g = ((357.528 + 0.9856003 * days_since) % 360) * np.pi / 180
    sun_earth = 1.00014 - 0.01671 * np.cos(g) - 0.00014 * np.cos(2.0 * g)
    return xr.DataArray(sun_earth, coords=dates.coords, dims=dates.dims)


def day_angle(time: xr.DataArray) -> xr.DataArray:
    """
    Day of year as an angle.

    Assuming the Earth makes a full circle in a year, this is the angle covered from
    the beginning of the year up to that timestep. Also called the "julian day fraction".

    Parameters
    ----------
    time : xr.DataArray
        Time coordinate.

    Returns
    -------
    xr.DataArray, [rad]
        Day angle.
    """
    if XR2409:
        decimal_year = time.dt.decimal_year
    else:
        decimal_year = _datetime_to_decimal_year(times=time, calendar=time.dt.calendar)
    return ((decimal_year % 1) * 2 * np.pi).assign_attrs(units="rad")


def solar_declination(time: xr.DataArray, method="spencer") -> xr.DataArray:
    """
    Solar declination.

    The angle between the sun rays and the earth's equator, in radians, as approximated
    by :cite:t:`spencer_fourier_1971` or assuming the orbit is a circle.

    Parameters
    ----------
    time : xr.DataArray
        Time coordinate.
    method : {'spencer', 'simple'}
        Which approximation to use. The default ("spencer") uses the first seven (7) terms of the
        Fourier series representing the observed declination, while "simple" assumes the orbit is
        a circle with a fixed obliquity and that the solstice/equinox happen at fixed angles on
        the orbit (the exact calendar date changes for leap years).

    Returns
    -------
    xr.DataArray, [rad]
        Solar declination angle.

    References
    ----------
    :cite:cts:`spencer_fourier_1971`
    """
    # julian day fraction
    da = convert_units_to(day_angle(time), "rad")
    if method == "simple":
        # This assumes the orbit is a perfect circle, the obliquity is 0.4091 rad (23.43°)
        # and the equinox is on the March 21st 17:20 UTC (March 20th 23:14 UTC on leap years)
        sd = 0.4091 * np.sin(da - 1.39)
    elif method == "spencer":
        sd = (
            0.006918
            - 0.399912 * np.cos(da)
            + 0.070257 * np.sin(da)
            - 0.006758 * np.cos(2 * da)
            + 0.000907 * np.sin(2 * da)
            - 0.002697 * np.cos(3 * da)
            + 0.001480 * np.sin(3 * da)
        )
    else:
        raise NotImplementedError("Method must be one of 'simple' or 'spencer'.")
    return _wrap_radians(sd).assign_attrs(units="rad").rename("declination")


def time_correction_for_solar_angle(time: xr.DataArray) -> xr.DataArray:
    """
    Time correction for solar angle.

    Every 1° of angular rotation on earth is equal to 4 minutes of time.
    The time correction is needed to adjust local watch time to solar time.

    Parameters
    ----------
    time : xr.DataArray
        Time coordinate.

    Returns
    -------
    xr.DataArray, [rad]
        Time correction of solar angle.

    References
    ----------
    :cite:cts:`di_napoli_mean_2020`
    """
    da = convert_units_to(day_angle(time), "rad")
    tc = (
        0.004297 + 0.107029 * np.cos(da) - 1.837877 * np.sin(da) - 0.837378 * np.cos(2 * da) - 2.340475 * np.sin(2 * da)
    )
    tc = tc.assign_attrs(units="degrees")
    return _wrap_radians(convert_units_to(tc, "rad"))


def eccentricity_correction_factor(
    time: xr.DataArray, method: Literal["spencer", "simple"] = "spencer"
) -> xr.DataArray:
    """
    Eccentricity correction factor of the Earth's orbit.

    The squared ratio of the mean distance Earth-Sun to the distance at a specific moment.
    As approximated by :cite:t:`spencer_fourier_1971`.

    Parameters
    ----------
    time : xr.DataArray
        Time coordinate.
    method : {'spencer', 'simple'}
        Which approximation to use.
        The default ("spencer") uses the first five (5) terms of the fourier series of the eccentricity.
        The "simple" method approximates with only the first two (2).

    Returns
    -------
    xr.DataArray, [dimensionless]
        Eccentricity correction factor.

    References
    ----------
    :cite:cts:`spencer_fourier_1971,perrin_estimation_1975`
    """
    # julian day fraction
    da = convert_units_to(day_angle(time), "rad")
    if method == "simple":
        # It is quite used, I think the source is (not available online):
        # Perrin de Brichambaut, C. (1975).
        # Estimation des ressources énergétiques solaires en France. Ed. Européennes thermique et industrie.
        return cast(xr.DataArray, 1 + 0.033 * np.cos(da))
    if method == "spencer":
        return cast(
            xr.DataArray,
            1.0001100
            + 0.034221 * np.cos(da)
            + 0.001280 * np.sin(da)
            + 0.000719 * np.cos(2 * da)
            + 0.000077 * np.sin(2 * da),
        )
    raise NotImplementedError("Method must be one of 'simple' or 'spencer'.")


def cosine_of_solar_zenith_angle(
    time: xr.DataArray,
    declination: xr.DataArray,
    lat: Quantified | xr.DataTree,
    lon: Quantified = "0 °",
    time_correction: xr.DataArray | None = None,
    stat: Literal["average", "integral", "instant"] = "average",
    sunlit: bool = False,
    chunks: dict[str, int] | None = None,
) -> xr.DataArray:
    """
    Cosine of the solar zenith angle.

    The solar zenith angle is the angle between a vertical line (perpendicular to the ground) and the sun rays.
    This function computes a statistic of its cosine : its instantaneous value,
    the integral from sunrise to sunset or the average over the same period or over a subdaily interval.
    Based on :cite:t:`kalogirou_chapter_2014` and :cite:t:`di_napoli_mean_2020`.

    Parameters
    ----------
    time : xr.DataArray
        The UTC time. If not daily and `stat` is "integral" or "average",
        the timestamp is taken as the start of interval.
        If daily, the interval is assumed to be centered on Noon.
        If fewer than three timesteps are given, a daily frequency is assumed.
    declination : xr.DataArray
        Solar declination. See :py:func:`solar_declination`.
    lat : Quantified
        Latitude coordinate. Expects units of "degree_north".
    lon : Quantified
        Longitude. Needed if the input timeseries is subdaily.
    time_correction : xr.DataArray, optional
        Time correction for solar angle. See :py:func:`time_correction_for_solar_angle`
        This is necessary if stat is "instant".
    stat : {'average', 'integral', 'instant'}
        Which daily statistic to return.
        If "average", this returns the average of the cosine of the zenith angle
        If "integral", this returns the integral of the cosine of the zenith angle
        If "instant", this returns the instantaneous cosine of the zenith angle
    sunlit : bool
        If True, only the sunlit part of the interval is considered in the integral or average.
        Does nothing if stat is "instant".
    chunks : dictionary
        When `time`,  `lat` and `lon` originate from coordinates of a large chunked dataset, this dataset's chunking
        can be passed here to ensure the computation is also chunked.

    Returns
    -------
    xr.DataArray, [rad] or [dimensionless]
        Cosine of the solar zenith angle. If stat is "integral", dimensions can be said to be "time" as the integral
        is on the hour angle.
        For seconds, multiply by the number of seconds in a complete day cycle (24*60*60) and divide by 2π.

    Notes
    -----
    This code was inspired by the `thermofeel` and `PyWBGT` package.

    References
    ----------
    :cite:cts:`kalogirou_chapter_2014,di_napoli_mean_2020`
    """
    declination = convert_units_to(declination, "rad")
    lat = _wrap_radians(convert_units_to(lat, "rad"))
    lon = convert_units_to(lon, "rad")
    declination, lat, lon = _chunk_like(declination, lat, lon, chunks=chunks)

    S_IN_D = 24 * 3600

    if len(time) < 3 or xr.infer_freq(time) == "D":
        h_s = -np.pi if stat != "instant" else 0
        h_e = np.pi - 1e-9  # just below pi
    else:
        if time.dtype == "O":  # cftime
            time_as_s = time.copy(data=xr.CFTimeIndex(cast(CFTimeIndex, time.values)).asi8 / 1e6)
        else:  # numpy
            time_as_s = time.copy(data=time.astype(float) / 1e9)
        h_s_utc = (((time_as_s % S_IN_D) / S_IN_D) * 2 * np.pi + np.pi).assign_attrs(units="rad")
        h_s = h_s_utc + lon

        interval_as_s = time.diff("time").dt.seconds.reindex(time=time.time, method="bfill")
        h_e = h_s + 2 * np.pi * interval_as_s / S_IN_D

    if stat == "instant":
        h_s = h_s + time_correction

        return cast(
            xr.DataArray,
            np.sin(declination) * np.sin(lat) + np.cos(declination) * np.cos(lat) * np.cos(h_s),
        ).clip(0, None)
    if stat not in {"average", "integral"}:
        raise NotImplementedError("Argument 'stat' must be one of 'integral', 'average' or 'instant'.")
    if sunlit:
        # hour angle of sunset (eq. 2.15), with NaNs inside the polar day/night
        tantan = cast(xr.DataArray, -np.tan(lat) * np.tan(declination))
        h_ss = np.arccos(tantan.where(abs(tantan) <= 1))
    else:
        # Whole period, so we put sunset at midnight
        h_ss = np.pi - 1e-9

    return xr.apply_ufunc(
        _sunlit_integral_of_cosine_of_solar_zenith_angle,
        declination,
        lat,
        _wrap_radians(h_ss),
        _wrap_radians(h_s),
        _wrap_radians(h_e),
        stat == "average",
        input_core_dims=[[]] * 6,
        dask="parallelized",
    )


@nb.vectorize
def _sunlit_integral_of_cosine_of_solar_zenith_angle(declination, lat, h_sunset, h_start, h_end, average):
    """Integral of the cosine of the solar zenith angle over the sunlit part of the interval."""
    # Code inspired by PyWBGT
    h_sunrise = -h_sunset
    # Polar day
    if np.isnan(h_sunset) & ((declination * lat) > 0):
        num = np.sin(h_end) - np.sin(h_start)
        # Polar day with interval crossing midnight
        if h_end < h_start:
            denum = h_end + 2 * np.pi - h_start
        else:
            denum = h_end - h_start
    # Polar night:
    elif np.isnan(h_sunset) & ((declination * lat) < 0):
        return 0
    # No sunlit interval (at night) 1) crossing midnight and 2) between 0h and sunrise 3) between sunset and 0h
    elif (
        (h_start > h_sunset and h_end < h_sunrise)
        or (h_start < h_sunrise and h_end < h_sunrise)
        or (h_start > h_sunset and h_end > h_sunset)
    ):
        return 0
    # Interval crossing midnight, starting after sunset (before midnight), finishing after sunrise
    elif h_start > h_end >= h_sunrise and h_start >= h_sunset:
        num = np.sin(h_end) - np.sin(h_sunrise)
        denum = h_end - h_sunrise
    # Interval crossing midnight, starting after sunrise, finishing after sunset (after midnight)
    elif h_end < h_start and h_start >= h_sunrise >= h_end:
        num = np.sin(h_sunset) - np.sin(h_start)
        denum = h_sunset - h_start
    # Interval crossing midnight, starting before sunset, finishing after sunrise (2 sunlit parts)
    elif h_sunset >= h_start > h_end >= h_sunrise:
        num = np.sin(h_sunset) - np.sin(h_start) + np.sin(h_end) - np.sin(h_sunrise)
        denum = h_sunset - h_start + h_end - h_sunrise
    # All other cases : interval not crossing midnight, overlapping with the sunlit part
    else:
        h1 = max(h_sunrise, h_start)
        h2 = min(h_sunset, h_end)
        num = np.sin(h2) - np.sin(h1)
        denum = h2 - h1
    out = np.sin(declination) * np.sin(lat) * denum + np.cos(declination) * np.cos(lat) * num
    if average:
        out = out / denum
    return out


def extraterrestrial_solar_radiation(
    times: xr.DataArray,
    lat: xr.DataArray,
    solar_constant: Quantified = "1361 W m-2",
    method: Literal["spencer", "simple"] = "spencer",
    chunks: Mapping[Any, tuple] | None = None,
) -> xr.DataArray:
    """
    Extraterrestrial solar radiation.

    This is the daily energy received on a surface parallel to the ground at the mean distance of the earth to the sun.
    It neglects the effect of the atmosphere. Computation is based on :cite:t:`kalogirou_chapter_2014` and the default
    solar constant is taken from :cite:t:`matthes_solar_2017`.

    Parameters
    ----------
    times : xr.DataArray
        Daily datetime data. This function makes no sense with data of other frequency.
    lat : xr.DataArray
        Latitude coordinate. Expects units of "degree_north".
    solar_constant : str
        The solar constant, the energy received on earth from the sun per surface per time.
    method : {'spencer', 'simple'}
        Which method to use when computing the solar declination and the eccentricity correction factor.
        See :py:func:`solar_declination` and :py:func:`eccentricity_correction_factor`.
    chunks : dict
        When `times` and `lat` originate from coordinates of a large chunked dataset, passing the dataset's chunks here
        will ensure the computation is chunked as well.

    Returns
    -------
    xr.DataArray, [J m-2 d-1]
        Extraterrestrial solar radiation.

    References
    ----------
    :cite:cts:`kalogirou_chapter_2014,matthes_solar_2017`
    """
    dr = eccentricity_correction_factor(times, method=method)
    ds = solar_declination(times, method=method)
    gsc = convert_units_to(solar_constant, "J m-2 d-1")
    rad_to_day = 1 / (2 * np.pi)  # convert radians of the "day circle" to day
    return (
        gsc
        * rad_to_day
        * cosine_of_solar_zenith_angle(times, ds, lat=lat, stat="integral", sunlit=True, chunks=chunks)
        * dr
    ).assign_attrs(units="J m-2 d-1")


def day_lengths(
    dates: xr.DataArray,
    lat: Quantified | xr.Dataset | xr.DataTree,
    method: Literal["spencer", "simple"] = "spencer",
    infill_polar_days: bool = False,
) -> xr.DataArray:
    r"""
    Calculate day-length according to latitude and day of the year.

    See :py:func:`solar_declination` for the approximation used to compute the solar declination angle.
    Based on :cite:t:`kalogirou_chapter_2014`.

    Parameters
    ----------
    dates : xr.DataArray
        Daily datetime data.
        This function makes no sense with data of other time frequencies.
    lat : Quantified or xarray.Dataset or xarray.DataTree
        Latitude coordinate. Expects units of "degree_north".
    method : {'spencer', 'simple'}
        Which approximation to use when computing the solar declination angle.
        See :py:func:`xclim.indices.helpers.solar_declination`.
    infill_polar_days : bool
        Whether to use a mask of 24 hours for polar days and 0 hours for polar nights.
        If False, polar days and nights will be NaN.
        If True, they will be filled with 24 and 0 hours, respectively,
        dependent on latitude and solar declination at the given date.

    Returns
    -------
    xarray.DataArray, [hours]
        Day-lengths in hours per individual day.

    Raises
    ------
    NotImplementedError
        If a series of dates provided are not inferrable at a daily time frequency.

    Notes
    -----
    The day length is computed as the time between sunrise and sunset.
    The infill_polar_days option provides an arbitrary method fill polar days and nights with
    24 and 0 hours, respectively. Care should be taken when using this option, as it may not be
    appropriate for all applications.

    References
    ----------
    :cite:cts:`kalogirou_chapter_2014`
    """
    if len(dates) >= 3 and xr.infer_freq(dates) != "D":
        raise NotImplementedError("day_lengths only supports daily data.")

    declination = solar_declination(dates.time, method=method)
    radians = convert_units_to(lat, "rad")
    lat_deg = convert_units_to(lat, "deg")
    # arccos gives the hour-angle at sunset, multiply by 24 / 2π to get hours.
    # The day length is twice that.
    with np.errstate(invalid="ignore"):
        day_length_hours = ((24 / np.pi) * np.arccos(-np.tan(radians) * np.tan(declination))).assign_attrs(units="h")

    if infill_polar_days:
        lat_broadcast, decl_broadcast = xr.broadcast(lat_deg, declination)
        # Polar day: sun never sets; Polar night: sun never rises.
        polar_day = ((lat_broadcast > 66.5) & (decl_broadcast > 0)) | ((lat_broadcast < -66.5) & (decl_broadcast < 0))
        polar_night = ((lat_broadcast > 66.5) & (decl_broadcast < 0)) | ((lat_broadcast < -66.5) & (decl_broadcast > 0))
        # Infill polar days with 24 hours and polar nights with 0 hours.
        valid = ~xr.ufuncs.isnan(day_length_hours)
        day_length_hours = day_length_hours.where(~(polar_day & ~valid), 24.0)
        day_length_hours = day_length_hours.where(~(polar_night & ~valid), 0)

    # Drop nonessential coordinates
    for coord in day_length_hours.coords:
        if coord not in ["lat", "time"]:
            day_length_hours = day_length_hours.drop_vars(coord)

    return day_length_hours


def huglin_day_length_latitude_coefficient(
    lat: xr.DataArray | str,
    method: Literal["huglin", "interpolated"],
    cap_value: float = np.nan,
) -> xr.DataArray:
    r"""
    Simple coefficient for the day-length and high latitudes.

    This latitude coefficient is used for determining the latitude effect on the day length specific to climate indices
    that concern viticulture, such as :py:func:`xclim.indices.huglin_index` (cite:p:`huglin_nouveau_1978`).
    This function is an empirical approximation of the day-length multiplication factor, :math:`k`, based on latitude.

    Parameters
    ----------
    lat : xarray.DataArray, str
        Latitude coordinate. Expects units of "degree_north".
        If provided a string (e.g. "45 degree_north"), it is converted to an xarray.DataArray.
    method : {"huglin", "interpolated"}
        The method to use for the coefficient calculation.
    cap_value : float
        For latitudes north of 50° N and south of 50° S, the value for the coefficient.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Coefficient for the day length based on latitude.

    Notes
    -----
    For the original `"huglin"` implementation :cite:p:`huglin_nouveau_1978`, the day-length multiplication factor,
    :math:`k`, is calculated as follows:

    .. math::

       k = f(lat) = \begin{cases}
                     1.0, & \text{if } | lat | <= 40 \\
                     1.02, & \text{if } 40 < | lat | <= 42 \\
                     1.03, & \text{if } 42 < | lat | <= 44 \\
                     1.04, & \text{if } 44 < | lat | <= 46 \\
                     1.05, & \text{if } 46 < | lat | <= 48 \\
                     1.06, & \text{if } 48 < | lat | <= 50 \\
                     m, & \text{if } | lat | > 50 \\
                     \end{cases}

    An alternative implementation (`"interpolated"`) uses smoothing to reduce the stepwise behaviour of the
    "huglin"` method. The day-length multiplication factor (:math:`k`) for the `"interpolated"` method then is
    calculated as follows:

    .. math::

       k = f(lat) = \begin{cases}
                     1, & \text{if } | lat | <= 40 \\
                     1 + ((abs(lat) - 40) / 10) * 0.06, & \text{if } 40 < | lat | <= 50 \\
                     m, & \text{if } | lat | > 50 \\
                     \end{cases}

    Where :math:`m` is the cap value, which is set to np.nan, or other if provided.

    References
    ----------
    :cite:cts:`huglin_nouveau_1978,project_team_eca&d_algorithm_2013`
    """
    if isinstance(lat, str):
        _lat_value = convert_units_to(lat, "deg")
        _lat = xr.DataArray(lat, attrs={"units": "degree_north"})
    else:
        _lat = lat

    if isinstance(cap_value, float):
        _cap_value = cap_value
    else:
        raise TypeError("Argument 'cap_value' must be a float (or numpy.nan).")

    lat_abs = abs(lat)
    if method == "huglin":
        k_f_bounds = [(0, -np.inf, 40), (0.02, 40, 42), (0.03, 42, 44), (0.04, 44, 46), (0.05, 46, 48), (0.06, 48, 50)]
        k = xr.full_like(lat_abs, _cap_value + 1)
        for k_f_b in k_f_bounds:
            cond = (k_f_b[1] < lat_abs) & (lat_abs <= k_f_b[2])
            k = k.where(~cond, 1 + k_f_b[0])
    elif method == "interpolated":
        lat_mask = lat_abs <= 50
        lat_coefficient = 1 + ((lat_abs - 40) / 10).clip(min=0) * 0.06
        k = xr.where(lat_mask, lat_coefficient, _cap_value)
    else:
        raise NotImplementedError("Method is not implemented. Only 'huglin' and 'interpolated' are permitted.")

    return k


def gladstones_day_length_latitude_coefficient(
    dates: xr.DataArray,
    lat: xr.DataArray | int | float,
    neutral_latitude: str = "40.0 deg",
    constrain: str | None = None,
    day_length_method: Literal["simple", "spencer"] = "spencer",
) -> xr.DataArray:
    """
    Day-length latitude coefficient based on the Gladstones methodology.

    This function computes a day-length latitude coefficient as it influences the monthly temperatures
    of the growing season as compared to the day-length of a neutral reference latitude.
    Based on :cite:t:`gladstones_viticulture_1992` and cite:t:`gladstones_wine_2011`.

    Parameters
    ----------
    dates : xarray.DataArray
        The dates for which the day length latitude coefficient is computed.
    lat : xarray.DataArray or int or float
        Latitude coordinate. Expects units of "degree_north".
        If a single value is given, it is converted to an xarray.DataArray.
    neutral_latitude : str
        The latitude at which the day length coefficient is 1.0.
        Latitudes between this value and 0 degrees North will have a coefficient below 1.0 during the growing season,
        while latitudes above this value will have a coefficient greater than 1.0.
        This negative absolute value of this latitude is used for calculating coefficients in the Southern Hemisphere.
    constrain : str, optional
        The lower latitude limit for applying the latitude coefficient.
        If a str is given (e.g. '25 degree_north`), values below this threshold will be set to '1.0'.
    day_length_method : {'simple', 'spencer'}
        The method to use for the day length calculation.
        The "simple" method uses a simple approximation of the day length based on latitude and time of year.
        The "spencer" method uses a more complex approximation based on the Fourier series of the solar declination.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Coefficient for the day length based on latitude.
    """
    if not isinstance(lat, xr.DataArray):
        lat = xr.DataArray(lat, attrs={"units": "degree_north"})
    if day_length_method not in ["simple", "spencer"]:
        raise NotImplementedError("day_length_method must be one of 'simple' or 'spencer'.")

    if isinstance(constrain, str):
        constrain_value = convert_units_to(constrain, "deg")
    elif constrain is None:
        constrain_value = False
    else:
        raise ValueError("Argument 'constrain' must be a str (e.g. '25 degree_north') or 'None'.")

    _neutral_latitude = convert_units_to(neutral_latitude, "deg")

    pivotal_day_length_north = day_lengths(dates=dates, lat=f"{abs(_neutral_latitude)} deg", method=day_length_method)
    pivotal_day_length_south = day_lengths(dates=dates, lat=f"{-abs(_neutral_latitude)} deg", method=day_length_method)
    day_length = day_lengths(dates=dates, lat=lat, method=day_length_method)

    if not constrain_value:
        k = xr.where(lat >= 0.0, day_length / pivotal_day_length_north, day_length / pivotal_day_length_south)
    else:
        k = xr.where(
            lat >= constrain_value,
            day_length / pivotal_day_length_north,
            xr.where(lat <= -constrain_value, day_length / pivotal_day_length_south, 1.0),
        )
    k = k.assign_attrs(units="dimensionless")

    return k


def jones_day_length_latitude_coefficient(
    dates: xr.DataArray,
    lat: xr.DataArray | xr.Dataset | xr.DataTree,
    method: Literal["gladstones", "jones"],
    floor: bool = False,
    start_date: str | DayOfYearStr = "04-01",
    end_date: str | DayOfYearStr = "11-01",
    freq: Literal["YS", "YS-JAN", "YS-JUL"] = "YS",
) -> xr.DataArray:
    r"""
    Complex day length latitude coefficient.

    This function computes a day length latitude coefficient as it influences the entire growing season.
    Based on cite:t:`hall_spatial_2010`.

    Parameters
    ----------
    dates : xarray.DataArray
        The dates for which the day length latitude coefficient is computed.
    lat : xr.DataArray or xr.Dataset or xr.DataTree
        Latitude coordinate. Expects units of "degree_north".
        If a single value is given, it is converted to an xarray.DataArray.
    method : {"gladstones", "jones"}
        The method to use for the coefficient calculation.
        The "jones" method .
        The "gladstones" method uses an approximation of the Gladstones methodology for day length latitude coefficient.
    floor : bool, optional
        If True, latitudes where the day length latitude coefficient would be below '1.0', the value is set to '1.0'.
        if False, coefficient can be below '1.0' for latitudes where the day length is less than the reference latitude.
    start_date : str or DayOfYearStr
        The start date of the growing season.
    end_date : str or DayOfYearStr
        The end date of the growing season. Date is not included in the aggregation.
    freq : {"YS", "YS-JAN", "YS-JUL"}
        The frequency at which to aggregate the day lengths.
        Must be an annual frequency, such as "YS" or "YS-JAN" (yearly start in January)
        or "YS-JUL" (yearly start in July).

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Coefficient for the day length based on latitude, aggregated over the growing season.

    Raises
    ------
    ValueError
        If all latitudes for every computed growing season have a day length latitude coefficient below 1.0.

    Notes
    -----
    For the `"jones"` method, A more robust day-length calculation based on latitude, calendar, day-of-year, and
    obliquity is used. This algorithm requires a calculation of the sum of the day lengths over the growing season
    at each latitude, :math:`totalSeasonDayLength_{Lat}`, which is then used to calculate the day length latitude
    coefficient :math:`k`:

    .. math::

        totalSeasonDayLength_{Lat} = \sum_{Jday=\text{103}}^{\text{284}}{dayLength_{Lat_{JDay}}}

    The day length latitude coefficient (:math:`k`) using the "jones" method is calculated as follows:

    .. math::

         k_{Lat} = 2.8311e-4 * totalSeasonDayLength_{Lat} + 0.30834

    The "gladstones" method provided here is a transformation of the "jones" method, based on the relationship
    detailed in :cite:t:`hall_spatial_2010`:

    .. math::

        k_{Lat}^{Gladstones} = 1.1135 * k_{Lat}^{Jones} - 0.1352

    For both of these methods, the :math:`k` coefficient must be calculated at the growing season frequency (yearly),
    starting from either January or July, depending on the hemisphere of interest.
    """
    if parse_offset(freq) not in [(1, "Y", True, "JAN"), (1, "Y", True, "JUL")]:
        msg = (
            f"Freq {freq} not supported. Must be 'YS'/'YS-JAN', or 'YS-JUL' for method 'jones'. "
            "An annual frequency is required for the current implementation."
        )
        raise NotImplementedError(msg)

    if method in ["gladstones", "jones"]:
        if freq == "YS-JUL":
            pass
        day_length = (
            select_time(
                day_lengths(dates=dates, lat=lat, method="spencer", infill_polar_days=False),
                date_bounds=(start_date, end_date),
                include_bounds=(True, False),
            )
            .dropna(dim="time", how="all")
            .dropna(dim="lat", how="any")
            .resample(time=freq)
            .sum()
        )
        k_jones: xr.DataArray = (2.8311e-4 * day_length) + 0.30834

        all_below_1 = (k_jones < 1.0).all(dim="lat")
        k_jones = k_jones.where(~all_below_1, np.nan)
        if k_jones.isnull().all():
            msg = (
                "All latitudes for every growing season have a day length latitude coefficient below 1.0. "
                "This is likely due to the start and end dates of the growing season being too restrictive "
                "or an incomplete time series."
            )
            raise ValueError(msg)

        if method == "jones":
            k_aggregated = k_jones
        else:
            k_aggregated = 1.1135 * k_jones - 0.1352
    else:
        raise NotImplementedError("Method not implemented. Only 'gladstones' or 'jones' are supported.")

    if floor:
        k_aggregated = k_aggregated.where(k_aggregated >= 1.0, 1.0)

    return k_aggregated


def wind_speed_height_conversion(
    ua: xr.DataArray,
    h_source: str,
    h_target: str,
    method: Literal["log"] = "log",
) -> xr.DataArray:
    r"""
    Wind speed at two meters.

    Parameters
    ----------
    ua : xarray.DataArray
        Wind speed at height `h`.
    h_source : str
        Height of the input wind speed `ua` (e.g. `h == "10 m"` for a wind speed at `10 meters`).
    h_target : str
        Height of the output wind speed.
    method : {"log"}
        Method used to convert wind speed from one height to another.

    Returns
    -------
    xarray.DataArray
        Wind speed at height `h_target`.

    References
    ----------
    :cite:cts:`allen_crop_1998`
    """
    h_source = convert_units_to(h_source, "m")
    h_target = convert_units_to(h_target, "m")
    if method == "log":
        if min(h_source, h_target) < 1 + 5.42 / 67.8:
            raise ValueError(
                f"The height {min(h_source, h_target)}m is too small for method {method}. "
                f"Heights must be greater than {1 + 5.42 / 67.8}"
            )
        with xr.set_options(keep_attrs=True):
            return ua * np.log(67.8 * h_target - 5.42) / np.log(67.8 * h_source - 5.42)
    else:
        raise NotImplementedError(f"'{method}' method is not implemented.")


def _gather_lat(da: xr.DataArray) -> xr.DataArray:
    """
    Gather latitude coordinate using cf-xarray.

    Parameters
    ----------
    da : xarray.DataArray
        CF-conformant DataArray with a "latitude" coordinate.

    Returns
    -------
    xarray.DataArray
        Latitude coordinate.
    """
    try:
        lat = da.cf["latitude"]
        return lat
    except KeyError as err:
        n_func = stack()[1].function
        msg = f"{n_func} could not find latitude coordinate in DataArray. Try passing it explicitly (`lat=ds.lat`)."
        raise ValueError(msg) from err


def _gather_lon(da: xr.DataArray) -> xr.DataArray:
    """
    Gather longitude coordinate using cf-xarray.

    Parameters
    ----------
    da : xarray.DataArray
        CF-conformant DataArray with a "longitude" coordinate.

    Returns
    -------
    xarray.DataArray
        Longitude coordinate.
    """
    try:
        lat = da.cf["longitude"]
        return lat
    except KeyError as err:
        n_func = stack()[1].function
        msg = f"{n_func} could not find longitude coordinate in DataArray. Try passing it explicitly (`lon=ds.lon`)."
        raise ValueError(msg) from err


def resample_map(
    obj: xr.DataArray | xr.Dataset,
    dim: str,
    freq: str,
    func: Callable,
    map_blocks: bool | Literal["from_context"] = "from_context",
    resample_kwargs: dict | None = None,
    map_kwargs: dict | None = None,
) -> xr.DataArray | xr.Dataset:
    r"""
    Wrap xarray's resample(...).map() with a :py:func:`xarray.map_blocks`.

    Ensures that the chunking is appropriate using `flox`.

    Parameters
    ----------
    obj : DataArray or Dataset
        The xarray object to resample.
    dim : str
        Dimension over which to resample.
    freq : str
        Resampling frequency along `dim`.
    func : callable
        Function to map on each resampled group.
    map_blocks : bool or "from_context"
        If True, the resample().map() call is wrapped inside a `map_blocks`.
        If False, this does not do anything special.
        If "from_context", xclim's "resample_map_blocks" option is used.
        If the object is not using dask, this is set to False.
    resample_kwargs : dict, optional
        Other arguments to pass to `obj.resample()`.
    map_kwargs : dict, optional
        Arguments to pass to `map`.

    Returns
    -------
    xr.DataArray or xr.Dataset
        Resampled object.
    """
    resample_kwargs = resample_kwargs or {}
    map_kwargs = map_kwargs or {}
    if map_blocks == "from_context":
        map_blocks = OPTIONS[MAP_BLOCKS]

    if not uses_dask(obj) or not map_blocks:
        return obj.resample({dim: freq}, **resample_kwargs).map(func, **map_kwargs)

    if rechunk_for_blockwise is None:
        msg = f"Using {MAP_BLOCKS}=True requires flox."
        raise ValueError(msg) from flox_err

    # Make labels, a unique integer for each resample group
    labels = xr.full_like(obj[dim], -1, dtype=np.int32)
    for lbl, group_slice in enumerate(obj[dim].resample({dim: freq}).groups.values()):
        labels[group_slice] = lbl

    obj_rechunked = rechunk_for_blockwise(obj, dim, labels)

    def _resample_map(obj_chnk, dm, frq, rs_kws, fun, mp_kws):
        return obj_chnk.resample({dm: frq}, **rs_kws).map(fun, **mp_kws)

    # Template. We are hoping that this takes a negligeable time as it is never loaded.
    template = obj_rechunked.resample(**{dim: freq}, **resample_kwargs).first()

    # New chunks along the time dim : infer the number of elements resulting from the resampling of each chunk
    if isinstance(obj_rechunked, xr.Dataset):
        chunksizes = obj_rechunked.chunks[dim]
    else:
        chunksizes = obj_rechunked.chunks[obj_rechunked.get_axis_num(dim)]
    new_chunks = []
    i = 0
    for chunksize in chunksizes:
        new_chunks.append(len(np.unique(labels[i : i + chunksize])))
        i += chunksize
    template = template.chunk({dim: tuple(new_chunks)})

    return obj_rechunked.map_blocks(_resample_map, (dim, freq, resample_kwargs, func, map_kwargs), template=template)


def _compute_daytime_temperature(
    hour_after_sunrise: xr.DataArray,
    tasmin: xr.DataArray,
    tasmax: xr.DataArray,
    daylength: xr.DataArray,
) -> xr.DataArray:
    """
    Compute daytime temperature based on a sinusoidal profile.

    Minimum temperature is reached at sunrise and maximum temperature 2h before sunset.

    Parameters
    ----------
    hour_after_sunrise : xarray.DataArray
        Hours after the last sunrise.
    tasmin : xarray.DataArray
        Daily minimum temperature.
    tasmax : xarray.DataArray
        Daily maximum temperature.
    daylength : xarray.DataArray
        Length of the day in hours.

    Returns
    -------
    xarray.DataArray
        Hourly daytime temperature.
    """
    return (tasmax - tasmin) * np.sin((np.pi * hour_after_sunrise) / (daylength + 4)) + tasmin


def _compute_nighttime_temperature(
    hours_after_sunset: xr.DataArray,
    tasmin: xr.DataArray,
    tas_sunset: xr.DataArray,
    daylength: xr.DataArray,
) -> xr.DataArray:
    """
    Compute nighttime temperature based on a logarithmic profile.

    Temperature at sunset is computed from previous daytime temperature,
    minimum temperature is reached at sunrise.

    Parameters
    ----------
    hours_after_sunset : xarray.DataArray
        Hours after the last sunset.
    tasmin : xarray.DataArray
        Daily minimum temperature.
    tas_sunset : xarray.DataArray
        Temperature at last sunset.
    daylength : xarray.DataArray
        Length of the day in hours.

    Returns
    -------
    xarray.DataArray
        Hourly nighttime temperature.
    """
    return tas_sunset - ((tas_sunset - tasmin) / np.log(24 - daylength)) * np.log(hours_after_sunset)


def _add_one_day(time: xr.DataArray) -> xr.DataArray:
    """
    Add one day to a time coordinate.

    Depending on the calendar/dtype of the time array we need to use numpy's or datetime's (for cftimes) timedelta.

    Parameters
    ----------
    time : xr.DataArray
        Time coordinate.

    Returns
    -------
    xr.DataArray
        Next day.
    """
    if time.dtype == "O":
        return time + timedelta(days=1)
    return time + np.timedelta64(1, "D")


def make_hourly_temperature(tasmin: xr.DataArray, tasmax: xr.DataArray) -> xr.DataArray:
    """
    Compute hourly temperatures from tasmin and tasmax.

    Based on the Linvill et al. "Calculating Chilling Hours and Chill Units from Daily
    Maximum and Minimum Temperature Observations", HortScience, 1990
    we assume a sinusoidal temperature profile during daylight and a logarithmic decrease after sunset
    with tasmin reached at sunsrise and tasmax reached 2h before sunset.

    For simplicity and because it's used for daily aggregation, we assume that sunrise globally happens at midnight
    and the sunsets after `daylength` hours computed via the :py:func:`day_lengths` function.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Daily minimum temperature.
    tasmax : xarray.DataArray
        Daily maximum temperature.

    Returns
    -------
    xarray.DataArray
        Hourly temperature.
    """
    data = xr.merge([tasmin, tasmax])
    data = data.assign_coords(time=data.time.dt.floor("D"))
    # We add one more timestamp so the resample function includes the last day
    data = xr.concat(
        [
            data,
            data.isel(time=-1).assign_coords(time=_add_one_day(data.isel(time=-1).time)),
        ],
        dim="time",
    )

    daylength = day_lengths(data.time, data.lat)
    # Create daily chunks to avoid memory issues after the resampling
    data = data.assign(
        daylength=daylength,
        sunset_temp=_compute_daytime_temperature(daylength, data.tasmin, data.tasmax, daylength),
        next_tasmin=data.tasmin.shift(time=-1),
    )
    # Compute hourly data by resampling and remove the last time stamp that was added earlier
    hourly = data.resample(time="h").ffill().isel(time=slice(0, -1))

    # To avoid "invalid value encountered in log" warning we set hours before sunset to 1
    nighttime_hours = (hourly.time.dt.hour + 1 - hourly.daylength).clip(1)

    return xr.where(
        hourly.time.dt.hour < hourly.daylength,
        _compute_daytime_temperature(hourly.time.dt.hour, hourly.tasmin, hourly.tasmax, hourly.daylength),
        _compute_nighttime_temperature(
            nighttime_hours,
            hourly.next_tasmin,
            hourly.sunset_temp,
            hourly.daylength - 1,
        ),
    ).assign_attrs(units=tasmin.units)
