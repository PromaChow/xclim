"""Threshold indice definitions."""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import xarray

from xclim.core import DayOfYearStr, Quantified
from xclim.core.calendar import doy_from_string, get_calendar, select_time
from xclim.core.missing import at_least_n_valid
from xclim.core.units import (
    convert_units_to,
    declare_units,
    pint2cfunits,
    rate2amount,
    str2pint,
    to_agg_units,
    units2pint,
)
from xclim.core.utils import deprecated
from xclim.indices import run_length as rl
from xclim.indices.generic import (
    bivariate_count_occurrences,
    compare,
    count_occurrences,
    cumulative_difference,
    domain_count,
    first_day_threshold_reached,
    season,
    spell_length_statistics,
    threshold_count,
)
from xclim.indices.helpers import resample_map

# Frequencies : YS: year start, QS-DEC: seasons starting in december, MS: month start
# See http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases

# -------------------------------------------------- #
# ATTENTION: ASSUME ALL INDICES WRONG UNTIL TESTED ! #
# -------------------------------------------------- #

__all__ = [
    "calm_days",
    "cold_spell_days",
    "cold_spell_frequency",
    "cold_spell_max_length",
    "cold_spell_total_length",
    "cooling_degree_days",
    "cooling_degree_days_approximation",
    "daily_pr_intensity",
    "days_with_snow",
    "degree_days_exceedance_date",
    "dry_days",
    "dry_spell_frequency",
    "dry_spell_max_length",
    "dry_spell_total_length",
    "first_day_temperature_above",
    "first_day_temperature_below",
    "first_snowfall",
    "frost_free_season_end",
    "frost_free_season_length",
    "frost_free_season_start",
    "frost_free_spell_max_length",
    "frost_season_length",
    "growing_degree_days",
    "growing_season_end",
    "growing_season_length",
    "growing_season_start",
    "heat_wave_index",
    "heating_degree_days",
    "heating_degree_days_approximation",
    "holiday_snow_and_snowfall_days",
    "holiday_snow_days",
    "hot_spell_frequency",
    "hot_spell_max_length",
    "hot_spell_max_magnitude",
    "hot_spell_total_length",
    "last_snowfall",
    "last_spring_frost",
    "maximum_consecutive_dry_days",
    "maximum_consecutive_frost_days",
    "maximum_consecutive_frost_free_days",
    "maximum_consecutive_tx_days",
    "maximum_consecutive_wet_days",
    "rprctot",
    "sea_ice_area",
    "sea_ice_extent",
    "snd_days_above",
    "snd_season_end",
    "snd_season_length",
    "snd_season_start",
    "snd_storm_days",
    "snowfall_frequency",
    "snowfall_intensity",
    "snw_days_above",
    "snw_season_end",
    "snw_season_length",
    "snw_season_start",
    "snw_storm_days",
    "tg_days_above",
    "tg_days_below",
    "tn_days_above",
    "tn_days_below",
    "tx_days_above",
    "tx_days_below",
    "warm_day_frequency",
    "warm_night_frequency",
    "wet_spell_frequency",
    "wet_spell_max_length",
    "wet_spell_total_length",
    "wetdays",
    "wetdays_prop",
    "windy_days",
]


@declare_units(sfcWind="[speed]", thresh="[speed]")
def calm_days(sfcWind: xarray.DataArray, thresh: Quantified = "2 m s-1", freq: str = "MS") -> xarray.DataArray:
    r"""
    Calm days.

    The number of days with average near-surface wind speed below threshold (default: 2 m/s).

    Parameters
    ----------
    sfcWind : xarray.DataArray
        Daily windspeed.
    thresh : Quantified
        Threshold average near-surface wind speed on which to base evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time]
        Number of days with average near-surface wind speed below the threshold.

    Notes
    -----
    Let :math:`WS_{ij}` be the windspeed at day :math:`i` of period :math:`j`.
    Then counted is the number of days where:

    .. math::

       WS_{ij} < Threshold [m s-1]
    """
    thresh = convert_units_to(thresh, sfcWind)
    out = threshold_count(sfcWind, "<", thresh, freq)
    out = to_agg_units(out, sfcWind, "count", deffreq="D")
    return out


