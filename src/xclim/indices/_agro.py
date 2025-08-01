"""Agroclimatic indice definitions."""

from __future__ import annotations

import warnings
from typing import Literal, cast

import numpy as np
import xarray
from scipy.stats import rv_continuous

import xclim.indices.run_length as rl
from xclim.core import DateStr, DayOfYearStr, Quantified
from xclim.core.calendar import parse_offset, select_time
from xclim.core.units import (
    amount2lwethickness,
    convert_units_to,
    declare_units,
    rate2amount,
    to_agg_units,
)
from xclim.core.utils import uses_dask
from xclim.indices._conversion import potential_evapotranspiration
from xclim.indices._simple import tn_min
from xclim.indices._threshold import (
    first_day_temperature_above,
    first_day_temperature_below,
)
from xclim.indices.generic import aggregate_between_dates, get_zones
from xclim.indices.helpers import (
    _gather_lat,
    gladstones_day_length_latitude_coefficient,
    huglin_day_length_latitude_coefficient,
    jones_day_length_latitude_coefficient,
    resample_map,
)
from xclim.indices.stats import standardized_index

# Frequencies: YS: year start, QS-DEC: seasons starting in december, MS: month start
# See https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html

# -------------------------------------------------- #
# ATTENTION: ASSUME ALL INDICES WRONG UNTIL TESTED ! #
# -------------------------------------------------- #

__all__ = [
    "biologically_effective_degree_days",
    "chill_portions",
    "chill_units",
    "cool_night_index",
    "corn_heat_units",
    "dryness_index",
    "effective_growing_degree_days",
    "hardiness_zones",
    "huglin_index",
    "latitude_temperature_index",
    "qian_weighted_mean_average",
    "rain_season",
    "standardized_precipitation_evapotranspiration_index",
    "standardized_precipitation_index",
    "water_budget",
]


@declare_units(
    tasmin="[temperature]",
    tasmax="[temperature]",
    thresh_tasmin="[temperature]",
    thresh_tasmax="[temperature]",
)
def corn_heat_units(
    tasmin: xarray.DataArray,
    tasmax: xarray.DataArray,
    thresh_tasmin: Quantified = "4.44 degC",
    thresh_tasmax: Quantified = "10 degC",
) -> xarray.DataArray:
    r"""
    Corn heat units.

    Temperature-based index used to estimate the development of corn crops.
    Formula adapted from :cite:t:`bootsma_risk_1999`.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh_tasmin : Quantified
        The minimum temperature threshold needed for corn growth.
    thresh_tasmax : Quantified
        The maximum temperature threshold needed for corn growth.

    Returns
    -------
    xarray.DataArray, [unitless]
        Daily corn heat units.

    Notes
    -----
    Formula used in calculating the Corn Heat Units for the Agroclimatic Atlas of Quebec :cite:p:`audet_atlas_2012`.

    The thresholds of 4.44°C for minimum temperatures and 10°C for maximum temperatures were selected following
    the assumption that no growth occurs below these values.

    Let :math:`TX_{i}` and :math:`TN_{i}` be the daily maximum and minimum temperature at day :math:`i`. Then the daily
    corn heat unit is:

    .. math::

       CHU_i = \frac{YX_{i} + YN_{i}}{2}

    with

    .. math::

       YX_i & = 3.33(TX_i -10) - 0.084(TX_i -10)^2, &\text{if } TX_i > 10°C
       YN_i & = 1.8(TN_i -4.44), &\text{if } TN_i > 4.44°C

    Where :math:`YX_{i}` and :math:`YN_{i}` is 0 when :math:`TX_i \leq 10°C` and :math:`TN_i \leq 4.44°C`, respectively.

    References
    ----------
    :cite:cts:`audet_atlas_2012,bootsma_risk_1999`
    """
    tasmin = convert_units_to(tasmin, "degC")
    tasmax = convert_units_to(tasmax, "degC")
    thresh_tasmin = convert_units_to(thresh_tasmin, "degC")
    thresh_tasmax = convert_units_to(thresh_tasmax, "degC")

    mask_tasmin = tasmin > thresh_tasmin
    mask_tasmax = tasmax > thresh_tasmax

    chu: xarray.DataArray = (
        xarray.where(mask_tasmin, 1.8 * (tasmin - thresh_tasmin), 0)
        + xarray.where(
            mask_tasmax,
            (3.33 * (tasmax - thresh_tasmax) - 0.084 * (tasmax - thresh_tasmax) ** 2),
            0,
        )
    ) / 2

    chu = chu.assign_attrs(units="")
    return chu


@declare_units(
    tas="[temperature]",
    tasmax="[temperature]",
    lat="[]",
    thresh="[temperature]",
)
def huglin_index(
    tas: xarray.DataArray,
    tasmax: xarray.DataArray,
    lat: xarray.DataArray | None = None,
    thresh: Quantified = "10 degC",
    method: str = "smoothed",
    cap_value: float = 1.0,
    start_date: str | DayOfYearStr = "04-01",
    end_date: str | DayOfYearStr = "10-01",
    freq: Literal["YS", "YS-JAN", "YS-JUL"] = "YS",
) -> xarray.DataArray:
    r"""
    Heliothermal Index of Huglin.

    Growing-degree days with a base of 10°C and adjusted for latitudes between 40°N and 50°N for April-September
    (Northern Hemisphere; October-March in Southern Hemisphere). Originally proposed in :cite:t:`huglin_nouveau_1978`.
    Used as a heat-summation metric in viticulture agroclimatology.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    tasmax : xarray.DataArray
        Maximum daily temperature.
    lat : xarray.DataArray
        Latitude coordinate.
        If None, a CF-conformant "latitude" field must be available within the passed DataArray.
    thresh : Quantified
        The temperature threshold.
    method : {"huglin", "icclim", "interpolated", "jones"}
        The formula to use for the latitude coefficient calculation.
        The "huglin" method uses a stepwise latitude coefficient for values
        between 40° and 50° based on :cite:t:`huglin_nouveau_1978`.
        The "interpolated" method uses a smoothed curve latitude coefficient for values
        based on the intervals set in :cite:t:`huglin_nouveau_1978`.
        The "jones" method integrates axial tilt, latitude, and day-of-year based on :cite:t:`hall_spatial_2010`.
        The "icclim" method is deprecated but is identical to method "huglin".
    cap_value : float
        The value to use for the latitude coefficient when latitude is above 50°N or below 50°S.
        Only applicable for methods "huglin", "icclim", and "interpolated" (default: 1.0).
    start_date : str or DayOfYearStr
        The hemisphere-based start date to consider (north = April, south = October).
    end_date : str or DayOfYearStr
        The hemisphere-based start date to consider (north = October, south = April). This date is non-inclusive.
    freq : str
        Resampling frequency (default: "YS"; For Southern Hemisphere, should be "YS-JUL").

    Returns
    -------
    xarray.DataArray, [unitless]
        Heliothermal index of Huglin (HI).

    Notes
    -----
    Let :math:`TX_{i}` and :math:`TG_{i}` be the daily maximum and mean temperature at day :math:`i` and
    :math:`T_{thresh}` the base threshold needed for heat summation (typically, 10 degC). A day-length multiplication,
    :math:`k`, based on latitude, :math:`lat`, is also considered. Then the heliothermal index for dates between
    1 April and 30 September is:

    .. math::

       HI = \sum_{i=\text{April 1}}^{\text{September 30}} \left(\frac{TX_i + TG_i)}{2} - T_{thresh} \right) * k

    There are a few methods provided for calculating the day-length multiplication factor (:math:`k`) based on latitude:

    - For the `"huglin"/"icclim"` and `"interpolated"` methods, values for k increase from `1.0` at 40°N or 40°S to `1.06` at 50°N or 50°S,
      where the `interpolated` method uses a smoothed curve and the `huglin/icclim` method uses a stepwise function.
      Values above 50°N or below 50°S are set via the `cap_value` variable, with `1.0` set as default.
      See: :py:func:`xclim.indices.helpers.huglin_day_length_latitude_coefficient` for more information.
    - For the `"jones"` method, A more robust day-length calculation based on latitude, calendar, day-of-year,
      and obliquity is used. The current implementation requires an annual frequency for consistent results.
      See: :py:func:`xclim.indices.generic.jones_day_length_coefficient` or :cite:t:`hall_spatial_2010` for more information.

    For compatibility with the original ICCLIM implementation :cite:p:`project_team_eca&d_algorithm_2013`,
    `end_date` should be set to `11-01` with `method="huglin"`.

    References
    ----------
    :cite:cts:`huglin_nouveau_1978,hall_spatial_2010`
    """
    if not isinstance(freq, str):
        raise TypeError("Freq must be a string.")

    _tas = convert_units_to(tas, "degC")
    _tasmax = convert_units_to(tasmax, "degC")
    _thresh = convert_units_to(thresh, "degC")

    if lat is None:
        lat = _gather_lat(tas)

    k: int | xarray.DataArray = 1
    k_aggregated: xarray.DataArray | None = None
    if (method := method.lower()) in ["huglin", "icclim", "interpolated"]:
        if method == "icclim":
            warnings.warn("Method 'icclim' is deprecated. Use 'stepwise' instead.", DeprecationWarning)
            method = "huglin"
        k = huglin_day_length_latitude_coefficient(lat, method=method, cap_value=cap_value)
    elif method.lower() == "jones":
        k_aggregated = jones_day_length_latitude_coefficient(
            dates=tas.time, lat=lat, method=method, start_date=start_date, end_date=end_date, freq=freq
        )
    else:
        raise NotImplementedError(
            "Method is not implemented. Only 'huglin', 'icclim', 'interpolated', and 'jones' are supported."
        )

    hi: xarray.DataArray = (((_tas + _tasmax) / 2) - _thresh).clip(min=0) * k
    hi = select_time(hi, date_bounds=(start_date, end_date), include_bounds=(True, False)).resample(time=freq).sum()
    if k_aggregated is not None:
        hi = hi * k_aggregated
    hi = hi.assign_attrs(units="")

    return hi