@declare_units(tas="[temperature]", thresh="[temperature]")
def cold_spell_days(
    tas: xarray.DataArray,
    thresh: Quantified = "-10 degC",
    window: int = 5,
    freq: str = "YS-JUL",
    op: Literal["<", "lt", "<=", "le"] = "<",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Cold spell days.

    The number of days that are part of cold spell events, defined as a sequence of consecutive days with mean daily
    temperature below a threshold (default: -10°C).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature below which a cold spell begins.
    window : int
        Minimum number of days with temperature below the threshold to qualify as a cold spell.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        Cold spell days.

    Notes
    -----
    Let :math:`T_i` be the mean daily temperature on day :math:`i`, the number of cold spell days during
    period :math:`\phi` is given by:

    .. math::

       \sum_{i \in \phi} \prod_{j=i}^{i+5} [T_j < thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false.
    """
    t = convert_units_to(thresh, tas)
    over = compare(tas, op, t, constrain=("<", "<="))

    out = rl.resample_and_rl(
        over,
        resample_before_rl,
        rl.windowed_run_count,
        window=window,
        freq=freq,
    )
    return to_agg_units(out, tas, "count", deffreq="D")


@declare_units(tas="[temperature]", thresh="[temperature]")
def cold_spell_frequency(
    tas: xarray.DataArray,
    thresh: Quantified = "-10 degC",
    window: int = 5,
    freq: str = "YS-JUL",
    op: Literal["<", "lt", "<=", "le"] = "<",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Cold spell frequency.

    The number of cold spell events, defined as a sequence of consecutive {window} days with mean daily
    temperature below a {thresh}.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature below which a cold spell begins.
    window : int
        Minimum number of days with temperature below the threshold to qualify as a cold spell.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run.

    Returns
    -------
    xarray.DataArray, [unitless]
        The {freq} number of cold periods of minimum {window} days.
    """
    t = convert_units_to(thresh, tas)
    over = compare(tas, op, t, constrain=("<", "<="))

    out = rl.resample_and_rl(
        over,
        resample_before_rl,
        rl.windowed_run_events,
        window=window,
        freq=freq,
    )
    out.attrs["units"] = ""
    return out


@declare_units(tas="[temperature]", thresh="[temperature]")
def cold_spell_max_length(
    tas: xarray.DataArray,
    thresh: Quantified = "-10 degC",
    window: int = 1,
    freq: str = "YS-JUL",
    op: Literal["<", "lt", "<=", "le"] = "<",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Longest cold spell.

    Longest spell of low temperatures over a given period.
    Longest series of at least {window} consecutive days with temperature at or below {thresh}.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        The temperature threshold needed to trigger a cold spell.
    window : int
        Minimum number of days with temperatures below the threshold to qualify as a cold spell.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} longest spell in cold periods of minimum {window} days.
    """
    thresh = convert_units_to(thresh, tas)

    cond = compare(tas, op, thresh, constrain=("<", "<="))
    max_l = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.longest_run,
        freq=freq,
    )
    max_window = max_l.where(max_l >= window, 0)
    out = to_agg_units(max_window, tas, "count", deffreq="D")
    return out


@declare_units(tas="[temperature]", thresh="[temperature]")
def cold_spell_total_length(
    tas: xarray.DataArray,
    thresh: Quantified = "-10 degC",
    window: int = 3,
    freq: str = "YS-JUL",
    op: Literal["<", "lt", "<=", "le"] = "<",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Total length of cold spells.

    Total length of spells of low temperatures over a given period.
    Total length of series of at least {window} consecutive days with temperature at or below {thresh}.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        The temperature threshold needed to trigger a cold spell.
    window : int
        Minimum number of days with temperatures below the threshold to qualify as a cold spell.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} total number of days in cold periods of minimum {window} days.
    """
    thresh = convert_units_to(thresh, tas)

    cond = compare(tas, op, thresh, constrain=("<", "<="))
    out = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.windowed_run_count,
        window=window,
        freq=freq,
    )
    return to_agg_units(out, tas, "count", deffreq="D")


@declare_units(snd="[length]", thresh="[length]")
def snd_season_end(
    snd: xarray.DataArray,
    thresh: Quantified = "2 cm",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover end date (depth).

    First day after the start of the continuous snow depth cover when snow depth is below a threshold
    for at least `window` consecutive days.

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow thickness.
    thresh : Quantified
        Threshold snow thickness.
    window : int
        Minimum number of days with snow depth below the threshold.
    freq : str
        Resampling frequency. Default: "YS-JUL".
        The default value is chosen for the northern hemisphere.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        First day after the start of the continuous snow depth cover.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snd.where(snd > 0), n=1, freq=freq)
    out = season(snd, thresh, window=window, op=">=", stat="end", freq=freq)
    snd_se = out.where(~valid)
    return snd_se


@declare_units(snw="[mass]/[area]", thresh="[mass]/[area]")
def snw_season_end(
    snw: xarray.DataArray,
    thresh: Quantified = "4 kg m-2",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover end date (amount).

    First day after the start of the continuous snow water cover
    when snow water is below a threshold for at least `N` consecutive days.

    Parameters
    ----------
    snw : xarray.DataArray
        Surface snow amount.
    thresh : str
        Threshold snow amount.
    window : int
        Minimum number of days with snow water below the threshold.
    freq : str
        Resampling frequency. The default value is chosen for the Northern Hemisphere.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        First day after the start of the continuous snow amount cover.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snw.where(snw > 0), n=1, freq=freq)
    out = season(snw, thresh, window=window, op=">=", stat="end", freq=freq)
    snw_se = out.where(~valid)
    return snw_se


@declare_units(snd="[length]", thresh="[length]")
def snd_season_start(
    snd: xarray.DataArray,
    thresh: Quantified = "2 cm",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover start date (depth).

    Day of year when snow depth is above or equal to a threshold
    for at least `N` consecutive days.

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow thickness.
    thresh : Quantified
        Threshold snow thickness.
    window : int
        Minimum number of days with snow depth above or equal to the threshold.
    freq : str
        Resampling frequency. The default value is chosen for the Northern Hemisphere.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        First day of the year when the snow depth is superior to a threshold for a minimum duration.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snd.where(snd > 0), n=1, freq=freq)
    out = season(snd, thresh, window=window, op=">=", stat="start", freq=freq)
    snd_ss = out.where(~valid)
    return snd_ss


@declare_units(snw="[mass]/[area]", thresh="[mass]/[area]")
def snw_season_start(
    snw: xarray.DataArray,
    thresh: Quantified = "4 kg m-2",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover start date (amount).

    Day of year when snow water is above or equal to a threshold for at least `N` consecutive days.

    Parameters
    ----------
    snw : xarray.DataArray
        Surface snow amount.
    thresh : str
        Threshold snow amount.
    window : int
        Minimum number of days with snow amount above or equal to the threshold.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        First day of the year when the snow amount is superior to a threshold for a minimum duration.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snw.where(snw > 0), n=1, freq=freq)
    out = season(snw, thresh, window=window, op=">=", stat="start", freq=freq)
    snw_ss = out.where(~valid)
    return snw_ss


@declare_units(snd="[length]", thresh="[length]")
def snd_season_length(
    snd: xarray.DataArray,
    thresh: Quantified = "2 cm",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover duration (depth).

    The season starts when snow depth is above a threshold for at least `N` consecutive days
    and stops when it drops below the same threshold for the same number of days.

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow thickness.
    thresh : Quantified
        Threshold snow thickness.
    window : int
        Minimum number of days with snow depth above and below threshold.
    freq : str
        Resampling frequency. The default value is chosen for the northern hemisphere.

    Returns
    -------
    xarray.DataArray, [days]
        Length of the snow season.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snd.where(snd > 0), n=1, freq=freq)
    out = season(snd, thresh, window=window, op=">=", stat="length", freq=freq)
    snd_sl = out.where(~valid)
    return snd_sl


@declare_units(snw="[mass]/[area]", thresh="[mass]/[area]")
def snw_season_length(
    snw: xarray.DataArray,
    thresh: Quantified = "4 kg m-2",
    window: int = 14,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Snow cover duration (amount).

    The season starts when the snow amount is above a threshold for at least `N` consecutive days
    and stops when it drops below the same threshold for the same number of days.

    Parameters
    ----------
    snw : xarray.DataArray
        Surface snow amount.
    thresh : Quantified
        Threshold snow amount.
    window : int
        Minimum number of days with snow amount above and below threshold.
    freq : str
        Resampling frequency. The default value is chosen for the northern hemisphere.

    Returns
    -------
    xarray.DataArray, [days]
        Length of the snow season.

    References
    ----------
    :cite:cts:`chaumont_elaboration_2017`
    """
    valid = at_least_n_valid(snw.where(snw > 0), n=1, freq=freq)
    out = season(snw, thresh, window=window, op=">=", stat="length", freq=freq)
    snw_sl = out.where(~valid)
    return snw_sl


@declare_units(snd="[length]", thresh="[length]")
def snd_storm_days(snd: xarray.DataArray, thresh: Quantified = "25 cm", freq: str = "YS-JUL") -> xarray.DataArray:
    """
    Days with snowfall over threshold.

    Number of days with snowfall depth accumulation greater or equal to threshold (default: 25 cm).

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow depth.
    thresh : Quantified
        Threshold on snowfall depth accumulation require to label an event a `snd storm`.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Number of days per period identified as winter storms.

    Warnings
    --------
    The default `freq` is valid for the northern hemisphere.

    Notes
    -----
    Snowfall accumulation is estimated by the change in snow depth.
    """
    thresh = convert_units_to(thresh, snd)

    # Compute daily accumulation
    acc = snd.diff(dim="time")

    # Winter storm condition
    snd_sd = threshold_count(acc, ">=", thresh, freq)
    snd_sd = snd_sd.assign_attrs(units=to_agg_units(snd_sd, snd, "count", deffreq="D"))
    return snd_sd


@declare_units(snw="[mass]/[area]", thresh="[mass]/[area]")
def snw_storm_days(snw: xarray.DataArray, thresh: Quantified = "10 kg m-2", freq: str = "YS-JUL") -> xarray.DataArray:
    """
    Days with snowfall over threshold.

    Number of days with snowfall amount accumulation greater or equal to threshold (default: 10 kg m-2).

    Parameters
    ----------
    snw : xarray.DataArray
        Surface snow amount.
    thresh : Quantified
        Threshold on snowfall amount accumulation require to label an event a `snw storm`.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Number of days per period identified as winter storms.

    Warnings
    --------
    The default `freq` is valid for the northern hemisphere.

    Notes
    -----
    Snowfall accumulation is estimated by the change in snow amount.
    """
    thresh = convert_units_to(thresh, snw)

    # Compute daily accumulation
    acc = snw.diff(dim="time")

    # Winter storm condition
    snw_sd = threshold_count(acc, ">=", thresh, freq)
    snw_sd = snw_sd.assign_attrs(units=to_agg_units(snw_sd, snw, "count", deffreq="D"))
    return snw_sd


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def daily_pr_intensity(
    pr: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    r"""
    Average daily precipitation intensity.

    Return the average precipitation over wet days.
    Wet days are those with precipitation over a given threshold (default: 1 mm/day).

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Precipitation value over which a day is considered wet.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [precipitation]
        The average precipitation over wet days for each period.

    Notes
    -----
    Let :math:`\mathbf{p} = p_0, p_1, \ldots, p_n` be the daily precipitation and :math:`thresh` be the precipitation
    threshold defining wet days. Then the daily precipitation intensity is defined as:

    .. math::

       \frac{\sum_{i=0}^n p_i [p_i \leq thresh]}{\sum_{i=0}^n [p_i \leq thresh]}

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false.

    Examples
    --------
    The following would compute for each grid cell of file `pr.day.nc` the average precipitation fallen over days with
    precipitation >= 5 mm at seasonal frequency, i.e. DJF, MAM, JJA, SON, DJF, etc.:

    >>> from xclim.indices import daily_pr_intensity
    >>> pr = xr.open_dataset(path_to_pr_file).pr
    >>> daily_int = daily_pr_intensity(pr, thresh="5 mm/day", freq="QS-DEC")
    """
    t = convert_units_to(thresh, pr, context="hydro")

    # Get amount of rain (not rate)
    pram = rate2amount(pr)

    # Comparison
    comparison = compare(pr, op, t, constrain=(">", ">="))

    # put pram = 0 for non wet-days
    pram_wd = xarray.where(comparison, pram, 0)

    # sum over wanted period
    s = pram_wd.resample(time=freq).sum(dim="time")

    # get number of wetdays over period
    wd = wetdays(pr, thresh=thresh, freq=freq)
    dpr_int = s / wd

    # Issue originally introduced in https://github.com/hgrecco/pint/issues/1486
    # Should be resolved in pint v0.24. See: https://github.com/hgrecco/pint/issues/1913
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=DeprecationWarning)
        dpr_int = dpr_int.assign_attrs(units=f"{str2pint(pram.units) / str2pint(wd.units):~}")

    return dpr_int


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def dry_days(
    pr: xarray.DataArray,
    thresh: Quantified = "0.2 mm/d",
    freq: str = "YS",
    op: Literal["<", "lt", "<=", "le"] = "<",
) -> xarray.DataArray:
    r"""
    Dry days.

    The number of days with daily precipitation below threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Threshold precipitation on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".

    Returns
    -------
    xarray.DataArray, [time]
         Number of days with daily precipitation {op} threshold.

    Notes
    -----
    Let :math:`PR_{ij}` be the daily precipitation at day :math:`i` of period :math:`j`. Then counted is the number
    of days where:

    .. math::

       \sum PR_{ij} < Threshold [mm/day]
    """
    thresh = convert_units_to(thresh, pr, context="hydro")
    count = threshold_count(pr, op, thresh, freq, constrain=("<", "<="))
    dd = to_agg_units(count, pr, "count", deffreq="D")
    return dd


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def maximum_consecutive_wet_days(
    pr: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Consecutive wet days.

    Returns the maximum number of consecutive days with precipitation above a given threshold (default: 1 mm/day).

    Parameters
    ----------
    pr : xarray.DataArray
        Mean daily precipitation flux.
    thresh : Quantified
        Threshold precipitation on which to base evaluation.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        The maximum number of consecutive wet days.

    Notes
    -----
    Let :math:`\mathbf{x}=x_0, x_1, \ldots, x_n` be a daily precipitation series and :math:`\mathbf{s}` be the sorted
    vector of indices :math:`i` where :math:`[p_i > thresh] \neq [p_{i+1} > thresh]`, that is, the days where the
    precipitation crosses the *wet day* threshold. Then the maximum number of consecutive wet days is given by:

    .. math::

       \max(\mathbf{d}) \quad \mathrm{where} \quad d_j = (s_j - s_{j-1}) [x_{s_j} > 0^\circ C]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false. Note that this formula does not handle sequences at
    the start and end of the series, but the numerical algorithm does.
    """
    thresh = convert_units_to(thresh, pr, context="hydro")

    cond = pr > thresh
    mcwd = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.longest_run,
        freq=freq,
    )
    mcwd = to_agg_units(mcwd, pr, "count", deffreq="D")
    return mcwd


@declare_units(tasmax="[temperature]", tasmin="[temperature]", tas="[temperature]", thresh="[temperature]")
def cooling_degree_days_approximation(
    tasmax: xarray.DataArray,
    tasmin: xarray.DataArray,
    tas: xarray.DataArray,
    thresh: Quantified = "18 degC",
    freq: str = "YS",
) -> xarray.DataArray:
    """
    Cooling degree days approximation.

    A more robust approximation of cooling degree days as a function of the daily cycle of temperature.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    tasmin : xarray.DataArray
        Minimum daily temperature.
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Temperature threshold above which air is cooled.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Approximation of cooling degree days.

    References
    ----------
    :cite:cts:`spinoni_2018`
    """
    # Where tasmax < thresh; CDD = 0
    # Where tas <= thresh <= tasmax; CDD = (tasmax - tasmin)/4
    # Where tasmin < thresh <= tas; CDD = [(tasmax - thresh)/2 - (thresh - tasmin)/4]
    # Where tasmin >= thresh; CDD = tas - thresh
    thresh = convert_units_to(thresh, tas)
    tasmax = convert_units_to(tasmax, tas)
    tasmin = convert_units_to(tasmin, tas)

    cdd = xarray.where(
        tasmax < thresh,
        0,
        xarray.where(
            tasmin < thresh,
            xarray.where(
                tas <= thresh,
                (tasmax - tasmin) / 4,
                (tasmax - thresh) / 2 - (thresh - tasmin) / 4,
            ),
            tas - thresh,
        ),
    )
    cdd = cdd.resample(time=freq).sum(dim="time")
    cdd = to_agg_units(cdd, tas, "integral", deffreq="D")
    return cdd


@declare_units(tas="[temperature]", thresh="[temperature]")
def cooling_degree_days(tas: xarray.DataArray, thresh: Quantified = "18 degC", freq: str = "YS") -> xarray.DataArray:
    r"""
    Cooling degree days.

    Returns the sum of degree days above the temperature threshold at which spaces are cooled (default: 18℃).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Temperature threshold above which air is cooled.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time][temperature]
        Cooling degree days.

    Notes
    -----
    Let :math:`x_i` be the daily mean temperature at day :math:`i`. Then the cooling degree days above
    temperature threshold :math:`thresh` over period :math:`\phi` is given by:

    .. math::

       \sum_{i \in \phi} (x_{i}-{thresh} [x_i > thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false.
    """
    cdd = cumulative_difference(tas, threshold=thresh, op=">", freq=freq)
    return cdd


@declare_units(tas="[temperature]", thresh="[temperature]")
def growing_degree_days(tas: xarray.DataArray, thresh: Quantified = "4.0 degC", freq: str = "YS") -> xarray.DataArray:
    r"""
    Growing degree-days over threshold temperature value.

    The sum of growing degree-days over a given mean daily temperature threshold (default: 4℃).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time][temperature]
        The sum of growing degree-days above a given threshold.

    Notes
    -----
    Let :math:`TG_{ij}` be the mean daily temperature at day :math:`i` of period :math:`j`. Then the
    growing degree days are:

    .. math::

       GD4_j = \sum_{i=1}^I (TG_{ij}-{4} | TG_{ij} > {4}℃)
    """
    cd = cumulative_difference(tas, threshold=thresh, op=">", freq=freq)
    return cd


@declare_units(tas="[temperature]", thresh="[temperature]")
def growing_season_start(
    tas: xarray.DataArray,
    thresh: Quantified = "5.0 degC",
    mid_date: DayOfYearStr | None = "07-01",
    window: int = 5,
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    r"""
    Start of the growing season.

    The growing season starts with the first sequence of a minimum length of consecutive days above the threshold
    and ends with the first sequence of the same minimum length of consecutive days under the threshold. Sequences
    of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, a start can't happen later and an end can't happen earlier.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    mid_date : str, optional
        Date of the year before which the season must start. Should have the format '%m-%d'.
        ``None`` removes that constraint.
    window : int
        Minimum number of days with temperature above threshold needed for evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Start of the growing season.

    Warnings
    --------
    The default `freq` and `mid_date` parameters are valid for the northern hemisphere.
    """
    return season(
        tas,
        thresh=thresh,
        mid_date=mid_date,
        window=window,
        freq=freq,
        op=op,
        constrain=(">", ">="),
        stat="start",
    )


@declare_units(tas="[temperature]", thresh="[temperature]")
def growing_season_end(
    tas: xarray.DataArray,
    thresh: Quantified = "5.0 degC",
    mid_date: DayOfYearStr | None = "07-01",
    window: int = 5,
    freq: str = "YS",
    op: Literal[">", ">=", "lt", "le"] = ">",
) -> xarray.DataArray:
    r"""
    End of the growing season.

    The growing season starts with the first sequence of a minimum length of consecutive days above the threshold
    and ends with the first sequence of the same minimum length of consecutive days under the threshold. Sequences
    of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, a start can't happen later and an end can't happen earlier.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    mid_date : str, optional
        Date of the year after which to look for the end of the season. Should have the format '%m-%d'.
        ``None`` removes that constraint.
    window : int
        Minimum number of days with temperature below threshold needed for evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">". Note that this comparison is what defines the season.
        The end of the season happens when the condition is NOT met for `window` consecutive days.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        End of the growing season.

    Warnings
    --------
    The default `freq` and `mid_date` parameters are valid for the northern hemisphere.

    Notes
    -----
    Let :math:`x_i` be the daily mean temperature at day of the year :math:`i` for values of :math:`i` going from 1
    to 365 or 366. The start date of the end of growing season is given by the smallest index :math:`i`:

    .. math::

       \prod_{j=i}^{i+w} [x_j < thresh]

    where :math:`w` is the number of days where temperature should be inferior to a given threshold after a given date,
    and :math:`[P]` is 1 if :math:`P` is true, and 0 if false.
    """
    return season(
        tas,
        thresh=thresh,
        mid_date=mid_date,
        window=window,
        freq=freq,
        op=op,
        constrain=(">", ">="),
        stat="end",
    )


@declare_units(tas="[temperature]", thresh="[temperature]")
def growing_season_length(
    tas: xarray.DataArray,
    thresh: Quantified = "5.0 degC",
    window: int = 6,
    mid_date: DayOfYearStr | None = "07-01",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    r"""
    Growing season length.

    The growing season starts with the first sequence of a minimum length of consecutive days above the threshold
    and ends with the first sequence of the same minimum length of consecutive days under the threshold.
    Sequences of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, a start can't happen later and an end can't happen earlier.
    If the season starts but never ends, the length is computed up to the end of the resampling period.
    If no season start is found, but the data is valid, a length of 0 is returned.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    window : int
        Minimum number of days with temperature above the threshold to mark the beginning and end of growing season.
    mid_date : str, optional
        Date of the year before which the season must start and after which it can end. Should have the format '%m-%d'.
        Setting `None` removes that constraint.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [time]
        Growing season length.

    Warnings
    --------
    The default `freq` and `mid_date` parameters are valid for the Northern Hemisphere.

    Notes
    -----
    Let :math:`TG_{ij}` be the mean temperature at day :math:`i` of period :math:`j`. Then counted is
    the number of days between the first occurrence of at least 6 consecutive days with:

    .. math::

       TG_{ij} >= 5 ℃

    and the first occurrence after 1 July of at least six (6) consecutive days with:

    .. math::

       TG_{ij} < 5 ℃

    References
    ----------
    :cite:cts:`project_team_eca&d_algorithm_2013`

    Examples
    --------
    >>> from xclim.indices import growing_season_length
    >>> tas = xr.open_dataset(path_to_tas_file).tas

    For the Northern Hemisphere:

    >>> gsl_nh = growing_season_length(tas, mid_date="07-01", freq="YS")

    If working in the Southern Hemisphere, one can use:

    >>> gsl_sh = growing_season_length(tas, mid_date="01-01", freq="YS-JUL")
    """
    return season(
        tas,
        thresh=thresh,
        mid_date=mid_date,
        window=window,
        freq=freq,
        op=op,
        constrain=(">", ">="),
        stat="length",
    )


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def frost_season_length(
    tasmin: xarray.DataArray,
    window: int = 5,
    mid_date: DayOfYearStr | None = "01-01",
    thresh: Quantified = "0.0 degC",
    freq: str = "YS-JUL",
    op: Literal["<", "lt", "<=", "le"] = "<",
) -> xarray.DataArray:
    r"""
    Frost season length.

    The number of days between the first occurrence of at least `N` (default: 5) consecutive days with minimum daily
    temperature under a threshold (default: 0℃) and the first occurrence of at least `N` consecutive days with
    minimum daily temperature above the same threshold.
    A mid-date can be given to limit the earliest day the end of season can take.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    window : int
        Minimum number of days with temperature below threshold to mark the beginning and end of frost season.
    mid_date : str, optional
        The date must be included in the season. It is the earliest the end of the season can be.
        ``None`` removes that constraint.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".

    Returns
    -------
    xarray.DataArray, [time]
        Frost season length.

    Warnings
    --------
    The default `freq` and `mid_date` parameters are valid for the Northern Hemisphere.

    Notes
    -----
    Let :math:`TN_{ij}` be the minimum temperature at day :math:`i` of period :math:`j`. Then counted is
    the number of days between the first occurrence of at least N consecutive days with:

    .. math::

       TN_{ij} > 0 ℃

    and the first subsequent occurrence of at least N consecutive days with:

    .. math::

       TN_{ij} < 0 ℃

    Examples
    --------
    >>> from xclim.indices import frost_season_length
    >>> tasmin = xr.open_dataset(path_to_tasmin_file).tasmin

    For the Northern Hemisphere:

    >>> fsl_nh = frost_season_length(tasmin, freq="YS-JUL")

    If working in the Southern Hemisphere, one can use:

    >>> fsl_sh = frost_season_length(tasmin, freq="YS")
    """
    return season(
        tasmin,
        thresh=thresh,
        window=window,
        op=op,
        stat="length",
        freq=freq,
        mid_date=mid_date,
        constrain=("<", "<="),
    )


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def frost_free_season_start(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0.0 degC",
    window: int = 5,
    mid_date: DayOfYearStr | None = "07-01",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Start of the frost-free season.

    The frost-free season starts when a sequence of `window` consecutive days are above the threshold
    and ends when a sequence of consecutive days of the same length are under the threshold. Sequences
    of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, the start must occur before and the end after for the season to be valid.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    window : int
        Minimum number of days with temperature above/under the threshold to start/end the season.
    mid_date : DayOfYearStr, optional
        A date that must be included in the season. `None` removes that constraint.
    op : {">", "gt", ">=", "ge"}
        How to compare tasmin and the threshold.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Day of the year when the frost-free season starts.

    Notes
    -----
    Let :math:`x_i` be the daily mean temperature at day of the year :math:`i` for values of :math:`i` going from 1
    to 365 or 366. The start date of the season is given by the smallest index :math:`i`:

    .. math::

       \prod_{j=i}^{i+w} [x_j >= thresh]

    where :math:`w` is the number of days the temperature threshold should be met or exceeded,
    and `i` must be earlier than `mid_date`.
    """
    return season(
        tasmin,
        thresh=thresh,
        window=window,
        op=op,
        stat="start",
        freq=freq,
        mid_date=mid_date,
        constrain=(">", ">="),
    )


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def frost_free_season_end(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0.0 degC",
    window: int = 5,
    mid_date: DayOfYearStr | None = "07-01",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    End of the frost-free season.

    The frost-free season starts when a sequence of `window` consecutive days are above the threshold
    and ends when a sequence of consecutive days of the same length are under the threshold. Sequences
    of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, the start must occur before and the end after for the season to be valid.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    window : int
        Minimum number of days with temperature above/under the threshold to start/end the season.
    mid_date : DayOfYearStr, optional
        A date what must be included in the season. `None` removes that constraint.
    op : {">", "gt", ">=", "ge"}
        How to compare tasmin and the threshold.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Day of the year when the frost-free season starts.

    Notes
    -----
    Let :math:`x_i` be the daily mean temperature at day of the year :math:`i` for values of :math:`i` going from 1
    to 365 or 366. The start date is given by the smallest index :math:`i`:

    .. math::

       \prod_{k=i}^{i+w} [x_k >= thresh]

    while the end date is given bt the largest index :math:`j`:

    .. math::

       \prod_{k=j}^{j+w} [x_k < thresh]

    where :math:`w` is the number of days the temperature threshold should be exceeded/subceeded.
    An end is only valid if a start is also found and the end must happen later than `mid_date`
    while the start must happen earlier.
    """
    return season(
        tasmin,
        thresh=thresh,
        window=window,
        op=op,
        stat="end",
        freq=freq,
        mid_date=mid_date,
        constrain=(">", ">="),
    )


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def frost_free_season_length(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0.0 degC",
    window: int = 5,
    mid_date: DayOfYearStr | None = "07-01",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Length of the frost-free season.

    The frost-free season starts when a sequence of `window` consecutive days are above the threshold
    and ends when a sequence of consecutive days of the same length are under the threshold. Sequences
    of consecutive days under the threshold shorter than `window` are allowed within the season.
    A middle date can be given, the start must occur before and the end after for the season to be valid.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    window : int
        Minimum number of days with temperature above/under the threshold to start/end the season.
    mid_date : DayOfYearStr, optional
        A date what must be included in the season. `None` removes that constraint.
    op : {">", "gt", ">=", "ge"}
        How to compare tasmin and the threshold.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time]
        Length of the frost free season.

    Notes
    -----
    Let :math:`x_i` be the daily mean temperature at day of the year :math:`i` for values of :math:`i` going from 1
    to 365 or 366. The start date is given by the smallest index :math:`i`:

    .. math::

       \prod_{k=i}^{i+w} [x_k >= thresh]

    while the end date is given bt the largest index :math:`j`:

    .. math::

       \prod_{k=j}^{j+w} [x_k < thresh]

    where :math:`w` is the number of days the temperature threshold should be exceeded/subceeded.
    An end is only valid if a start is also found and the end must happen later than `mid_date`
    while the start must happen earlier.

    Examples
    --------
    >>> from xclim.indices import frost_season_length
    >>> tasmin = xr.open_dataset(path_to_tasmin_file).tasmin

    For the Northern Hemisphere:

    >>> ffsl_nh = frost_free_season_length(tasmin, freq="YS")

    If working in the Southern Hemisphere, one can use:

    >>> ffsl_sh = frost_free_season_length(tasmin, freq="YS-JUL")
    """
    return season(
        tasmin,
        thresh=thresh,
        window=window,
        op=op,
        stat="length",
        freq=freq,
        mid_date=mid_date,
        constrain=(">", ">="),
    )


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def frost_free_spell_max_length(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0.0 degC",
    window: int = 1,
    freq: str = "YS-JUL",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Longest frost-free spell.

    Longest spell of warm temperatures over a given period.
    Longest series of at least {window} consecutive days with temperature at or above the threshold.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        The temperature threshold needed to trigger a frost-free spell.
    window : int
        Minimum number of days with temperatures above thresholds to qualify as a frost-free day.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} longest spell in frost-free periods of minimum {window} days.
    """
    thresh = convert_units_to(thresh, tasmin)

    cond = compare(tasmin, op, thresh, constrain=(">", ">="))
    max_l = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.longest_run,
        freq=freq,
    )
    out = max_l.where(max_l >= window, 0)
    return to_agg_units(out, tasmin, "count", deffreq="D")


# FIXME: `tas` should instead be `tasmin` if we want to follow expected definitions.
@declare_units(tasmin="[temperature]", thresh="[temperature]")
def last_spring_frost(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0 degC",
    op: Literal["<", "lt", "<=", "le"] = "<",
    before_date: DayOfYearStr = "07-01",
    window: int = 1,
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Last day of temperatures inferior to a threshold temperature.

    Returns last day of period where minimum temperature is inferior to a threshold over a given number of days
    (default: 1) and limited to a final calendar date (default: July 1st).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".
    before_date : str,
        Date of the year before which to look for the final frost event. Should have the format '%m-%d'.
    window : int
        Minimum number of days with temperature below the threshold needed for evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Day of the year when temperature is inferior to a threshold over a given number of days for the first time.
        If there is no such day, returns np.nan.

    Warnings
    --------
    The default `freq` and `before_date` parameters are valid for the Northern Hemisphere.
    """
    thresh = convert_units_to(thresh, tasmin)
    cond = compare(tasmin, op, thresh, constrain=("<", "<="))

    out = resample_map(
        cond,
        "time",
        freq,
        rl.last_run_before_date,
        map_kwargs={
            "window": window,
            "date": before_date,
            "dim": "time",
            "coord": "dayofyear",
        },
    )
    out.attrs.update(units="", is_dayofyear=np.int32(1), calendar=get_calendar(tasmin))
    return out


@declare_units(tas="[temperature]", thresh="[temperature]")
def first_day_temperature_below(
    tas: xarray.DataArray,
    thresh: Quantified = "0 degC",
    op: Literal["<", "lt", "<=", "le"] = "<",
    after_date: DayOfYearStr = "07-01",
    window: int = 1,
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    First day of temperatures inferior to a given temperature threshold.

    Returns first day of period where temperature is inferior to a threshold over a given number of days (default: 1),
    limited to a starting calendar date (default: July 1st).

    Parameters
    ----------
    tas : xarray.DataArray
        Daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: ">".
    after_date : str
        Date of the year after which to look for the first event. Should have the format '%m-%d'.
    window : int
        Minimum number of days with temperature below the threshold needed for evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Day of the year when temperature is inferior to a threshold over a given number of days for the first time.
        If there is no such day, returns np.nan.

    Warnings
    --------
    The default `freq` and `after_date` parameters are valid for the Northern Hemisphere.
    """
    # noqa

    fdtb = first_day_threshold_reached(
        tas,
        threshold=thresh,
        op=op,
        after_date=after_date,
        window=window,
        freq=freq,
        constrain=("<", "<="),
    )
    return fdtb


@declare_units(tas="[temperature]", thresh="[temperature]")
def first_day_temperature_above(
    tas: xarray.DataArray,
    thresh: Quantified = "0 degC",
    op: Literal[">", "gt", ">=", "ge"] = ">",
    after_date: DayOfYearStr = "01-01",
    window: int = 1,
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    First day of temperatures superior to a given temperature threshold.

    Returns first day of period where temperature is superior to a threshold over a given number of days (default: 1),
    limited to a starting calendar date (default: January 1st).

    Parameters
    ----------
    tas : xarray.DataArray
        Daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".
    after_date : str
        Date of the year after which to look for the first event. Should have the format '%m-%d'.
    window : int
        Minimum number of days with temperature above the threshold needed for evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Day of the year when temperature is superior to a threshold over a given number of days for the first time.
        If there is no such day, returns np.nan.

    Warnings
    --------
    The default `freq` and `after_date` parameters are valid for the northern hemisphere.

    Notes
    -----
    Let :math:`x_i` be the daily mean|max|min temperature at day of the year :math:`i` for values of :math:`i` going
    from 1 to 365 or 366. The first day above temperature threshold is given by the smallest index :math:`i`:

    .. math::

       \prod_{j=i}^{i+w} [x_j > thresh]

    where :math:`w` is the number of days the temperature threshold should be exceeded, and :math:`[P]` is
    1 if :math:`P` is true, and 0 if false.
    """
    fdtr = first_day_threshold_reached(
        tas,
        threshold=thresh,
        op=op,
        after_date=after_date,
        window=window,
        freq=freq,
        constrain=(">", ">="),
    )
    return fdtr


@declare_units(prsn="[precipitation]", thresh="[precipitation]")
def first_snowfall(
    prsn: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    First day with snowfall rate above a given threshold.

    Returns the first day of a period where snowfall exceeds a threshold (default: 1 mm/day).

    Parameters
    ----------
    prsn : xarray.DataArray
        Snowfall flux.
    thresh : Quantified
        Threshold snowfall flux or liquid water equivalent snowfall rate. (default: 1 mm/day).
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Last day of the year where snowfall is superior to a threshold.
        If there is no such day, returns np.nan.

    Warnings
    --------
    The default `freq` is valid for the northern hemisphere.

    Notes
    -----
    The 1 mm/day liquid water equivalent snowfall rate threshold in :cite:cts:`frei_snowfall_2018` corresponds
    to the 1 cm/day snowfall rate threshold  in :cite:cts:`cbcl_climate_2020` using a snow density of 100 kg/m**3.

    If the threshold and prsn differ by a density (i.e. [length/time] vs. [mass/area/time]), a liquid water equivalent
    snowfall rate is assumed, and the threshold is converted using a 1000 kg m-3 density.

    References
    ----------
    :cite:cts:`cbcl_climate_2020`.
    """
    thresh = convert_units_to(thresh, prsn, context="hydro")
    cond = prsn >= thresh

    out = resample_map(
        cond,
        "time",
        freq,
        rl.first_run,
        map_kwargs={"window": 1, "dim": "time", "coord": "dayofyear"},
    )
    out.attrs.update(units="", is_dayofyear=np.int32(1), calendar=get_calendar(prsn))
    return out


@declare_units(prsn="[precipitation]", thresh="[precipitation]")
def last_snowfall(
    prsn: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Last day with snowfall above a given threshold.

    Returns the last day of a period where snowfall exceeds a threshold (default: 1 mm/day)

    Parameters
    ----------
    prsn : xarray.DataArray
        Snowfall flux.
    thresh : Quantified
        Threshold snowfall flux or liquid water equivalent snowfall rate (default: 1 mm/day).
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Last day of the year where snowfall is superior to a threshold.
        If there is no such day, returns np.nan.

    Warnings
    --------
    The default `freq` is valid for the Northern Hemisphere.

    Notes
    -----
    The 1 mm/day liquid water equivalent snowfall rate threshold in :cite:cts:`frei_snowfall_2018` corresponds
    to the 1 cm/day snowfall rate threshold in :cite:cts:`cbcl_climate_2020` using a snow density of 100 kg/m**3.

    If the threshold and prsn differ by a density (i.e. [length/time] vs. [mass/area/time]), a liquid water equivalent
    snowfall rate is assumed, and the threshold is converted using a 1000 kg m-3 density.

    References
    ----------
    :cite:cts:`cbcl_climate_2020`.
    """
    thresh = convert_units_to(thresh, prsn, context="hydro")
    cond = prsn >= thresh

    out = resample_map(
        cond,
        "time",
        freq,
        rl.last_run,
        map_kwargs={"window": 1, "dim": "time", "coord": "dayofyear"},
    )
    out.attrs.update(units="", is_dayofyear=np.int32(1), calendar=get_calendar(prsn))
    return out


@declare_units(
    prsn="[precipitation]",
    low="[precipitation]",
    high="[precipitation]",
)
def days_with_snow(
    prsn: xarray.DataArray,
    low: Quantified = "0 kg m-2 s-1",
    high: Quantified = "1E6 kg m-2 s-1",
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Days with snow.

    Return the number of days where snowfall is within low and high thresholds.

    Parameters
    ----------
    prsn : xarray.DataArray
        Snowfall flux.
    low : Quantified
        Minimum threshold snowfall flux or liquid water equivalent snowfall rate.
    high : Quantified
        Maximum threshold snowfall flux or liquid water equivalent snowfall rate.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [days]
        Number of days where snowfall is between low and high thresholds.

    Warnings
    --------
    The default `freq` is valid for the northern hemisphere.

    Notes
    -----
    If threshold and prsn differ by a density (i.e. [length/time] vs. [mass/area/time]), a liquid water equivalent
    snowfall rate is assumed and the threshold is converted using a 1000 kg m-3 density.

    References
    ----------
    :cite:cts:`matthews_planning_2017`.
    """
    low = convert_units_to(low, prsn, context="hydro")
    high = convert_units_to(high, prsn, context="hydro")
    out = domain_count(prsn, low, high, freq)
    return to_agg_units(out, prsn, "count", deffreq="D")


@declare_units(prsn="[precipitation]", thresh="[precipitation]")
def snowfall_frequency(
    prsn: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Percentage of snow days.

    Return the percentage of days where snowfall exceeds a threshold (default: 1 mm/day).

    Parameters
    ----------
    prsn : xarray.DataArray
        Snowfall flux.
    thresh : Quantified
        Threshold snowfall flux or liquid water equivalent snowfall rate (default: 1 mm/day).
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [%]
        Percentage of days where snowfall exceeds a given threshold.

    Warnings
    --------
    The default `freq` is valid for the Northern Hemisphere.

    Notes
    -----
    The 1 mm/day liquid water equivalent snowfall rate threshold in :cite:cts:`frei_snowfall_2018` corresponds
    to the 1 cm/day snowfall rate threshold in :cite:cts:`cbcl_climate_2020` using a snow density of 100 kg/m**3.

    If the threshold and prsn differ by a density (i.e. [length/time] vs. [mass/area/time]), a liquid water equivalent
    snowfall rate is assumed, and the threshold is converted using a 1000 kg m-3 density.

    References
    ----------
    :cite:cts:`frei_snowfall_2018`.
    """
    # High threshold here just needs to be a big value. It is converted to same units as
    # so that a warning message won't be triggered just because of this value
    thresh_units = pint2cfunits(units2pint(thresh))
    high_thresh = convert_units_to("1E6 kg m-2 s-1", thresh_units, context="hydro")
    high = f"{high_thresh} {thresh_units}"

    snow_days = days_with_snow(prsn, low=thresh, high=high, freq=freq)
    total_days = prsn.resample(time=freq).count(dim="time")
    snow_freq = snow_days / total_days * 100
    snow_freq = snow_freq.assign_attrs(**snow_days.attrs)
    # overwrite snow_days units
    snow_freq = snow_freq.assign_attrs(units="%")
    return snow_freq


@declare_units(prsn="[precipitation]", thresh="[precipitation]")
def snowfall_intensity(
    prsn: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Mean daily snowfall rate during snow days.

    Return the mean daily snowfall rate during days where snowfall exceeds a threshold (default: 1 mm/day).

    Parameters
    ----------
    prsn : xarray.DataArray
        Snowfall flux.
    thresh : Quantified
        Threshold snowfall flux or liquid water equivalent snowfall rate (default: 1 mm/day).
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray,
        Mean daily liquid water equivalent snowfall rate during days where snowfall exceeds a threshold.

    Warnings
    --------
    The default `freq` is valid for the Northern Hemisphere.

    Notes
    -----
    The 1 mm/day liquid water equivalent snowfall rate threshold in :cite:cts:`frei_snowfall_2018` corresponds
    to the 1 cm/day snowfall rate threshold  in :cite:cts:`cbcl_climate_2020` using a snow density of 100 kg/m**3.

    If threshold and prsn differ by a density (i.e. [length/time] vs. [mass/area/time]), a liquid water equivalent
    snowfall rate is assumed and the threshold is converted using a 1000 kg m-3 density.

    References
    ----------
    :cite:cts:`frei_snowfall_2018`.
    """
    thresh = convert_units_to(thresh, "mm/day", context="hydro")
    lwe_prsn = convert_units_to(prsn, "mm/day", context="hydro")

    cond = lwe_prsn >= thresh
    mean = lwe_prsn.where(cond).resample(time=freq).mean(dim="time")
    snow_int = mean.fillna(0)
    snow_int = snow_int.assign_attrs(units=lwe_prsn.units)
    return snow_int


@deprecated(from_version="0.57.0", suggested="hot_spell_total_length")
@declare_units(tasmax="[temperature]", thresh="[temperature]")
def heat_wave_index(
    tasmax: xarray.DataArray,
    thresh: Quantified = "25.0 degC",
    window: int = 5,
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    """
    Heat wave index.

    Number of days that are part of a heatwave, defined as five or more consecutive days over a threshold of 25℃.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        Threshold temperature on which to designate a heatwave.
    window : int
        Minimum number of days with temperature above the threshold to qualify as a heatwave.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    DataArray, [time]
        Heat wave index.
    """
    thresh = convert_units_to(thresh, tasmax)
    over = compare(tasmax, op, thresh, constrain=(">", ">="))
    out = rl.resample_and_rl(
        over,
        resample_before_rl,
        rl.windowed_run_count,
        window=window,
        freq=freq,
    )
    return to_agg_units(out, tasmax, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def hot_spell_max_magnitude(
    tasmax: xarray.DataArray,
    thresh: Quantified = "25.0 degC",
    window: int = 3,
    freq: str = "YS",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    """
    Hot spell maximum magnitude.

    Magnitude of the most intensive heat wave event as the sum of differences between tasmax
    and the given threshold for Heat Wave days, defined as three or more consecutive days
    over the threshold.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : xarray.DataArray
        Threshold temperature on which to designate a heatwave.
    window : int
        Minimum number of days with temperature above the threshold to qualify as a heatwave.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    DataArray, [time]
        Hot spell maximum magnitude.

    References
    ----------
    :cite:cts:`russo_magnitude_2014,zhang_high_2022`.
    """
    thresh = convert_units_to(thresh, tasmax)
    over_values = (tasmax - thresh).clip(0)

    out = rl.resample_and_rl(
        over_values,
        resample_before_rl,
        rl.windowed_max_run_sum,
        window=window,
        freq=freq,
    )
    return to_agg_units(out, tasmax, op="integral", deffreq="D")


@declare_units(tasmax="[temperature]", tasmin="[temperature]", tas="[temperature]", thresh="[temperature]")
def heating_degree_days_approximation(
    tasmax: xarray.DataArray,
    tasmin: xarray.DataArray,
    tas: xarray.DataArray,
    thresh: Quantified = "17.0 degC",
    freq: str = "YS",
) -> xarray.DataArray:
    """
    Heating degree days approximation.

    A more robust approximation of heating degree days as a function of the daily cycle of temperature.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    tasmin : xarray.DataArray
        Minimum daily temperature.
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray
        Approximation of heating degree days.

    References
    ----------
    :cite:cts:`spinoni_2018`
    """
    # Where tasmax <= thresh; HDD = thresh - tas
    # Where tas <= thresh < tasmax; HDD = (thresh - tasmin)/2 - (tasmax - thresh)/4
    # Where tasmin < thresh < tas; HDD = (thresh - tasmin)/4
    # Where tasmin >= thresh; HDD = 0
    thresh = convert_units_to(thresh, tasmax)
    tasmax = convert_units_to(tasmax, tas)
    tasmin = convert_units_to(tasmin, tas)

    hdd = xarray.where(
        tasmax <= thresh,
        thresh - tas,
        xarray.where(
            tas <= thresh,
            (thresh - tasmin) / 2 - (tasmax - thresh) / 4,
            xarray.where(tasmin <= thresh, (thresh - tasmin) / 4, 0),
        ),
    )
    hdd = hdd.resample(time=freq).sum(dim="time")
    hdd = to_agg_units(hdd, tas, "integral", deffreq="D")
    return hdd


@declare_units(tas="[temperature]", thresh="[temperature]")
def heating_degree_days(
    tas: xarray.DataArray,
    thresh: Quantified = "17.0 degC",
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Heating degree days.

    Sum of degree days below the temperature threshold (default: 17℃) at which spaces are heated.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time][temperature]
        Heating degree days index.

    Notes
    -----
    This index intentionally differs from its ECA&D :cite:p:`project_team_eca&d_algorithm_2013` equivalent: HD17.
    In HD17, values below zero are not clipped before the sum. The present definition should provide a better
    representation of the energy demand for heating buildings to the given threshold.

    Let :math:`TG_{ij}` be the daily mean temperature at day :math:`i` of period :math:`j`. Then the
    heating degree days are:

    .. math::

       HD17_j = \sum_{i=1}^{I} (17℃ - TG_{ij}) | TG_{ij} < 17℃)
    """
    hdd = cumulative_difference(tas, threshold=thresh, op="<", freq=freq)
    return hdd


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def hot_spell_max_length(
    tasmax: xarray.DataArray,
    thresh: Quantified = "30 degC",
    window: int = 1,
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Longest hot spell.

    Longest spell of high temperatures over a given period.
    Longest series of at least {window} consecutive days with temperature at or above {thresh}.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        The temperature threshold needed to trigger a hot spell.
    window : int
        Minimum number of days with temperatures below thresholds to qualify as a hot spell.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} longest spell in hot periods of minimum {window} days.

    Notes
    -----
    The threshold on `tasmax` follows the one used in heat waves. A day temperature threshold between 30° and 35°C
    was selected by Health Canada professionals, following a temperature–mortality analysis. This absolute temperature
    threshold characterizes the occurrence of hot weather events that can result in adverse health outcomes for Canadian
    communities :cite:p:`casati_regional_2013`.

    In :cite:t:`robinson_definition_2001` where heat waves are also considered, the corresponding parameters would
    be `thresh=39.44, window=2` (103F).

    References
    ----------
    :cite:cts:`casati_regional_2013,robinson_definition_2001`
    """
    thresh = convert_units_to(thresh, tasmax)

    cond = compare(tasmax, op, thresh, constrain=(">", ">="))
    max_l = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.longest_run,
        freq=freq,
    )
    out = max_l.where(max_l >= window, 0)
    return to_agg_units(out, tasmax, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def hot_spell_total_length(
    tasmax: xarray.DataArray,
    thresh: Quantified = "30 degC",
    window: int = 3,
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Total length of hot spells.

    Total length of spells of high temperatures over a given period.
    Total length of series of at least {window} consecutive days with temperature at or above {thresh}.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        The temperature threshold needed to trigger a hot spell.
    window : int
        Minimum number of days with temperatures below the threshold to qualify as a hot spell.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} total number of days in hot periods of minimum {window} days.

    Notes
    -----
    The threshold on `tasmax` follows the one used in heat waves. A day temperature threshold between 30° and 35°C
    was selected by Health Canada professionals, following a temperature–mortality analysis. This absolute temperature
    threshold characterize the occurrence of hot weather events that can result in adverse health outcomes for Canadian
    communities :cite:p:`casati_regional_2013`.

    In :cite:t:`robinson_definition_2001` where heat waves are also considered, the corresponding parameters would
    be `thresh=39.44, window=2` (103F).
    """
    thresh = convert_units_to(thresh, tasmax)

    cond = compare(tasmax, op, thresh, constrain=(">", ">="))
    out = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.windowed_run_count,
        window=window,
        freq=freq,
    )
    return to_agg_units(out, tasmax, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def hot_spell_frequency(
    tasmax: xarray.DataArray,
    thresh: Quantified = "30 degC",
    window: int = 3,
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    """
    Hot spell frequency.

    The number of hot spell events, defined as a sequence of consecutive {window} days
    with mean daily temperature above a {thresh}.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        Threshold temperature below which a hot spell begins.
    window : int
        Minimum number of days with temperature above the threshold to qualify as a hot spell.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run.

    Returns
    -------
    xarray.DataArray, [unitless]
        The {freq} number of hot periods of minimum {window} days.

    Notes
    -----
    The threshold on `tasmax` follows the one used in heat waves. A day temperature threshold between 30° and 35°C
    was selected by Health Canada professionals, following a temperature–mortality analysis. This absolute temperature
    threshold characterize the occurrence of hot weather events that can result in adverse health outcomes for Canadian
    communities :cite:p:`casati_regional_2013`.

    In :cite:t:`robinson_definition_2001` where heat waves are also considered, the corresponding parameters would
    be `thresh=39.44, window=2` (103F).

    References
    ----------
    :cite:cts:`casati_regional_2013,robinson_definition_2001`
    """
    thresh = convert_units_to(thresh, tasmax)

    cond = compare(tasmax, op, thresh, constrain=(">", ">="))
    out = rl.resample_and_rl(
        cond,
        resample_before_rl,
        rl.windowed_run_events,
        window=window,
        freq=freq,
    )
    out.attrs["units"] = ""
    return out


@declare_units(snd="[length]", thresh="[length]")
def snd_days_above(
    snd: xarray.DataArray,
    thresh: Quantified = "2 cm",
    freq: str = "YS-JUL",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    """
    The number of days with snow depth above a threshold.

    Number of days where surface snow depth is greater or equal to a given threshold (default: 2 cm).

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow thickness.
    thresh : Quantified
        Threshold snow thickness.
    freq : str
        Resampling frequency. The default value is chosen for the Northern Hemisphere.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where snow depth is greater than or equal to {thresh}.
    """
    valid = at_least_n_valid(snd, n=1, freq=freq)
    thresh = convert_units_to(thresh, snd)
    out = threshold_count(snd, op, thresh, freq)
    return to_agg_units(out, snd, "count", deffreq="D").where(~valid)


@declare_units(snw="[mass]/[area]", thresh="[mass]/[area]")
def snw_days_above(
    snw: xarray.DataArray,
    thresh: Quantified = "4 kg m-2",
    freq: str = "YS-JUL",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    """
    The number of days with snow amount above a given threshold.

    Number of days where surface snow amount is greater or equal to a given threshold.

    Parameters
    ----------
    snw : xarray.DataArray
        Surface snow amount.
    thresh : str
        Threshold snow amount.
    freq : str
        Resampling frequency. The default value is chosen for the Northern hemisphere.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where snow amount is greater than or equal to {thresh}.
    """
    valid = at_least_n_valid(snw, n=1, freq=freq)
    thresh = convert_units_to(thresh, snw)
    out = threshold_count(snw, op, thresh, freq)
    return to_agg_units(out, snw, "count", deffreq="D").where(~valid)


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def tn_days_above(
    tasmin: xarray.DataArray,
    thresh: Quantified = "20.0 degC",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
):
    """
    The number of days with tasmin above a threshold (number of tropical nights).

    Number of days where minimum daily temperature exceeds a threshold (default: 20℃).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tasmin {op} threshold.

    Notes
    -----
    Let :math:`TN_{ij}` be the minimum daily temperature at day :math:`i` of period :math:`j`. Then
    counted is the number of days where:

    .. math::

       TN_{ij} > Threshold [℃]
    """
    thresh = convert_units_to(thresh, tasmin)
    f = threshold_count(tasmin, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(f, tasmin, "count", deffreq="D")


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def tn_days_below(
    tasmin: xarray.DataArray,
    thresh: Quantified = "-10.0 degC",
    freq: str = "YS",
    op: Literal["<", "lt", "<=", "le"] = "<",
) -> xarray.DataArray:
    """
    Number of days with tasmin below a given threshold.

    Number of days where minimum daily temperature is below a given threshold (default: -10℃).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tasmin {op} threshold.

    Notes
    -----
    Let :math:`TN_{ij}` be the minimum daily temperature at day :math:`i` of period :math:`j`. Then
    counted is the number of days where:

    .. math::

       TN_{ij} < Threshold [℃]
    """
    thresh = convert_units_to(thresh, tasmin)
    f1 = threshold_count(tasmin, op, thresh, freq, constrain=("<", "<="))
    return to_agg_units(f1, tasmin, "count", deffreq="D")


@declare_units(tas="[temperature]", thresh="[temperature]")
def tg_days_above(
    tas: xarray.DataArray,
    thresh: Quantified = "10.0 degC",
    freq: str = "YS",
    op: Literal["<", "lt", "<=", "le"] = ">",
):
    """
    The number of days with tas above a given threshold.

    Number of days where mean daily temperature exceeds a threshold (default: 10℃).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tas {op} threshold.

    Notes
    -----
    Let :math:`TG_{ij}` be the mean daily temperature at day :math:`i` of period :math:`j`. Then
    counted is the number of days where:

    .. math::

       TG_{ij} > Threshold [℃]
    """
    thresh = convert_units_to(thresh, tas)
    f = threshold_count(tas, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(f, tas, "count", deffreq="D")


@declare_units(tas="[temperature]", thresh="[temperature]")
def tg_days_below(
    tas: xarray.DataArray,
    thresh: Quantified = "10.0 degC",
    freq: str = "YS",
    op: Literal["<", "lt", "<=", "le"] = "<",
):
    """
    The number of days with tas below a given threshold.

    Number of days where mean daily temperature is below a given threshold (default: 10℃).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tas {op} threshold.

    Notes
    -----
    Let :math:`TG_{ij}` be the mean daily temperature at day :math:`i` of period :math:`j`. Then counted is the number
    of days where:

    .. math::

       TG_{ij} < Threshold [℃]
    """
    thresh = convert_units_to(thresh, tas)
    f1 = threshold_count(tas, op, thresh, freq, constrain=("<", "<="))
    return to_agg_units(f1, tas, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def tx_days_above(
    tasmax: xarray.DataArray,
    thresh: Quantified = "25.0 degC",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
) -> xarray.DataArray:
    """
    The number of days with tasmax above a given threshold (number of summer days).

    Number of days where maximum daily temperature exceeds a given threshold (default: 25℃).

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tasmax {op} threshold (number of summer days).

    Notes
    -----
    Let :math:`TX_{ij}` be the maximum daily temperature at day :math:`i` of period :math:`j`. Then counted is the
    number of days where:

    .. math::

       TX_{ij} > Threshold [℃]
    """
    thresh = convert_units_to(thresh, tasmax)
    f = threshold_count(tasmax, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(f, tasmax, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def tx_days_below(
    tasmax: xarray.DataArray,
    thresh: Quantified = "25.0 degC",
    freq: str = "YS",
    op: Literal["<", "lt", "<=", "le"] = "<",
):
    """
    The number of days with tasmax below a given threshold.

    Number of days where maximum daily temperature is below a given threshold (default: 25℃).

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {"<", "lt", "<=", "le"}
        Comparison operation. Default: "<".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days where tasmin {op} threshold.

    Notes
    -----
    Let :math:`TX_{ij}` be the maximum daily temperature at day :math:`i` of period :math:`j`. Then
    counted is the number of days where:

    .. math::

       TX_{ij} < Threshold [℃]
    """
    thresh = convert_units_to(thresh, tasmax)
    f1 = threshold_count(tasmax, op, thresh, freq, constrain=("<", "<="))
    return to_agg_units(f1, tasmax, "count", deffreq="D")


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def warm_day_frequency(
    tasmax: xarray.DataArray,
    thresh: Quantified = "30 degC",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
) -> xarray.DataArray:
    """
    Frequency of extreme warm days.

    Return the number of days with maximum daily temperature exceeding a given threshold (default: 30℃) per period.

    Parameters
    ----------
    tasmax : xarray.DataArray
        Maximum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days with tasmax {op} threshold per period.

    Notes
    -----
    Let :math:`TX_{ij}` be the maximum daily temperature at day :math:`i` of period :math:`j`. Then counted is the
    number of days where:

    .. math::

       TN_{ij} > Threshold [℃]
    """
    thresh = convert_units_to(thresh, tasmax)
    events = threshold_count(tasmax, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(events, tasmax, "count", deffreq="D")


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def warm_night_frequency(
    tasmin: xarray.DataArray,
    thresh: Quantified = "22 degC",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">",
) -> xarray.DataArray:
    """
    Frequency of extreme warm nights.

    Return the number of days with minimum daily temperatures exceeding a given threshold (default: 22℃) per period.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature on which to base evaluation.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">".

    Returns
    -------
    xarray.DataArray, [time]
        Number of days with tasmin {op} threshold per period.
    """
    thresh = convert_units_to(thresh, tasmin)
    events = threshold_count(tasmin, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(events, tasmin, "count", deffreq="D")


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def wetdays(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm/day",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    """
    Wet days.

    Return the total number of days during period with precipitations over a given threshold (default: 1.0 mm/day).

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Precipitation value over which a day is considered wet.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [time]
        The number of wet days for each period [day].

    Examples
    --------
    The following would compute for each grid cell of file `pr.day.nc` the number days with precipitation over 5 mm
    at the seasonal frequency, i.e. DJF, MAM, JJA, SON, DJF, etc.:

    >>> from xclim.indices import wetdays
    >>> pr = xr.open_dataset(path_to_pr_file).pr
    >>> wd = wetdays(pr, thresh="5 mm/day", freq="QS-DEC")
    """
    thresh = convert_units_to(thresh, pr, context="hydro")

    wd = threshold_count(pr, op, thresh, freq, constrain=(">", ">="))
    return to_agg_units(wd, pr, "count", deffreq="D")


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def wetdays_prop(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm/day",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    """
    Proportion of wet days.

    Return the proportion of days during period with precipitations over a given threshold (default: 1.0 mm/day).

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Precipitation value over which a day is considered wet.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [time]
        The proportion of wet days for each period [1].

    Examples
    --------
    The following would compute for each grid cell of file `pr.day.nc` the proportion of days with precipitation over
    5 mm at the seasonal frequency, i.e. DJF, MAM, JJA, SON, DJF, etc.:

    >>> from xclim.indices import wetdays_prop
    >>> pr = xr.open_dataset(path_to_pr_file).pr
    >>> wd = wetdays_prop(pr, thresh="5 mm/day", freq="QS-DEC")
    """
    thresh = convert_units_to(thresh, pr, context="hydro")

    wd = compare(pr, op, thresh, constrain=(">", ">="))
    fwd = wd.resample(time=freq).mean(dim="time").assign_attrs(units="1")
    return fwd


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def maximum_consecutive_frost_days(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0.0 degC",
    freq: str = "YS-JUL",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Maximum number of consecutive frost days (Tn < 0℃).

    The maximum number of consecutive days within the period where the minimum daily temperature
    is under a given threshold (default: 0°C).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
      Determines if the resampling should take place before or after the run
      length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        The maximum number of consecutive frost days (tasmin < threshold per period).

    Warnings
    --------
    The default `freq` is valid for the Northern Hemisphere.

    Notes
    -----
    Let :math:`\mathbf{t}=t_0, t_1, \ldots, t_n` be a minimum daily temperature series and :math:`thresh`
    the threshold below which a day is considered a frost day. Let :math:`\mathbf{s}` be the sorted vector
    of indices :math:`i` where :math:`[t_i < thresh] \neq [t_{i+1} < thresh]`, that is, the days where the
    temperature crosses the threshold. Then the maximum number of consecutive frost days is given by:

    .. math::

       \max(\mathbf{d}) \quad \mathrm{where} \quad d_j = (s_j - s_{j-1}) [t_{s_j} < thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false. Note that this formula does not handle sequences at
    the start and end of the series, but the numerical algorithm does.
    """
    csml: xarray.DataArray = cold_spell_max_length(
        tasmin,
        thresh=thresh,
        window=1,
        freq=freq,
        op="<",
        resample_before_rl=resample_before_rl,
    )
    return csml


@declare_units(pr="[precipitation]", thresh="[precipitation]")
def maximum_consecutive_dry_days(
    pr: xarray.DataArray,
    thresh: Quantified = "1 mm/day",
    freq: str = "YS",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Maximum number of consecutive dry days.

    Return the maximum number of consecutive days within the period where precipitation
    is below a certain threshold (default: 1 mm/day).

    Parameters
    ----------
    pr : xarray.DataArray
        Mean daily precipitation flux.
    thresh : Quantified
        Threshold precipitation on which to base evaluation.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
      Determines if the resampling should take place before or after the run
      length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        The maximum number of consecutive dry days (precipitation < threshold per period).

    Notes
    -----
    Let :math:`\mathbf{p}=p_0, p_1, \ldots, p_n` be a daily precipitation series and :math:`thresh` the threshold
    under which a day is considered dry. Then let :math:`\mathbf{s}` be the sorted vector of indices :math:`i` where
    :math:`[p_i < thresh] \neq [p_{i+1} < thresh]`, that is, the days where the precipitation crosses the threshold.
    Then the maximum number of consecutive dry days is given by:

    .. math::

       \max(\mathbf{d}) \quad \mathrm{where} \quad d_j = (s_j - s_{j-1}) [p_{s_j} < thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false. Note that this formula does not handle sequences at
    the start and end of the series, but the numerical algorithm does.
    """
    t = convert_units_to(thresh, pr, context="hydro")
    group = pr < t
    resampled = rl.resample_and_rl(
        group,
        resample_before_rl,
        rl.longest_run,
        freq=freq,
    )
    mcdd = to_agg_units(resampled, pr, "count", deffreq="D")
    return mcdd


@declare_units(tasmin="[temperature]", thresh="[temperature]")
def maximum_consecutive_frost_free_days(
    tasmin: xarray.DataArray,
    thresh: Quantified = "0 degC",
    freq: str = "YS",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Maximum number of consecutive frost-free days (Tn >= 0℃).

    Return the maximum number of consecutive days within the period where the minimum daily temperature is
    above or equal to a given threshold (default: 0℃).

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum daily temperature.
    thresh : Quantified
        Threshold temperature.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
      Determines if the resampling should take place before or after the run
      length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        The maximum number of consecutive frost free days (tasmin >= threshold per period).

    Warnings
    --------
    The default `freq` is valid for the Northern Hemisphere.

    Notes
    -----
    Let :math:`\mathbf{t}=t_0, t_1, \ldots, t_n` be a daily minimum temperature series and :math:`thresh`
    the threshold above or equal to which a day is considered a frost free day. Let :math:`\mathbf{s}`
    be the sorted vector of indices :math:`i` where :math:`[t_i <= thresh] \neq [t_{i+1} <= thresh]`,
    that is, the days where the temperature crosses the threshold.
    Then the maximum number of consecutive frost free days is given by:

    .. math::

       \max(\mathbf{d}) \quad \mathrm{where} \quad d_j = (s_j - s_{j-1}) [t_{s_j} >= thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false. Note that this formula does not handle sequences at
    the start and end of the series, but the numerical algorithm does.
    """
    mcffd = frost_free_spell_max_length(
        tasmin,
        thresh=thresh,
        window=1,
        freq=freq,
        op=">=",
        resample_before_rl=resample_before_rl,
    )
    return mcffd


@declare_units(tasmax="[temperature]", thresh="[temperature]")
def maximum_consecutive_tx_days(
    tasmax: xarray.DataArray,
    thresh: Quantified = "25 degC",
    freq: str = "YS",
    resample_before_rl: bool = True,
) -> xarray.DataArray:
    r"""
    Maximum number of consecutive days with tasmax above a given threshold (summer days).

    Return the maximum number of consecutive days within the period where the maximum daily temperature is
    above a certain threshold (default: 25℃).

    Parameters
    ----------
    tasmax : xarray.DataArray
        Max daily temperature.
    thresh : Quantified
        Threshold temperature.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
      Determines if the resampling should take place before or after the run
      length encoding (or a similar algorithm) is applied to runs.

    Returns
    -------
    xarray.DataArray, [time]
        The maximum number of days with tasmax > thresh per periods (summer days).

    Notes
    -----
    Let :math:`\mathbf{t}=t_0, t_1, \ldots, t_n` be a daily maximum temperature series and :math:`thresh`
    the threshold above which a day is considered a summer day. Let :math:`\mathbf{s}` be the sorted vector
    of indices :math:`i` where :math:`[t_i < thresh] \neq [t_{i+1} < thresh]`, that is, the days where the
    temperature crosses the threshold. Then the maximum number of consecutive tx_days (summer days) is given by:

    .. math::

       \max(\mathbf{d}) \quad \mathrm{where} \quad d_j = (s_j - s_{j-1}) [t_{s_j} > thresh]

    where :math:`[P]` is 1 if :math:`P` is true, and 0 if false. Note that this formula does not handle sequences at
    the start and end of the series, but the numerical algorithm does.
    """
    mctxd = hot_spell_max_length(
        tasmax,
        thresh=thresh,
        window=1,
        freq=freq,
        op=">",
        resample_before_rl=resample_before_rl,
    )
    return mctxd


@declare_units(siconc="[]", areacello="[area]", thresh="[]")
def sea_ice_area(
    siconc: xarray.DataArray, areacello: xarray.DataArray, thresh: Quantified = "15 %"
) -> xarray.DataArray:
    """
    Total sea ice area.

    Sea ice area measures the total sea ice covered area where sea ice concentration is above a given threshold,
    usually set to 15%.

    Parameters
    ----------
    siconc : xarray.DataArray
        Sea ice concentration (area fraction).
    areacello : xarray.DataArray
        Grid cell area (usually over the ocean).
    thresh : Quantified
        Minimum sea ice concentration for a grid cell to contribute to the sea ice extent.

    Returns
    -------
    xarray.DataArray, [length]^2
        Sea ice area.

    Notes
    -----
    To compute sea ice area over a subregion, first mask or subset the input sea ice concentration data.

    References
    ----------
    "What is the difference between sea ice area and extent?" - :cite:cts:`nsidc_frequently_2008`
    """
    t = convert_units_to(thresh, siconc)
    factor = convert_units_to("100 %", siconc)
    sia = xarray.dot(siconc.where(siconc >= t, 0), areacello) / factor
    sia = sia.assign_attrs(units=areacello.units)
    return sia


@declare_units(siconc="[]", areacello="[area]", thresh="[]")
def sea_ice_extent(
    siconc: xarray.DataArray, areacello: xarray.DataArray, thresh: Quantified = "15 %"
) -> xarray.DataArray:
    """
    Total sea ice extent.

    Sea ice extent measures the *ice-covered* area, where a region is considered ice-covered if its sea ice
    concentration is above a given threshold, usually set to 15%.

    Parameters
    ----------
    siconc : xarray.DataArray
        Sea ice concentration (area fraction).
    areacello : xarray.DataArray
        Grid cell area.
    thresh : Quantified
        Minimum sea ice concentration for a grid cell to contribute to the sea ice extent.

    Returns
    -------
    xarray.DataArray, [length]^2
        Sea ice extent.

    Notes
    -----
    To compute sea ice area over a subregion, first mask or subset the input sea ice concentration data.

    References
    ----------
    "What is the difference between sea ice area and extent?" - :cite:cts:`nsidc_frequently_2008`
    """
    t = convert_units_to(thresh, siconc)
    sie = xarray.dot(siconc >= t, areacello)
    sie = sie.assign_attrs(units=areacello.units)
    return sie


@declare_units(sfcWind="[speed]", thresh="[speed]")
def windy_days(sfcWind: xarray.DataArray, thresh: Quantified = "10.8 m s-1", freq: str = "MS") -> xarray.DataArray:
    r"""
    Windy days.

    The number of days with average near-surface wind speed above a given threshold (default: 10.8 m/s).

    Parameters
    ----------
    sfcWind : xarray.DataArray
        Daily average near-surface wind speed.
    thresh : Quantified
        Threshold average near-surface wind speed on which to base evaluation.
    freq : str
        Resampling frequency.

    Returns
    -------
    xarray.DataArray, [time]
        Number of days with average near-surface wind speed above threshold.

    Notes
    -----
    Let :math:`WS_{ij}` be the windspeed at day :math:`i` of period :math:`j`. Then counted is the number of days where:

    .. math::

       WS_{ij} >= Threshold [m s-1]
    """
    thresh = convert_units_to(thresh, sfcWind)
    out = threshold_count(sfcWind, ">=", thresh, freq)
    out = to_agg_units(out, sfcWind, "count", deffreq="D")
    return out


@declare_units(pr="[precipitation]", prc="[precipitation]", thresh="[precipitation]")
def rprctot(
    pr: xarray.DataArray,
    prc: xarray.DataArray,
    thresh: Quantified = "1.0 mm/day",
    freq: str = "YS",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
) -> xarray.DataArray:
    """
    Proportion of accumulated precipitation arising from convective processes.

    Return the proportion of total accumulated precipitation due to convection on days with total precipitation
    greater or equal to a given threshold (default: 1.0 mm/day) during the given period.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    prc : xarray.DataArray
        Daily convective precipitation.
    thresh : Quantified
        Precipitation value over which a day is considered wet.
    freq : str
        Resampling frequency.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".

    Returns
    -------
    xarray.DataArray, [dimensionless]
        The proportion of the total precipitation accounted for by convective precipitation for each period.
    """
    thresh = convert_units_to(thresh, pr, context="hydro")
    prc = convert_units_to(prc, pr)

    wd = compare(pr, op, thresh)
    pr_tot = rate2amount(pr).where(wd).resample(time=freq).sum(dim="time")
    prc_tot = rate2amount(prc).where(wd).resample(time=freq).sum(dim="time")

    ratio = prc_tot / pr_tot
    ratio = ratio.assign_attrs(units="")

    return ratio


@declare_units(tas="[temperature]", thresh="[temperature]", sum_thresh="K days")
def degree_days_exceedance_date(
    tas: xarray.DataArray,
    thresh: Quantified = "0 degC",
    sum_thresh: Quantified = "25 K days",
    op: Literal[">", "gt", "<", "lt", ">=", "ge", "<=", "le"] = ">",
    after_date: DayOfYearStr | None = None,
    never_reached: DayOfYearStr | int | None = None,
    freq: str = "YS",
) -> xarray.DataArray:
    r"""
    Degree-days exceedance date.

    Day of year when the sum of degree days exceeds a threshold (default: 25 K days).
    Degree days are computed above or below a given temperature threshold (default: 0℃).

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    thresh : Quantified
        Threshold temperature on which to base degree-days evaluation.
    sum_thresh : Quantified
        Threshold of the degree days sum.
    op : {">", "gt", "<", "lt", ">=", "ge", "<=", "le"}
        If equivalent to '>', degree days are computed as `tas - thresh` and if
        equivalent to '<', they are computed as `thresh - tas`.
    after_date : str, optional
        Date at which to start the cumulative sum.
        In "MM-DD" format, defaults to the start of the sampling period.
    never_reached : int, str, optional
        What to do when `sum_thresh` is never exceeded.
        If an int, the value to assign as a day-of-year.
        If a string, must be in "MM-DD" format, the day-of-year of that date is assigned.
        Default (None) assigns "NaN".
    freq : str
        Resampling frequency. If `after_date` is given, `freq` should be annual.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Degree-days exceedance date.

    Notes
    -----
    Let :math:`TG_{ij}` be the daily mean temperature at day :math:`i` of period :math:`j`,
    :math:`T` is the reference threshold and :math:`ST` is the sum threshold. Then, starting
    at day :math:i_0:, the degree days exceedance date is the first day :math:`k` such that:

    .. math::

       \begin{cases}
       ST < \sum_{i=i_0}^{k} \max(TG_{ij} - T, 0) & \text{if $op$ is '>'} \\
       ST < \sum_{i=i_0}^{k} \max(T - TG_{ij}, 0) & \text{if $op$ is '<'}
       ST < \sum_{i=i_0}^{k} \max(T - TG_{ij}, 0) & \text{if $op$ is '<'}
       \end{cases}
       \end{cases}

    The resulting :math:`k` is expressed as a day of year.

    Cumulated degree days have numerous applications including plant and insect phenology.
    See: https://en.wikipedia.org/wiki/Growing_degree-day for examples (:cite:t:`wikipedia_contributors_growing_2021`).
    """
    thresh = convert_units_to(thresh, "K")
    tas = convert_units_to(tas, "K")
    sum_thresh = convert_units_to(sum_thresh, "K days")

    if op in ["<", "lt", "<=", "le"]:
        c = thresh - tas
    elif op in [">", "gt", ">=", "ge"]:
        c = tas - thresh
    else:
        raise NotImplementedError(f"op: '{op}'.")

    def _exceedance_date(grp):
        strt_idx = rl.index_of_date(grp.time, after_date, max_idxs=1, default=0)
        if strt_idx.size == 0:  # The date is not within the group. Happens at boundaries.
            return xarray.full_like(grp.isel(time=0), np.nan, float).drop_vars("time")  # type: ignore
        cumsum = grp.where(grp.time >= grp.time[strt_idx][0]).cumsum("time")

        out = rl.first_run_after_date(
            cumsum > sum_thresh,
            window=1,
            date=None,
        )
        if never_reached is None:
            # This is slightly faster in numpy and generates fewer tasks in dask
            return out
        if isinstance(never_reached, str):
            never_reached_val = doy_from_string(DayOfYearStr(never_reached), grp.time.dt.year[0], grp.time.dt.calendar)
        else:
            never_reached_val = never_reached
        return xarray.where((cumsum <= sum_thresh).all("time"), never_reached_val, out)

    dded = resample_map(c.clip(0), "time", freq, _exceedance_date)
    dded = dded.assign_attrs(units="", is_dayofyear=np.int32(1), calendar=get_calendar(tas))
    return dded


@declare_units(pr="[precipitation]", thresh="[length]")
def dry_spell_frequency(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 3,
    freq: str = "YS",
    resample_before_rl: bool = True,
    op: Literal["sum", "max", "min", "mean"] = "sum",
    **indexer,
) -> xarray.DataArray:
    r"""
    Return the number of dry periods of n days and more.

    Periods during which the accumulated or maximal daily precipitation amount
    within a window of n days is under a given threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Precipitation amount under which a period is considered dry.
        The value against which the threshold is compared depends on `op`.
    window : int
        Minimum length of the spells.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run length encoding
        (or a similar algorithm) is applied to runs.
    op : {"sum", "max", "min", "mean"}
        Operation to perform on the window.
        Default is "sum", which checks that the sum of accumulated precipitation over the whole window
        is less than the threshold.
        "max" checks that the maximal daily precipitation amount within the window is less than the threshold.
        This is the same as verifying that each individual day is below the threshold.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the dry days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [unitless]
        The {freq} number of dry periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Examples
    --------
    >>> from xclim.indices import dry_spell_frequency
    >>> pr = xr.open_dataset(path_to_pr_file).pr
    >>> dsf_sum = dry_spell_frequency(pr=pr, op="sum")
    >>> dsf_max = dry_spell_frequency(pr=pr, op="max")
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op="<",
        window=window,
        win_reducer=op,
        spell_reducer="count",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(pr="[precipitation]", thresh="[length]")
def dry_spell_total_length(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 3,
    op: Literal["sum", "max", "min", "mean"] = "sum",
    freq: str = "YS",
    resample_before_rl: bool = True,
    **indexer,
) -> xarray.DataArray:
    r"""
    Total length of dry spells.

    The total number of days in dry periods of a minimum length, during which the maximum or
    accumulated precipitation within a window of the same length is under a given threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Accumulated precipitation value under which a period is considered dry.
    window : int
        Number of days when the maximum or accumulated precipitation is under the threshold.
    op : {"sum", "max", "min", "mean"}
        Operation to perform on the window.
        Default is "sum", which checks that the sum of accumulated precipitation over the whole window
        is less than the threshold.
        "max" checks that the maximal daily precipitation amount within the window is less than the threshold.
        This is the same as verifying that each individual day is below the threshold.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run length encoding
        (or a similar algorithm) is applied to runs.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the dry days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} total number of days in dry periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Notes
    -----
    The algorithm assumes days before and after the timeseries are "wet", meaning that the condition for being
    considered part of a dry spell is stricter on the edges. For example, with `window=3` and `op='sum'`, the first day
    of the series is considered part of a dry spell only if the accumulated precipitation within the first three days is
    under the threshold. In comparison, a day in the middle of the series is considered part of a dry spell if any of
    the three 3-day periods of which it is part are considered dry (so a total of five days are included in the
    computation, compared to only three).
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op="<",
        window=window,
        win_reducer=op,
        spell_reducer="sum",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(pr="[precipitation]", thresh="[length]")
def dry_spell_max_length(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 1,
    op: Literal["max", "sum"] = "sum",
    freq: str = "YS",
    resample_before_rl: bool = True,
    **indexer,
) -> xarray.DataArray:
    r"""
    Longest dry spell.

    The maximum number of consecutive days in a dry period of minimum length, during which the maximum or
    accumulated precipitation within a window of the same length is under a threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Accumulated precipitation value under which a period is considered dry.
    window : int
        Number of days when the maximum or accumulated precipitation is under the threshold.
    op : {"max", "sum"}
        Reduce operation.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run
        length encoding (or a similar algorithm) is applied to runs.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the dry days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} longest spell in dry periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Notes
    -----
    The algorithm assumes days before and after the timeseries are "wet", meaning that the condition for being
    considered part of a dry spell is stricter on the edges. For example, with `window=3` and `op='sum'`,
    the first day of the series is considered part of a dry spell only if the accumulated precipitation within
    the first three days is under the threshold. In comparison, a day in the middle of the series is considered
    part of a dry spell if any of the three 3-day periods of which it is part are considered dry
    (so a total of five days are included in the computation, compared to only three).
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op="<",
        window=window,
        win_reducer=op,
        spell_reducer="max",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(pr="[precipitation]", thresh="[length]")
def wet_spell_frequency(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 3,
    freq: str = "YS",
    resample_before_rl: bool = True,
    op: Literal["sum", "min", "max", "mean"] = "sum",
    **indexer,
) -> xarray.DataArray:
    r"""
    Return the number of wet periods of n days and more.

    Periods during which the accumulated, minimal, or maximal daily precipitation amount within a window
    of n days is over a given threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Precipitation amount over which a period is considered dry.
        The value against which the threshold is compared depends on `op`.
    window : int
        Minimum length of the spells.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run length encoding
        (or a similar algorithm) is applied to runs.
    op : {"sum", "min", "max", "mean"}
        Operation to perform on the window.
        Default is "sum", which checks that the sum of accumulated precipitation over the whole window is
        more than the threshold.
        "min" checks that the maximal daily precipitation amount within the window is more than the threshold.
        This is the same as verifying that each individual day is above the threshold.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the wet days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [unitless]
        The {freq} number of wet periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Examples
    --------
    >>> from xclim.indices import wet_spell_frequency
    >>> pr = xr.open_dataset(path_to_pr_file).pr
    >>> dsf_sum = wet_spell_frequency(pr=pr, op="sum")
    >>> dsf_min = wet_spell_frequency(pr=pr, op="min")
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op=">=",
        window=window,
        win_reducer=op,
        spell_reducer="count",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(pr="[precipitation]", thresh="[length]")
def wet_spell_total_length(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 3,
    op: Literal["min", "sum", "max", "mean"] = "sum",
    freq: str = "YS",
    resample_before_rl: bool = True,
    **indexer,
) -> xarray.DataArray:
    r"""
    Total length of wet spells.

    Total number of days in wet periods of a minimum length, during which the minimum or
    accumulated precipitation within a window of the same length is over a threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Accumulated precipitation value over which a period is considered wet.
    window : int
        Number of days when the maximum or accumulated precipitation is over the threshold.
    op : {"min", "sum", "max", "mean"}
        Reduce operation.
        `min` means that all days within the minimum window must exceed the threshold.
        `sum` means that the accumulated precipitation within the window must exceed the threshold.
        In all cases, the whole window is marked a part of a wet spell.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run length encoding
        (or a similar algorithm) is applied to runs.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the wet days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} total number of days in wet periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Notes
    -----
    The algorithm assumes days before and after the timeseries are "dry", meaning that the condition for being
    considered part of a wet spell is stricter on the edges. For example, with `window=3` and `op='sum'`, the first day
    of the series is considered part of a wet spell only if the accumulated precipitation within the first three days is
    over the threshold. In comparison, a day in the middle of the series is considered part of a wet spell if any of
    the three 3-day periods of which it is part are considered wet (so a total of five days are included in the
    computation, compared to only three).
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op=">=",
        window=window,
        win_reducer=op,
        spell_reducer="sum",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(pr="[precipitation]", thresh="[length]")
def wet_spell_max_length(
    pr: xarray.DataArray,
    thresh: Quantified = "1.0 mm",
    window: int = 1,
    op: Literal["min", "sum", "max", "mean"] = "sum",
    freq: str = "YS",
    resample_before_rl: bool = True,
    **indexer,
) -> xarray.DataArray:
    r"""
    Longest wet spell.

    The maximum number of consecutive days in a wet period of minimum length, during which the minimum or
    accumulated precipitation within a window of the same length is over a threshold.

    Parameters
    ----------
    pr : xarray.DataArray
        Daily precipitation.
    thresh : Quantified
        Accumulated precipitation value over which a period is considered wet.
    window : int
        Number of days when the maximum or accumulated precipitation is over threshold.
    op : {"min", "sum", "max", "mean"}
        Reduce operation.
        `min` means that all days within the minimum window must exceed the threshold.
        `sum` means that the accumulated precipitation within the window must exceed the threshold.
        In all cases, the whole window is marked a part of a wet spell.
    freq : str
        Resampling frequency.
    resample_before_rl : bool
        Determines if the resampling should take place before or after the run length encoding
        (or a similar algorithm) is applied to runs.
    **indexer : {dim: indexer}, optional
        Indexing parameters to compute the indicator on a temporal subset of the data.
        It accepts the same arguments as :py:func:`xclim.indices.generic.select_time`.
        Indexing is done after finding the wet days, but before finding the spells.

    Returns
    -------
    xarray.DataArray, [days]
        The {freq} longest spell in wet periods of minimum {window} days.

    See Also
    --------
    xclim.indices.generic.spell_length_statistics : The parent function that computes the spell length statistics.

    Notes
    -----
    The algorithm assumes days before and after the timeseries are "dry", meaning that the condition for being
    considered part of a wet spell is stricter on the edges. For example, with `window=3` and `op='sum'`, the first day
    of the series is considered part of a wet spell only if the accumulated precipitation within the first three days is
    over the threshold. In comparison, a day in the middle of the series is considered part of a wet spell if any of
    the three 3-day periods of which it is part are considered wet (so a total of five days are included in the
    computation, compared to only three).
    """
    pram = rate2amount(convert_units_to(pr, "mm/d", context="hydro"), out_units="mm")
    return spell_length_statistics(
        pram,
        threshold=thresh,
        op=">=",
        window=window,
        win_reducer=op,
        spell_reducer="max",
        freq=freq,
        resample_before_rl=resample_before_rl,
        **indexer,
    )


@declare_units(
    snd="[length]",
    prsn="[precipitation]",
    snd_thresh="[length]",
    prsn_thresh="[length]",
)
def holiday_snow_days(
    snd: xarray.DataArray,
    snd_thresh: Quantified = "20 mm",
    op: Literal[">", "gt", ">=", "ge"] = ">=",
    date_start: str = "12-25",
    date_end: str | None = None,
    freq: str = "YS",
) -> xarray.DataArray:  # numpydoc ignore=SS05
    """
    Christmas Days.

    Whether there is a significant amount of snow on the ground on December 25th (or a given date range).

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow depth.
    snd_thresh : Quantified
        Threshold snow amount. Default: 20 mm.
    op : {">", "gt", ">=", "ge"}
        Comparison operation. Default: ">=".
    date_start : str
        Beginning of the analysis period. Default: "12-25" (December 25th).
    date_end : str, optional
        End of analysis period. If not provided, `date_start` is used.
        Default: None.
    freq : str
        Resampling frequency. Default: "YS".
        The default value is chosen for the northern hemisphere.

    Returns
    -------
    xarray.DataArray, [bool]
        Boolean array of years with Christmas Days.

    References
    ----------
    https://www.canada.ca/en/environment-climate-change/services/weather-general-tools-resources/historical-christmas-snowfall-data.html
    """
    snd_constrained = select_time(
        snd,
        date_bounds=(date_start, date_start if date_end is None else date_end),
    )

    xmas_days = count_occurrences(snd_constrained, snd_thresh, freq, op, constrain=[">=", ">"])

    xmas_days = to_agg_units(xmas_days, snd, "count", deffreq="D")
    return xmas_days


@declare_units(
    snd="[length]",
    prsn="[precipitation]",
    snd_thresh="[length]",
    prsn_thresh="[length]",
)
def holiday_snow_and_snowfall_days(
    snd: xarray.DataArray,
    prsn: xarray.DataArray | None = None,
    snd_thresh: Quantified = "20 mm",
    prsn_thresh: Quantified = "1 mm",
    snd_op: Literal[">", "gt", ">=", "ge"] = ">=",
    prsn_op: Literal[">", "gt", ">=", "ge"] = ">=",
    date_start: str = "12-25",
    date_end: str | None = None,
    freq: str = "YS-JUL",
) -> xarray.DataArray:
    r"""
    Perfect Christmas Days.

    Whether there is a significant amount of snow on the ground and measurable snowfall occurring on December 25th.

    Parameters
    ----------
    snd : xarray.DataArray
        Surface snow depth.
    prsn : xarray.DataArray
        Snowfall flux.
    snd_thresh : Quantified
        Threshold snow amount. Default: 20 mm.
    prsn_thresh : Quantified
        Threshold daily snowfall liquid-water equivalent thickness. Default: 1 mm.
    snd_op : {">", "gt", ">=", "ge"}
        Comparison operation for snow depth. Default: ">=".
    prsn_op : {">", "gt", ">=", "ge"}
        Comparison operation for snowfall flux. Default: ">=".
    date_start : str
        Beginning of analysis period. Default: "12-25" (December 25th).
    date_end : str, optional
        End of analysis period. If not provided, `date_start` is used.
        Default: None.
    freq : str
        Resampling frequency. Default: "YS-JUL".
        The default value is chosen for the northern hemisphere.

    Returns
    -------
    xarray.DataArray, [int]
        The total number of days with snow and snowfall during the holiday.

    References
    ----------
    https://www.canada.ca/en/environment-climate-change/services/weather-general-tools-resources/historical-christmas-snowfall-data.html
    """
    snd_constrained = select_time(
        snd,
        date_bounds=(date_start, date_start if date_end is None else date_end),
    )

    prsn_mm = rate2amount(convert_units_to(prsn, "mm day-1", context="hydro"), out_units="mm")
    prsn_mm_constrained = select_time(
        prsn_mm,
        date_bounds=(date_start, date_start if date_end is None else date_end),
    )

    perfect_xmas_days = bivariate_count_occurrences(
        data_var1=snd_constrained,
        data_var2=prsn_mm_constrained,
        threshold_var1=snd_thresh,
        threshold_var2=prsn_thresh,
        op_var1=snd_op,
        op_var2=prsn_op,
        freq=freq,
        var_reducer="all",
        constrain_var1=[">=", ">"],
        constrain_var2=[">=", ">"],
    )

    perfect_xmas_days = to_agg_units(perfect_xmas_days, snd, "count", deffreq="D")
    return perfect_xmas_days