@declare_units(
    tasmin="[temperature]",
    tasmax="[temperature]",
    lat="[]",
    thresh_tasmin="[temperature]",
    low_dtr="[temperature]",
    high_dtr="[temperature]",
    max_daily_degree_days="[temperature]",
)
def biologically_effective_degree_days(
    tasmin: xarray.DataArray,
    tasmax: xarray.DataArray,
    lat: xarray.DataArray | None = None,
    thresh_tasmin: Quantified = "10 degC",
    method: Literal["gladstones", "icclim", "jones", "smoothed", "stepwise"] = "gladstones",
    cap_value: float = 1.0,
    low_dtr: Quantified = "10 degC",
    high_dtr: Quantified = "13 degC",
    max_daily_degree_days: Quantified = "9 degC",
    start_date: str | DayOfYearStr = "04-01",
    end_date: str | DayOfYearStr = "11-01",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Biologically effective growing degree days.

    Growing-degree days with a base of 10°C and an upper limit of 19°C and adjusted for latitudes between 40°N and 50°N
    for April to October (Northern Hemisphere; October to April in Southern Hemisphere). A temperature range adjustment
    also promotes small and large swings in daily temperature range. Used as a heat-summation metric in viticulture
    agroclimatology.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    tasmax : xarray.DataArray
        Maximum daily temperature.
    lat : xarray.DataArray, optional
        Latitude coordinate.
        If None and method is not "icclim", a CF-conformant "latitude" field must be available within the passed DataArray.
    thresh_tasmin : Quantified
        The minimum temperature threshold.
    method : {"gladstones", "huglin", "icclim", "interpolated", "jones"}
        The formula to use for the daily temperature range and latitude coefficient.
        The "gladstones" method uses a temperature range adjustment and a latitude coefficient
        based on :cite:t:`gladstones_wine_2011`.
        End_date should be "11-01" for the Northern Hemisphere.
        The "huglin" method uses a temperature range adjustment and a stepwise latitude coefficient for values
        between 40° and 50° based on :cite:t:`huglin_nouveau_1978`.
        End_date should be "11-01" for the Northern Hemisphere.
        The "icclim" method does not implement daily temperature range and nor a latitude coefficient
        based on :cite:t:`project_team_eca&d_algorithm_2013`.
        End date should be "10-01" for the Northern Hemisphere.
        The "interpolated" method uses a temperature range adjustment and a smoothed curve latitude
        coefficient for values between 40° and 50° based on :cite:t:`huglin_nouveau_1978`.
        The "jones" method uses a temperature range adjustment and integrates axial tilt, latitude,
        and day-of-year based on :cite:t:`hall_spatial_2010`.
        End_date should be "11-01" for the Northern Hemisphere.
    cap_value : float
        The value to use for the latitude coefficient for latitudes north of 50°N or south of 50°S.
        Only applicable for methods "huglin" and "interpolated".
    low_dtr : Quantified
        The lower bound for daily temperature range adjustment.
    high_dtr : Quantified
        The higher bound for daily temperature range adjustment.
    max_daily_degree_days : Quantified
        The maximum number of biologically effective degrees days that can be summed daily.
    start_date : str or DayOfYearStr
        The hemisphere-based start date to consider (north = April, south = October).
    end_date : str or DayOfYearStr
        The hemisphere-based start date to consider (north = October, south = April).
        This date is non-inclusive.
    freq : str
        Resampling frequency (For Southern Hemisphere, should be "YS-JUL").

    Returns
    -------
    xarray.DataArray, [K days]
        Biologically effective growing degree days (BEDD).

    Warnings
    --------
    UserWarning
        Emitted if latitude is supplied for the "icclim" method, as it is not used in the calculation.

    Notes
    -----
    Lat coordinate must be provided if method is "gladstones", "gladstones_simple", or "huglin"; The "icclim" method for BEDD
    here differs from the approach detailed in the Heliothermal Index of Huglin (HI) by not considering the latitude coefficient.

    The tasmax ceiling of 19°C is assumed to be the maximum temperature beyond which no further gains from warmer daily
    temperatures occur. Indice originally published in :cite:t:`gladstones_viticulture_1992`.

    Let :math:`TX_{i}` and :math:`TN_{i}` be the daily maximum and minimum temperature at day :math:`i`, :math:`lat` the latitude
    of the point of interest, :math:`degdays_{max}` the maximum amount of degrees that can be summed per day (typically, 9).
    Then the sum of daily biologically effective growing degree day (BEDD) units between 1 April and 31 October is:

    .. math::

       BEDD_i = \sum_{i=\text{April 1}}^{\text{October 31}} min\left( \left( max\left( \frac{TX_i + TN_i)}{2} - 10, 0 \right) * k \right) + TR_{adj}, degdays_{max} \right)

    .. math::

       TR_{adj} = f(TX_{i}, TN_{i}) = \begin{cases}
       0.25(TX_{i} - TN_{i} - 13), & \text{if } (TX_{i} - TN_{i}) > 13 \\
       0, & \text{if } 10 < (TX_{i} - TN_{i}) < 13\\
       0.25(TX_{i} - TN_{i} - 10), & \text{if } (TX_{i} - TN_{i}) < 10 \\
       \end{cases}

    .. math::

       k = f(lat) = 1 + \left( \frac{\left| lat \right|}{50} * 0.06, \text{if }40 < |lat| <50, \text{else } 0\right)

    An alternative version of the BEDD (`method="icclim"`) does not consider :math:`TR_{adj}` and :math:`k` and employs a
    different end date (30 September) :cite:p:`project_team_eca&d_algorithm_2013`. The simplified formula is as follows:

    .. math::

       BEDD_i = \sum_{i=\text{April 1}}^{ \text{September 30} } min\left( max\left( \frac{TX_i + TN_i)}{2} - 10, 0 \right), degdays_{max} \right)

    References
    ----------
    :cite:cts:`gladstones_viticulture_1992,huglin_biologie_1998,project_team_eca&d_algorithm_2013,hall_spatial_2010`
    """
    if not isinstance(freq, str):
        raise TypeError("Freq must be a string.")

    _tasmin = convert_units_to(tasmin, "degC")
    _tasmax = convert_units_to(tasmax, "degC")
    thresh_tasmin_deg = convert_units_to(thresh_tasmin, "degC")
    max_daily_degree_days = convert_units_to(max_daily_degree_days, "degC")

    k: int | xarray.DataArray = 1
    k_aggregated: xarray.DataArray | None = None
    if method.lower() == "icclim":
        if lat is not None:
            warnings.warn(
                "Lat coordinate is not used for method 'icclim' in 'biologically_effective_degree_days' calculation.",
                UserWarning,
            )
        tr_adj = 0
    elif method in ["gladstones", "huglin", "interpolated", "jones"]:
        # Temperature range adjustment
        low_dtr = convert_units_to(low_dtr, "degC")
        high_dtr = convert_units_to(high_dtr, "degC")
        dtr = _tasmax - _tasmin
        tr_adj = 0.25 * xarray.where(
            dtr > high_dtr,
            dtr - high_dtr,
            xarray.where(dtr < low_dtr, dtr - low_dtr, 0),
        )

        if lat is None:
            lat = _gather_lat(tasmin)

        if method in ["huglin", "interpolated"]:
            k = huglin_day_length_latitude_coefficient(lat, method=method, cap_value=cap_value)
        elif method == "gladstones":
            k = gladstones_day_length_latitude_coefficient(dates=tasmin.time, lat=lat)
        elif method == "jones":
            k_aggregated = jones_day_length_latitude_coefficient(
                dates=tasmin.time, lat=lat, method=method, start_date=start_date, end_date=end_date, freq=freq
            )

    else:
        raise NotImplementedError(
            "Method is not implemented. Only 'gladstones', 'huglin', 'icclim', 'interpolated', and 'jones' are supported."
        )

    bedd: xarray.DataArray = ((((_tasmin + _tasmax) / 2) - thresh_tasmin_deg).clip(min=0) * k + tr_adj).clip(
        max=max_daily_degree_days
    )
    bedd = select_time(bedd, date_bounds=(start_date, end_date), include_bounds=(True, False)).resample(time=freq).sum()
    if k_aggregated is not None:
        bedd = bedd * k_aggregated
    bedd = bedd.assign_attrs(units="K days")

    return bedd


@declare_units(tasmin="[temperature]")
def cool_night_index(
    tasmin: xarray.DataArray,
    lat: xarray.DataArray | str | None = None,
    freq: Literal["YS", "YS-JAN"] = "YS",
) -> xarray.DataArray:
    """
    Cool Night Index.

    Mean minimum temperature for September (northern hemisphere) or March (Southern hemisphere).
    Used in calculating the Géoviticulture Multicriteria Classification System (:cite:t:`tonietto_multicriteria_2004`).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    lat : xarray.DataArray or {"north", "south"}, optional
        Latitude coordinate as an array, float or string.
        If None, a CF-conformant "latitude" field must be available within the passed DataArray.
    freq : {"YS", "YS-JAN"}
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [degC]
        Mean of daily minimum temperature for month of interest.

    Warnings
    --------
    This indice is calculated using minimum temperature resampled to monthly average, and therefore will accept monthly
    averaged data as inputs.

    Notes
    -----
    Given that this indice only examines September and March months, it is possible to send in DataArrays containing
    only these timesteps. Users should be aware that due to the missing values checks in wrapped Indicators, datasets
    that are missing several months will be flagged as invalid. This check can be ignored by setting the following
    context:

    .. code-block:: python

        with xclim.set_options(check_missing="skip"):
            cni = cool_night_index(tasmin)

    References
    ----------
    :cite:cts:`tonietto_multicriteria_2004`

    Examples
    --------
    >>> from xclim.indices import cool_night_index
    >>> tasmin = xr.open_dataset(path_to_tasmin_file).tasmin
    >>> cni = cool_night_index(tasmin)
    """
    if not isinstance(freq, str):
        raise TypeError("Freq must be a string.")
    if parse_offset(freq) != (1, "Y", True, "JAN"):
        raise ValueError(f"Freq not allowed: {freq}. Must be `YS` or `YS-JAN`")

    tasmin = convert_units_to(tasmin, "degC")

    # Use September in northern hemisphere, March in southern hemisphere.
    months = tasmin.time.dt.month

    if lat is None:
        lat = _gather_lat(tasmin)
    if isinstance(lat, xarray.DataArray):
        month = xarray.where(lat > 0, 9, 3)
    elif isinstance(lat, str):
        if lat.lower() == "north":
            month = 9
        elif lat.lower() == "south":
            month = 3
        else:
            raise NotImplementedError(f"Latitude value not implemented: {lat}.")
    else:
        raise ValueError("Latitude must be a DataArray or str ('north' or 'south').")

    tasmin = tasmin.where(months == month, drop=True)

    cni: xarray.DataArray = tasmin.resample(time=freq).mean(keep_attrs=True)
    cni = cni.assign_attrs(units="degC")
    return cni


@declare_units(pr="[precipitation]", evspsblpot="[precipitation]", wo="[length]")
def dryness_index(  # numpydoc ignore=SS05
    pr: xarray.DataArray,
    evspsblpot: xarray.DataArray,
    lat: xarray.DataArray | str | None = None,
    wo: Quantified = "200 mm",
    freq: Literal["YS", "YS-JAN"] = "YS",
) -> xarray.DataArray:
    r"""
    Dryness Index.

    Approximation of the water balance for the categorizing the winegrowing season. Uses both precipitation and an
    adjustment of potential evapotranspiration between April and September (Northern Hemisphere) or October and March
    (Southern hemisphere). Used in calculating the Géoviticulture Multicriteria Classification System
    (:cite:t:`tonietto_multicriteria_2004`).

    Parameters
    ----------
    pr : xarray.DataArray
        Precipitation.
    evspsblpot : xarray.DataArray
        Potential evapotranspiration.
    lat : xarray.DataArray or {"north", "south"}, optional
        Latitude coordinate as an array, float or string.
        If None, a CF-conformant "latitude" field must be available within the passed DataArray.
    wo : Quantified
        The initial soil water reserve accessible to root systems [length]. Default: 200 mm.
    freq : {"YS", "YS-JAN"}
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [mm]
        Dryness Index.

    Warnings
    --------
    Dryness Index expects CF-Convention conformant potential evapotranspiration (positive up). This indice is calculated
    using evapotranspiration and precipitation resampled and converted to monthly total accumulations, and therefore
    will accept monthly fluxes as inputs.

    Notes
    -----
    Given that this indice only examines monthly total accumulations for six-month periods depending on the hemisphere,
    it is possible to send in DataArrays containing only these timesteps. Users should be aware that due to the missing
    values checks in wrapped Indicators, datasets that are missing several months will be flagged as invalid. This check
    can be ignored by setting the following context:

    .. code-block:: python

        with xclim.set_options(check_missing="skip"):
            di = dryness_index(pr, evspsblpot)

    Let :math:`Wo` be the initial useful soil water reserve (typically "200 mm"), :math:`P` be precipitation,
    :math:`T_{v}` be the potential transpiration in the vineyard, and :math:`E_{s}` be the direct evaporation from the
    soil. Then the Dryness Index, or the estimate of soil water reserve at the end of a period (1 April to 30 September
    in the Northern Hemispherere or 1 October to 31 March in the Southern Hemisphere), can be given by the following
    formulae:

    .. math::

       W = \sum_{\text{April 1}}^{\text{September 30}} \left( Wo + P - T_{v} - E_{s} \right)

    or (for the Southern Hemisphere):

    .. math::

       W = \sum_{\text{October 1}}^{\text{March 31}} \left( Wo + P - T_{v} - E_{s} \right)

    Where :math:`T_{v}` and :math:`E_{s}` are given by the following formulae:

    .. math::

       T_{v} = ETP * k

    and

    .. math::

       E_{s} = \frac{ETP}{N}\left( 1 - k \right) * JPm

    Where :math:`ETP` is evapotranspiration, :math:`N` is the number of days in the given month. :math:`k` is the
    coefficient for radiative absorption given by the vine plant architecture, and :math:`JPm` is the number of days of
    effective evaporation from the soil per month, both provided by the following formulae:

    .. math::

       k = \begin{cases}
            0.1, & \text{if month = April (NH) or October (SH)}  \\
            0.3, & \text{if month = May (NH) or November (SH)}  \\
            0.5, & \text{if month = June - September (NH) or December - March (SH)} \\
            \end{cases}

    .. math::

       JPm = \max\left( P / 5, N \right)

    References
    ----------
    :cite:cts:`tonietto_multicriteria_2004,riou_determinisme_1994`

    Examples
    --------
    >>> from xclim.indices import dryness_index
    >>> dryi = dryness_index(pr_dataset, evspsblpot_dataset, wo="200 mm")
    """
    if not isinstance(freq, str):
        raise TypeError("Freq must be a string.")
    if parse_offset(freq) != (1, "Y", True, "JAN"):
        raise ValueError(f"Freq not allowed: {freq}. Must be `YS` or `YS-JAN`")

    # Resample all variables to monthly totals in mm units.
    evspsblpot = amount2lwethickness(rate2amount(evspsblpot), out_units="mm").resample(time="MS").sum()
    pr = amount2lwethickness(rate2amount(pr), out_units="mm").resample(time="MS").sum()
    wo = convert_units_to(wo, "mm")

    # Different potential evapotranspiration rates for northern hemisphere and southern hemisphere.
    # wo_adjustment is the initial soil moisture rate at beginning of season.
    adjustment_array_north = xarray.DataArray(
        [0, 0, 0, 0.1, 0.3, 0.5, 0.5, 0.5, 0.5, 0, 0, 0],
        dims="month",
        coords={"month": np.arange(1, 13)},
    )
    adjustment_array_south = xarray.DataArray(
        [0.5, 0.5, 0.5, 0, 0, 0, 0, 0, 0, 0.1, 0.3, 0.5],
        dims="month",
        coords={"month": np.arange(1, 13)},
    )

    has_north, has_south = False, False
    if lat is None:
        lat = _gather_lat(pr)
    if isinstance(lat, xarray.DataArray):
        if (lat >= 0).any():
            has_north = True
        if (lat < 0).any():
            has_south = True

        adjustment = xarray.where(
            lat >= 0,
            adjustment_array_north,
            adjustment_array_south,
        )
    elif isinstance(lat, str):
        if lat.lower() == "north":
            adjustment = adjustment_array_north
            has_north = True
        elif lat.lower() == "south":
            adjustment = adjustment_array_south
            has_south = True
        else:
            raise ValueError(f"Latitude value not implemented: {lat}.")
    else:
        raise ValueError("Latitude must be a DataArray or str ('north' or 'south').")

    # Monthly weights array
    k = adjustment.sel(month=evspsblpot.time.dt.month)

    # Drop all pr outside seasonal bounds
    pr_masked = (k > 0) * pr

    # Potential transpiration of the vineyard
    t_v = evspsblpot * k

    # Direct soil evaporation
    e_s = (
        (evspsblpot / evspsblpot.time.dt.daysinmonth)
        * (1 - k)
        * (pr_masked / 5).clip(max=evspsblpot.time.dt.daysinmonth)
    )

    di_north: xarray.DataArray | None = None
    di_south: xarray.DataArray | None = None
    # Dryness index
    if has_north:
        di_north = wo + (pr_masked - t_v - e_s).resample(time="YS-JAN").sum()
    if has_south:
        di_south = wo + (pr_masked - t_v - e_s).resample(time="YS-JUL").sum()
        # Shift time for Southern Hemisphere to allow for concatenation with Northern Hemisphere
        di_south = di_south.shift(time=1).isel(time=slice(1, None))
        di_south["time"] = di_south.indexes["time"].shift(-6, "MS")

    di: xarray.DataArray
    if has_north and has_south:
        di = di_north.where(lat >= 0, di_south)
    elif has_north:
        di = di_north  # noqa
    elif has_south:
        di = di_south  # noqa
    else:
        raise ValueError("No hemisphere data found.")

    di = di.assign_attrs(units="mm")
    return di


@declare_units(tas="[temperature]", lat="[]")
def latitude_temperature_index(
    tas: xarray.DataArray,
    lat: xarray.DataArray | None = None,
    lat_factor: float = 75,
    freq: str = "YS",
) -> xarray.DataArray:
    """
    Latitude-Temperature Index.

    Mean temperature of the warmest month with a latitude-based scaling factor :cite:p:`jackson_prediction_1988`.
    Used for categorizing wine-growing regions.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    lat : xarray.DataArray, optional
        Latitude coordinate.
        If None, a CF-conformant "latitude" field must be available within the passed DataArray.
    lat_factor : float
        Latitude factor. Maximum poleward latitude. Default: 75.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [unitless]
        Latitude Temperature Index.

    Notes
    -----
    The latitude factor of `75` is provided for examining the poleward expansion of wine-growing climates under
    scenarios of climate change :cite:p:`kenny_assessment_1992`. For comparing 20th century/observed historical
    records, the original scale factor of `60` is more appropriate :cite:p:`jackson_prediction_1988`.

    Let :math:`Tn_{j}` be the average temperature for a given month :math:`j`, :math:`lat_{f}` be the latitude factor,
    and :math:`lat` be the latitude of the area of interest. Then the Latitude-Temperature Index (:math:`LTI`) is:

    .. math::

       LTI = max(TN_{j}: j = 1..12)(lat_f - | lat | )

    References
    ----------
    :cite:cts:`jackson_prediction_1988,kenny_assessment_1992`
    """
    tas = convert_units_to(tas, "degC")

    tas = tas.resample(time="MS").mean(dim="time", keep_attrs=True)
    mtwm = tas.resample(time=freq).max(dim="time", keep_attrs=True)

    if lat is None:
        lat = _gather_lat(tas)

    lat_mask = (abs(lat) >= 0) & (abs(lat) <= lat_factor)
    lat_coeff = xarray.where(lat_mask, lat_factor - abs(lat), 0)

    lti: xarray.DataArray = mtwm * lat_coeff
    lti = lti.assign_attrs(units="")
    return lti


@declare_units(
    pr="[precipitation]",
    evspsblpot="[precipitation]",
    tasmin="[temperature]",
    tasmax="[temperature]",
    tas="[temperature]",
    lat="[]",
    hurs="[]",
    rsds="[radiation]",
    rsus="[radiation]",
    rlds="[radiation]",
    rlus="[radiation]",
    sfcWind="[speed]",
)
def water_budget(
    pr: xarray.DataArray,
    evspsblpot: xarray.DataArray | None = None,
    tasmin: xarray.DataArray | None = None,
    tasmax: xarray.DataArray | None = None,
    tas: xarray.DataArray | None = None,
    lat: xarray.DataArray | None = None,
    hurs: xarray.DataArray | None = None,
    rsds: xarray.DataArray | None = None,
    rsus: xarray.DataArray | None = None,
    rlds: xarray.DataArray | None = None,
    rlus: xarray.DataArray | None = None,
    sfcWind: xarray.DataArray | None = None,
    method: str = "BR65",
) -> xarray.DataArray:
    r"""
    Precipitation minus potential evapotranspiration.

    Precipitation minus potential evapotranspiration as a measure of an approximated surface water budget,
    where the potential evapotranspiration can be calculated with a given method.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    evspsblpot : xarray.DataArray, optional
        Potential evapotranspiration.
    tasmin : xarray.DataArray, optional
        Minimum daily temperature.
    tasmax : xarray.DataArray, optional
        Maximum daily temperature.
    tas : xarray.DataArray, optional
        Mean daily temperature.
    lat : xarray.DataArray, optional
        Latitude coordinate, needed if evspsblpot is not given.
        If None, a CF-conformant "latitude" field must be available within the `pr` DataArray.
    hurs : xarray.DataArray, optional
        Relative humidity.
    rsds : xarray.DataArray, optional
        Surface Downwelling Shortwave Radiation.
    rsus : xarray.DataArray, optional
        Surface Upwelling Shortwave Radiation.
    rlds : xarray.DataArray, optional
        Surface Downwelling Longwave Radiation.
    rlus : xarray.DataArray, optional
        Surface Upwelling Longwave Radiation.
    sfcWind : xarray.DataArray, optional
        Surface wind velocity (at 10 m).
    method : str
        Method to use to calculate the potential evapotranspiration.

    Returns
    -------
    xarray.DataArray
        Precipitation minus potential evapotranspiration.

    See Also
    --------
    xclim.indicators.atmos.potential_evapotranspiration : Potential evapotranspiration calculation.
    """
    pr = convert_units_to(pr, "kg m-2 s-1", context="hydro")

    if lat is None and evspsblpot is None:
        lat = _gather_lat(pr)

    if evspsblpot is None:
        pet = potential_evapotranspiration(
            tasmin=tasmin,
            tasmax=tasmax,
            tas=tas,
            lat=lat,
            hurs=hurs,
            rsds=rsds,
            rsus=rsus,
            rlds=rlds,
            rlus=rlus,
            sfcWind=sfcWind,
            method=method,
        )
    else:
        pet = convert_units_to(evspsblpot, "kg m-2 s-1", context="hydro")

    if xarray.infer_freq(pet.time) == "MS":
        pr = pr.resample(time="MS").mean(dim="time", keep_attrs=True)

    out: xarray.DataArray = pr - pet
    out = out.assign_attrs(units=pr.attrs["units"])
    return out


@declare_units(
    pr="[precipitation]",
    thresh_wet_start="[length]",
    thresh_dry_start="[length]",
    thresh_dry_end="[length]",
)
def rain_season(
    pr: xarray.DataArray,
    thresh_wet_start: Quantified = "25.0 mm",
    window_wet_start: int = 3,
    window_not_dry_start: int = 30,
    thresh_dry_start: Quantified = "1.0 mm",
    window_dry_start: int = 7,
    method_dry_start: str = "per_day",
    date_min_start: DayOfYearStr = "05-01",
    date_max_start: DayOfYearStr = "12-31",
    thresh_dry_end: Quantified = "0.0 mm",
    window_dry_end: int = 20,
    method_dry_end: str = "per_day",
    date_min_end: DayOfYearStr = "09-01",
    date_max_end: DayOfYearStr = "12-31",
    freq="YS-JAN",
) -> tuple[xarray.DataArray, xarray.DataArray, xarray.DataArray]:
    """
    Find the length of the rain season and the day of year of its start and its end.

    The rain season begins when two conditions are met: 1) There must be a number of wet days with precipitations above
    or equal to a given threshold; 2) There must be another sequence following, where, for a given period in time, there
    are no dry sequence (i.e. a certain number of days where precipitations are below or equal to a certain threshold).
    The rain season ends when there is a dry sequence.

    Parameters
    ----------
    pr : xr.DataArray
        Precipitation data.
    thresh_wet_start : Quantified
        Accumulated precipitation threshold associated with `window_wet_start`.
    window_wet_start : int
        Number of days when accumulated precipitation is above `thresh_wet_start`.
        Defines the first condition to start the rain season.
    window_not_dry_start : int
        Number of days, after `window_wet_start` days, during which no dry period must be found as a second and last
        condition to start the rain season.
        A dry sequence is defined with `thresh_dry_start`, `window_dry_start` and `method_dry_start`.
    thresh_dry_start : Quantified
        Threshold length defining a dry day in the sequence related to `window_dry_start`.
    window_dry_start : int
        Number of days used to define a dry sequence in the start of the season.
        Daily precipitations lower than `thresh_dry_start` during `window_dry_start` days are considered a dry sequence.
        The precipitations must be lower than `thresh_dry_start` for either every day in the sequence
        (`method_dry_start == "per_day"`) or for the total (`method_dry_start == "total"`).
    method_dry_start : {"per_day", "total"}
        Method used to define a dry sequence associated with `window_dry_start`.
        The threshold `thresh_dry_start` is either compared to every daily precipitation
        (`method_dry_start == "per_day"`) or to total precipitations (`method_dry_start == "total"`) in the sequence
        `window_dry_start` days.
    date_min_start : DayOfYearStr
        First day of year when season can start ("mm-dd").
    date_max_start : DayOfYearStr
        Last day of year when season can start ("mm-dd").
    thresh_dry_end : str
        Threshold length defining a dry day in the sequence related to `window_dry_end`.
    window_dry_end : int
        Number of days used to define a dry sequence in the end of the season.
        Daily precipitations lower than `thresh_dry_end` during `window_dry_end` days are considered a dry sequence.
        The precipitations must be lower than `thresh_dry_end` for either every day in the sequence
        (`method_dry_end == "per_day"`) or for the total (`method_dry_end == "total"`).
    method_dry_end : {"per_day", "total"}
        Method used to define a dry sequence associated with `window_dry_end`.
        The threshold `thresh_dry_end` is either compared to every daily precipitation (`method_dry_end == "per_day"`)
        or to total precipitations (`method_dry_end == "total"`) in the sequence `window_dry` days.
    date_min_end : DayOfYearStr
        First day of year when season can end ("mm-dd").
    date_max_end : DayOfYearStr
        Last day of year when season can end ("mm-dd").
    freq : str
      Resampling frequency.

    Returns
    -------
    rain_season_start: xr.DataArray, [dimensionless]
        The beginning of the rain season.
    rain_season_end: xr.DataArray, [dimensionless]
        The end of the rain season.
    rain_season_length: xr.DataArray, [time]
        The length of the rain season.

    Notes
    -----
    The rain season starts at the end of a period of raining (a total precipitation  of `thresh_wet_start` over
    `window_wet_start` days). This must be directly followed by a period of `window_not_dry_start` days with no dry
    sequence. The dry sequence is a period of `window_dry_start` days where precipitations are below `thresh_dry_start`
    (either the total precipitations over the period, or the daily precipitations, depending on `method_dry_start`).
    The rain season stops when a dry sequence happens (the dry sequence is defined as in the start sequence, but with
    parameters `window_dry_end`, `thresh_dry_end` and `method_dry_end`). The dates on which the season can start are
    constrained by `date_min_start`and `date_max_start` (and similarly for the end of the season).

    References
    ----------
    :cite:cts:`sivakumar_predicting_1998`
    """
    # Unit conversion.
    pram = rate2amount(pr, out_units="mm")
    thresh_wet_start = convert_units_to(thresh_wet_start, pram)
    thresh_dry_start = convert_units_to(thresh_dry_start, pram)
    thresh_dry_end = convert_units_to(thresh_dry_end, pram)

    # should we flag date_min_end  < date_max_start?
    def _get_first_run(run_positions, start_date, end_date):
        run_positions = select_time(run_positions, date_bounds=(start_date, end_date))
        first_start = run_positions.argmax("time")
        return xarray.where(first_start != run_positions.argmin("time"), first_start, np.nan)

    # Find the start of the rain season
    def _get_first_run_start(_pram):
        last_doy = _pram.indexes["time"][-1].strftime("%m-%d")
        _pram = select_time(_pram, date_bounds=(date_min_start, last_doy))

        # First condition: Start with enough precipitation
        da_start = _pram.rolling({"time": window_wet_start}).sum() >= thresh_wet_start

        # Second condition: No dry period after
        if method_dry_start == "per_day":
            da_stop = _pram <= thresh_dry_start
            window_dry = window_dry_start
        elif method_dry_start == "total":
            da_stop = _pram.rolling({"time": window_dry_start}).sum() <= thresh_dry_start
            # equivalent to rolling forward in time instead, i.e. end date will be at beginning of dry run
            da_stop = da_stop.shift({"time": -(window_dry_start - 1)}, fill_value=False)
            window_dry = 1
        else:
            raise ValueError(f"Unknown method_dry_start: {method_dry_start}.")

        # First and second condition combined in a run length
        events = rl.runs_with_holes(da_start, 1, da_stop, window_dry)
        run_positions = rl.rle(events) >= (window_not_dry_start + window_wet_start)

        return _get_first_run(run_positions, date_min_start, date_max_start)

    # Find the end of the rain season
    # FIXME: This function mixes local and parent-level variables. It should be refactored.
    def _get_first_run_end(_pram):
        if method_dry_end == "per_day":
            da_stop = _pram <= thresh_dry_end
            run_positions = rl.rle(da_stop) >= window_dry_end
        elif method_dry_end == "total":
            run_positions = _pram.rolling({"time": window_dry_end}).sum() <= thresh_dry_end
        else:
            raise ValueError(f"Unknown method_dry_end: {method_dry_end}.")
        return _get_first_run(run_positions, date_min_end, date_max_end)

    # Get start, end and length of rain season. Written as a function so it can be resampled
    # FIXME: This function mixes local and parent-level variables. It should be refactored.
    def _get_rain_season(_pram):
        start = _get_first_run_start(_pram)

        # masking value before  start of the season (end of season should be after)
        # Get valid integer indexer of the day after the first run starts.
        # `start != NaN` only possible if a condition on next few time steps is respected.
        # Thus, `start+1` exists if `start != NaN`
        start_ind = (start + 1).fillna(-1).astype(int)
        mask = _pram * np.nan
        # Put "True" on the day of run start
        mask[{"time": start_ind}] = 1
        # Mask back points without runs, propagate the True
        mask = mask.where(start.notnull()).ffill("time")
        mask = mask.notnull()
        end = _get_first_run_end(_pram.where(mask))

        length = xarray.where(end.notnull(), end - start, _pram["time"].size - start)

        # converting to doy
        crd = _pram.time.dt.dayofyear
        start = rl.lazy_indexing(crd, start)
        end = rl.lazy_indexing(crd, end)

        _out = xarray.Dataset(
            {
                "rain_season_start": start,
                "rain_season_end": end,
                "rain_season_length": length,
            }
        )
        return _out

    # Compute rain season, attribute units
    out = cast(xarray.Dataset, pram.resample(time=freq).map(_get_rain_season))
    rain_season_start = out.rain_season_start.assign_attrs(units="", is_dayofyear=np.int32(1))
    rain_season_end = out.rain_season_end.assign_attrs(units="", is_dayofyear=np.int32(1))
    rain_season_length = out.rain_season_length.assign_attrs(units="days")
    return rain_season_start, rain_season_end, rain_season_length


@declare_units(
    pr="[precipitation]",
    params="[]",
)
def standardized_precipitation_index(
    pr: xarray.DataArray,
    freq: str | None = "MS",
    window: int = 1,
    dist: str | rv_continuous = "gamma",
    method: str = "ML",
    fitkwargs: dict | None = None,
    cal_start: DateStr | None = None,
    cal_end: DateStr | None = None,
    params: Quantified | None = None,
    **indexer,
) -> xarray.DataArray:
    r"""
    Standardized Precipitation Index (SPI).

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    freq : str, optional
        Resampling frequency. A monthly or daily frequency is expected. Option `None` assumes
        that the desired resampling has already been applied input dataset and will skip the resampling step.
    window : int
        Averaging window length relative to the resampling frequency. For example, if `freq="MS"`,
        i.e. a monthly resampling, the window is an integer number of months.
    dist : {'gamma', 'fisk'} or `rv_continuous` function
        Name of the univariate distribution, or a callable `rv_continuous` (see :py:mod:`scipy.stats`).
    method : {"APP", "ML", "PWM"}
        Name of the fitting method, such as `ML` (maximum likelihood), `APP` (approximate). The approximate method
        uses a deterministic function that does not involve any optimization. `PWM` should be used with a `lmoments3` distribution.
    fitkwargs : dict, optional
        Kwargs passed to ``xclim.indices.stats.fit`` used to impose values of certains parameters (`floc`, `fscale`).
        If method is `PWM`, `fitkwargs` should be empty, except for `floc` with `dist`=`gamma` which is allowed.
    cal_start : DateStr, optional
        Start date of the calibration period. A `DateStr` is expected, that is a `str` in format `"YYYY-MM-DD"`.
        Default option `None` means that the calibration period begins at the start of the input dataset.
    cal_end : DateStr, optional
        End date of the calibration period. A `DateStr` is expected, that is a `str` in format `"YYYY-MM-DD"`.
        Default option `None` means that the calibration period finishes at the end of the input dataset.
    params : xarray.DataArray
        Fit parameters.
        The `params` can be computed using ``xclim.indices.stats.standardized_index_fit_params`` in advance.
        The output can be given here as input, and it overrides other options.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.

    Returns
    -------
    xarray.DataArray, [unitless]
        Standardized Precipitation Index.

    See Also
    --------
    xclim.indices.stats.standardized_index : Standardized Index.
    xclim.indices.stats.standardized_index_fit_params : Standardized Index Fit Params.

    Notes
    -----
    * N-month SPI / N-day SPI is determined by choosing the `window = N` and the appropriate frequency `freq`.
    * Supported statistical distributions are: ["gamma", "fisk"], where "fisk" is scipy's implementation of
      a log-logistic distribution
    * Supported frequencies are daily ("D"), weekly ("W"), and monthly ("MS").
    * Weekly frequency will only work if the input array has a "standard" (non-cftime) calendar.
    * If `params` is given as input, it overrides the `cal_start`, `cal_end`, `freq` and `window`, `dist` and `method` options.
    * "APP" method only supports two-parameter distributions. Parameter `loc` needs to be fixed to use method `APP`.
    * The results from `climate_indices` library can be reproduced with `method = "APP"` and `fitwkargs = {"floc": 0}`, except for the maximum
      and minimum values allowed which are greater in xclim ±8.21, . See `xclim.indices.stats.standardized_index`

    References
    ----------
    :cite:cts:`mckee_relationship_1993`

    Examples
    --------
    >>> from datetime import datetime
    >>> from xclim.indices import standardized_precipitation_index
    >>> ds = xr.open_dataset(path_to_pr_file)
    >>> pr = ds.pr
    >>> cal_start, cal_end = "1990-05-01", "1990-08-31"
    >>> spi_3 = standardized_precipitation_index(
    ...     pr,
    ...     freq="MS",
    ...     window=3,
    ...     dist="gamma",
    ...     method="ML",
    ...     cal_start=cal_start,
    ...     cal_end=cal_end,
    ... )  # Computing SPI-3 months using a gamma distribution for the fit
    >>> # Fitting parameters can also be obtained first, then reused as input.
    >>> # To properly reproduce the example, we also need to specify that we use a
    >>> # (potentially) zero-inflated distribution. For a monthly SPI, this should rarely
    >>> # make a difference.
    >>> from xclim.indices.stats import standardized_index_fit_params
    >>> params = standardized_index_fit_params(
    ...     pr.sel(time=slice(cal_start, cal_end)),
    ...     freq="MS",
    ...     window=3,
    ...     dist="gamma",
    ...     method="ML",
    ...     zero_inflated=True,
    ... )  # First getting params
    >>> spi_3_fitted = standardized_precipitation_index(pr, params=params)
    """
    fitkwargs = fitkwargs or {}

    dist_methods = {"gamma": ["ML", "APP"], "fisk": ["ML", "APP"]}
    if isinstance(dist, str):
        if dist in dist_methods:
            if method not in dist_methods[dist]:
                raise NotImplementedError(f"{method} method is not implemented for {dist} distribution")
        else:
            raise NotImplementedError(f"{dist} distribution is not yet implemented.")

    # Precipitation is expected to be zero-inflated
    zero_inflated = True
    spi = standardized_index(
        pr,
        freq=freq,
        window=window,
        dist=dist,
        method=method,
        zero_inflated=zero_inflated,
        fitkwargs=fitkwargs,
        cal_start=cal_start,
        cal_end=cal_end,
        params=params,
        **indexer,
    )

    return spi


@declare_units(
    wb="[precipitation]",
    params="[]",
)
def standardized_precipitation_evapotranspiration_index(
    wb: xarray.DataArray,
    freq: str | None = "MS",
    window: int = 1,
    dist: str | rv_continuous = "gamma",
    method: str = "ML",
    fitkwargs: dict | None = None,
    cal_start: DateStr | None = None,
    cal_end: DateStr | None = None,
    params: Quantified | None = None,
    **indexer,
) -> xarray.DataArray:
    r"""
    Standardized Precipitation Evapotranspiration Index (SPEI).

    Precipitation minus potential evapotranspiration data (PET) fitted to a statistical distribution (dist), transformed
    to a cdf,  and inverted back to a gaussian normal pdf. The potential evapotranspiration is calculated with a given
    method (`method`).

    Parameters
    ----------
    wb : xarray.DataArray
        Daily water budget (pr - pet).
    freq : str, optional
        Resampling frequency. A monthly or daily frequency is expected. Option `None` assumes
        that the desired resampling has already been applied input dataset and will skip the resampling step.
    window : int
        Averaging window length relative to the resampling frequency. For example, if `freq="MS"`, i.e. a monthly
        resampling, the window is an integer number of months.
    dist : {'gamma', 'fisk'} or `rv_continuous` function
        Name of the univariate distribution, or a callable `rv_continuous` (see :py:mod:`scipy.stats`).
    method : {"APP", "ML", "PWM"}
        Name of the fitting method, such as `ML` (maximum likelihood), `APP` (approximate). The approximate method
        uses a deterministic function that does not involve any optimization. `PWM` should be used with a `lmoments3` distribution.
    fitkwargs : dict, optional
        Kwargs passed to ``xclim.indices.stats.fit`` used to impose values of certains parameters (`floc`, `fscale`).
        If method is `PWM`, `fitkwargs` should be empty, except for `floc` with `dist`=`gamma` which is allowed.
    cal_start : DateStr, optional
        Start date of the calibration period. A `DateStr` is expected, that is a `str` in format `"YYYY-MM-DD"`.
        Default option `None` means that the calibration period begins at the start of the input dataset.
    cal_end : DateStr, optional
        End date of the calibration period. A `DateStr` is expected, that is a `str` in format `"YYYY-MM-DD"`.
        Default option `None` means that the calibration period finishes at the end of the input dataset.
    params : xarray.DataArray, optional
        Fit parameters.
        The `params` can be computed using ``xclim.indices.stats.standardized_index_fit_params`` in advance.
        The output can be given here as input, and it overrides other options.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.

    Returns
    -------
    xarray.DataArray
        Standardized Precipitation Evapotranspiration Index.

    See Also
    --------
    standardized_precipitation_index : Standardized Precipitation Index.
    xclim.indices.stats.standardized_index : Standardized Index.
    xclim.indices.stats.standardized_index_fit_params : Standardized Index Fit Params.
    """
    fitkwargs = fitkwargs or {}

    dist_methods = {"gamma": ["ML", "APP"], "fisk": ["ML", "APP"]}
    if isinstance(dist, str):
        if dist in dist_methods:
            if method not in dist_methods[dist]:
                raise NotImplementedError(f"{method} method is not implemented for {dist} distribution")
        else:
            raise NotImplementedError(f"{dist} distribution is not yet implemented.")

    # Water budget is not expected to be zero-inflated
    zero_inflated = False
    spei = standardized_index(
        wb,
        freq=freq,
        window=window,
        dist=dist,
        method=method,
        zero_inflated=zero_inflated,
        fitkwargs=fitkwargs,
        cal_start=cal_start,
        cal_end=cal_end,
        params=params,
        **indexer,
    )

    return spei


@declare_units(tas="[temperature]")
def qian_weighted_mean_average(tas: xarray.DataArray, dim: str = "time") -> xarray.DataArray:
    r"""
    Binomial smoothed, five-day weighted mean average temperature.

    Calculates a five-day weighted moving average with emphasis on temperatures closer to day of interest.

    Parameters
    ----------
    tas : xr.DataArray
        Daily mean temperature.
    dim : str
        Time dimension.

    Returns
    -------
    xr.DataArray, [same as tas]
        Binomial smoothed, five-day weighted mean average temperature.

    Notes
    -----
    Qian Modified Weighted Mean Indice originally proposed in :cite:p:`qian_observed_2010`,
    based on :cite:p:`bootsma_impacts_2005`.

    Let :math:`X_{n}` be the average temperature for day :math:`n` and :math:`X_{t}` be the daily mean temperature
    on day :math:`t`. Then the weighted mean average can be calculated as follows:

    .. math::

       \overline{X}_{n} = \frac{X_{n-2} + 4X_{n-1} + 6X_{n} + 4X_{n+1} + X_{n+2}}{16}

    References
    ----------
    :cite:cts:`bootsma_impacts_2005,qian_observed_2010`
    """
    units = tas.attrs["units"]

    weights = xarray.DataArray([0.0625, 0.25, 0.375, 0.25, 0.0625], dims=["window"])
    weighted_mean: xarray.DataArray = tas.rolling({dim: 5}, center=True).construct("window").dot(weights)
    weighted_mean = weighted_mean.assign_attrs(units=units)
    return weighted_mean


@declare_units(
    tasmax="[temperature]",
    tasmin="[temperature]",
    thresh="[temperature]",
)
def effective_growing_degree_days(
    tasmax: xarray.DataArray,
    tasmin: xarray.DataArray,
    *,
    thresh: Quantified = "5 degC",
    method: str = "bootsma",
    after_date: DayOfYearStr = "07-01",
    dim: str = "time",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Effective growing degree days.

    Growing degree days based on a dynamic start and end of the growing season,
    as defined in :cite:p:`bootsma_impacts_2005`.

    Parameters
    ----------
    tasmax : xr.DataArray
        Daily mean temperature.
    tasmin : xr.DataArray
        Daily minimum temperature.
    thresh : Quantified
        The minimum temperature threshold.
    method : {"bootsma", "qian"}
        The window method used to determine the temperature-based start date.
        For "bootsma", the start date is defined as 10 days after the average temperature exceeds a threshold.
        For "qian", the start date is based on a weighted 5-day rolling average,
        based on :py:func`qian_weighted_mean_average`.
    after_date : str
        Date of the year after which to look for the first frost event. Should have the format '%m-%d'.
    dim : str
        Time dimension.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [K days]
        Effective growing degree days (EGDD).

    Notes
    -----
    The effective growing degree days for a given year :math:`EGDD_i` can be calculated as follows:

    .. math::

       EGDD_i = \sum_{i=\text{j_{start}}^{\text{j_{end}}} max\left(TG - Thresh, 0 \right)

    Where :math:`TG` is the mean daly temperature, and :math:`j_{start}` and :math:`j_{end}` are the start and end dates
    of the growing season. The growing season start date methodology is determined via the `method` flag.
    For "bootsma", the start date is defined as 10 days after the average temperature exceeds a threshold (5 degC).
    For "qian", the start date is based on a weighted 5-day rolling average, based on :py:func:`qian_weighted_mean_average`.

    The end date is determined as the day preceding the first day with minimum temperature below 0 degC.

    References
    ----------
    :cite:cts:`bootsma_impacts_2005`
    """
    tasmax = convert_units_to(tasmax, "degC")
    tasmin = convert_units_to(tasmin, "degC")
    thresh = convert_units_to(thresh, "degC")
    thresh_with_units = f"{thresh} degC"

    tas = (tasmin + tasmax) / 2
    tas.attrs["units"] = "degC"

    if method.lower() == "bootsma":
        fda = first_day_temperature_above(tas=tas, thresh=thresh_with_units, window=1, freq=freq)
        start = fda + 10
    elif method.lower() == "qian":
        tas_weighted = qian_weighted_mean_average(tas=tas, dim=dim)
        start = first_day_temperature_above(tas_weighted, thresh=thresh_with_units, window=5, freq=freq)
    else:
        raise NotImplementedError(f"Method: {method}.")

    # The day before the first day below 0 degC
    end = (
        first_day_temperature_below(
            tasmin,
            thresh="0 degC",
            after_date=after_date,
            window=1,
            freq=freq,
        )
        - 1
    )

    deg_days = (tas - thresh).clip(min=0)
    egdd: xarray.DataArray = aggregate_between_dates(deg_days, start=start, end=end, freq=freq)
    egdd = to_agg_units(egdd, tas, op="integral", deffreq="D")
    return egdd


@declare_units(tasmin="[temperature]")
def hardiness_zones(  # numpydoc ignore=SS05
    tasmin: xarray.DataArray, window: int = 30, method: str = "usda", freq: str = "YS"
):
    """
    Hardiness zones.

    Hardiness zones are a categorization of the annual extreme temperature minima, averaged over a certain period.
    The USDA method defines 14 zones, each divided into two sub-zones, using steps of 5°F, starting at -60°F.
    The Australian National Botanic Gardens method defines 7 zones, using steps of 5°C, starting at -15°C.

    Parameters
    ----------
    tasmin : xr.DataArray
        Minimum temperature.
    window : int
        The length of the averaging window, in years.
    method : {"usda", "anbg"}
        Whether to return the American (`usda`) or the Australian (`anbg`) classification zones.
    freq : str
        Resampling frequency.

    Returns
    -------
    xr.DataArray, [dimensionless]
        {method} hardiness zones.
        US sub-zones are denoted by using a half step. For example, Zone 4b is given as 4.5.
        Values are given at the end of the averaging window.

    References
    ----------
    :cite:cts:`usda_2012,dawson_plant_1991`
    """
    if method.lower() == "usda":
        zone_min, zone_max, zone_step = "-60 degF", "70 degF", "5 degF"

    elif method.lower() == "anbg":
        zone_min, zone_max, zone_step = "-15 degC", "20 degC", "5 degC"

    else:
        raise NotImplementedError(f"Method must be one of `usda` or `anbg`. Got {method}.")

    tn_min_rolling = tn_min(tasmin, freq=freq).rolling(time=window).mean()
    zones: xarray.DataArray = get_zones(tn_min_rolling, zone_min=zone_min, zone_max=zone_max, zone_step=zone_step)

    zones = zones.assign_attrs(units="")
    return zones


def _accumulate_intermediate(prev_E, prev_xi, curr_xs, curr_ak1):
    """Accumulate the intermediate product based on the previous concentration and the current temperature."""
    curr_S = np.where(prev_E < 1, prev_E, prev_E - prev_E * prev_xi)
    return curr_xs - (curr_xs - curr_S) * np.exp(-curr_ak1)


def _chill_portion_one_season(tas_K):
    """Computes the chill portion for a single season based on the dynamic model on a numpy array."""
    # Constants as described in Luedeling et al. (2009)
    E0 = 4153.5
    E1 = 12888.8
    A0 = 139500
    A1 = 2.567e18
    SLP = 1.6
    TETMLT = 277
    AA = A0 / A1
    EE = E1 - E0

    ftmprt = SLP * TETMLT * (tas_K - TETMLT) / tas_K
    sr = np.exp(ftmprt)
    xi = sr / (1 + sr)
    xs = AA * np.exp(EE / tas_K)
    ak1 = A1 * np.exp(-E1 / tas_K)

    inter_E = np.zeros_like(tas_K)
    for i in range(1, tas_K.shape[-1]):
        inter_E[..., i] = _accumulate_intermediate(inter_E[..., i - 1], xi[..., i - 1], xs[..., i], ak1[..., i])
    delta = np.where(inter_E >= 1, inter_E * xi, 0)

    return delta


def _apply_chill_portion_one_season(tas_K):
    """Apply the chill portion function on to an xarray DataArray."""
    if uses_dask(tas_K):
        tas_K = tas_K.chunk(time=-1)
    return xarray.apply_ufunc(
        _chill_portion_one_season,
        tas_K,
        input_core_dims=[["time"]],
        output_core_dims=[["time"]],
        output_dtypes=[tas_K.dtype],
        dask="parallelized",
    ).sum("time")


@declare_units(tas="[temperature]")
def chill_portions(tas: xarray.DataArray, freq: str = "YS", **indexer) -> xarray.DataArray:
    r"""
    Chill portion based on the dynamic model.

    Chill portions are a measure to estimate the bud breaking potential of different crop.
    The constants and functions are taken from Luedeling et al. (2009) which formalises the method described in
    Fishman et al. (1987). The model computes the accumulation of an intermediate product that is transformed to
    the final product once it exceeds a certain concentration. The intermediate product can be broken down at higher
    temperatures but the final product is stable even at higher temperature. Thus, the dynamic model is more accurate
    than the Utah model especially in moderate climates like Israel, California, or Spain.

    Parameters
    ----------
    tas : xr.DataArray
        Hourly temperature.
    freq : str
        Resampling frequency.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.

    Returns
    -------
    xr.DataArray, [unitless]
        Chill portions after the Dynamic Model.

    Notes
    -----
    Typically, this indicator is computed for a period of the year. You can use the `**indexer` arguments
    of `select_time` in combination with the `freq` argument to select e.g. a winter period:

    .. code-block:: python

        cp = chill_portions(tas, date_bounds=("09-01", "03-30"), freq="YS-JUL")

    Note that incomplete periods will lead to NaNs.

    References
    ----------
    :cite:cts:`fishman_chill_1987,luedeling_chill_2009`

    Examples
    --------
    >>> from xclim.indices import chill_portions
    >>> from xclim.indices.helpers import make_hourly_temperature
    >>> tasmin = xr.open_dataset(path_to_tasmin_file).tasmin
    >>> tasmax = xr.open_dataset(path_to_tasmax_file).tasmax
    >>> tas_hourly = make_hourly_temperature(tasmin, tasmax)
    >>> cp = chill_portions(tasmin)
    """
    tas_K: xarray.DataArray = select_time(convert_units_to(tas, "K"), drop=True, **indexer)
    return resample_map(tas_K, "time", freq, _apply_chill_portion_one_season).assign_attrs(units="")


@declare_units(tas="[temperature]")
def chill_units(tas: xarray.DataArray, positive_only: bool = False, freq: str = "YS") -> xarray.DataArray:
    """
    Chill units using the Utah model.

    Chill units are a measure to estimate the bud breaking potential of different crop based on Richardson et al. (1974).
    The Utah model assigns a weight to each hour depending on the temperature recognising that high temperatures can actual decrease,
    the potential for bud breaking. Providing `positive_only=True` will ignore days with negative chill units.

    Parameters
    ----------
    tas : xr.DataArray
        Hourly temperature.
    positive_only : bool
        If `True`, only positive daily chill units are aggregated.
    freq : str
        Resampling frequency.

    Returns
    -------
    xr.DataArray, [unitless]
        Chill units using the Utah model.

    References
    ----------
    :cite:cts:`richardson_chill_1974`

    Examples
    --------
    >>> from xclim.indices import chill_units
    >>> from xclim.indices.helpers import make_hourly_temperature
    >>> tasmin = xr.open_dataset(path_to_tasmin_file).tasmin
    >>> tasmax = xr.open_dataset(path_to_tasmax_file).tasmax
    >>> tas_hourly = make_hourly_temperature(tasmin, tasmax)
    >>> cu = chill_units(tasmin)
    """
    tas = convert_units_to(tas, "degC")
    cu = xarray.where(
        (tas <= 1.4) | ((tas > 12.4) & (tas <= 15.9)),
        0,
        xarray.where(
            ((tas > 1.4) & (tas <= 2.4)) | ((tas > 9.1) & (tas <= 12.4)),
            0.5,
            xarray.where(
                (tas > 2.4) & (tas <= 9.1),
                1,
                xarray.where((tas > 15.9) & (tas <= 17.9), -0.5, -1),
            ),
        ),
    )
    cu = cu.where(tas.notnull())

    if positive_only:
        daily = cu.resample(time="1D").sum()
        cu = daily.where(daily > 0)
    return cu.resample(time=freq).sum().assign_attrs(units="")
