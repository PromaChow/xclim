"""Conversion and approximation functions."""

from __future__ import annotations

from typing import cast

import numpy as np
import xarray as xr
from numba import vectorize

from xclim.core import Quantified
from xclim.core.units import (
    amount2rate,
    convert_units_to,
    declare_units,
    flux2rate,
    rate2flux,
    units2pint,
)
from xclim.indices.helpers import (
    _gather_lat,
    _gather_lon,
    cosine_of_solar_zenith_angle,
    day_lengths,
    distance_from_sun,
    extraterrestrial_solar_radiation,
    solar_declination,
    time_correction_for_solar_angle,
    wind_speed_height_conversion,
)

__all__ = [
    "clausius_clapeyron_scaled_precipitation",
    "clearness_index",
    "dewpoint_from_specific_humidity",
    "fao_allen98",
    "heat_index",
    "humidex",
    "longwave_upwelling_radiation_from_net_downwelling",
    "mean_radiant_temperature",
    "potential_evapotranspiration",
    "prsn_to_prsnd",
    "prsnd_to_prsn",
    "rain_approximation",
    "relative_humidity",
    "saturation_vapor_pressure",
    "sfcwind_to_uas_vas",
    "shortwave_downwelling_radiation_from_clearness_index",
    "shortwave_upwelling_radiation_from_net_downwelling",
    "snd_to_snw",
    "snowfall_approximation",
    "snw_to_snd",
    "specific_humidity",
    "specific_humidity_from_dewpoint",
    "tas",
    "uas_vas_to_sfcwind",
    "universal_thermal_climate_index",
    "vapor_pressure",
    "vapor_pressure_deficit",
    "wind_chill_index",
    "wind_power_potential",
    "wind_profile",
]


@declare_units(tas="[temperature]", tdps="[temperature]", hurs="[]")
def humidex(
    tas: xr.DataArray,
    tdps: xr.DataArray | None = None,
    hurs: xr.DataArray | None = None,
) -> xr.DataArray:
    r"""
    Humidex Index.

    The Humidex indicates how hot the air feels to an average person, accounting for the effect of humidity.
    It can be loosely interpreted as the equivalent perceived temperature when the air is dry.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean Temperature.
    tdps : xarray.DataArray, optional
        Dewpoint Temperature, used to compute the vapour pressure.
    hurs : xarray.DataArray, optional
        Relative Humidity, used as an alternative way to compute the vapour pressure if the dewpoint
        temperature is not available.

    Returns
    -------
    xarray.DataArray, [temperature]
      The Humidex Index.

    Notes
    -----
    The humidex is usually computed using hourly observations of dry bulb and dewpoint temperatures. It is computed
    using the formula based on :cite:t:`masterton_humidex_1979`:

    .. math::

       T + {\frac {5}{9}}\left[e - 10\right]

    where :math:`T` is the dry bulb air temperature (°C). The term :math:`e` can be computed from the dewpoint
    temperature :math:`T_{dewpoint}` in °K:

    .. math::

       e = 6.112 \times \exp(5417.7530\left({\frac {1}{273.16}}-{\frac {1}{T_{\text{dewpoint}}}}\right)

    where the constant 5417.753 reflects the molecular weight of water, latent heat of vaporization,
    and the universal gas constant :cite:p:`mekis_observed_2015`.
    Alternatively, the term :math:`e` can also be computed from the relative humidity `h` expressed
    in percent using :cite:t:`sirangelo_combining_2020`:

    .. math::

       e = \frac{h}{100} \times 6.112 * 10^{7.5 T/(T + 237.7)}.

    The humidex *comfort scale* :cite:p:`canada_glossary_2011` can be interpreted as follows:

    - 20 to 29 : no discomfort;
    - 30 to 39 : some discomfort;
    - 40 to 45 : great discomfort, avoid exertion;
    - 46 and over : dangerous, possible heat stroke;

    Please note that while both the humidex and the heat index are calculated using dew point, the humidex uses
    a dew point of 7 °C (45 °F) as a base, whereas the heat index uses a dew point base of 14 °C (57 °F). Further,
    the heat index uses heat balance equations which account for many variables other than vapour pressure,
    which is used exclusively in the humidex calculation.

    References
    ----------
    :cite:cts:`canada_glossary_2011,masterton_humidex_1979,mekis_observed_2015,sirangelo_combining_2020`
    """
    if (tdps is None) and (hurs is None):
        raise ValueError("At least one of `tdps` or `hurs` must be given.")

    # Vapour pressure in hPa
    if tdps is not None:
        # Convert dewpoint temperature to Kelvins
        tdps = convert_units_to(tdps, "kelvin")
        e = 6.112 * np.exp(5417.7530 * (1 / 273.16 - 1.0 / tdps))

    elif hurs is not None:
        # Convert dry bulb temperature to Celsius
        tasC = convert_units_to(tas, "celsius")
        hurs = convert_units_to(hurs, "%")
        e = hurs / 100 * 6.112 * 10 ** (7.5 * tasC / (tasC + 237.7))

    else:
        raise ValueError("Either `tdps` or `hurs` must be provided.")

    # Temperature delta due to humidity in delta_degC
    h: xr.DataArray = 5 / 9 * (e - 10)
    h = h.assign_attrs(units="delta_degree_Celsius")

    # Get delta_units for output
    du = (1 * units2pint(tas) - 0 * units2pint(tas)).units
    h = convert_units_to(h, du)

    # Add the delta to the input temperature
    out = h + tas
    out = out.assign_attrs(units=tas.units)
    return out


@declare_units(tas="[temperature]", hurs="[]")
def heat_index(tas: xr.DataArray, hurs: xr.DataArray) -> xr.DataArray:
    r"""
    Heat index.

    Perceived temperature after relative humidity is taken into account :cite:p:`blazejczyk_comparison_2012`.
    The index is only valid for temperatures above 20°C.

    Parameters
    ----------
    tas : xr.DataArray
        Mean Temperature. The equation assumes an instantaneous value.
    hurs : xr.DataArray
        Relative Humidity. The equation assumes an instantaneous value.

    Returns
    -------
    xr.DataArray, [temperature]
        Heat index for moments with temperature above 20°C.

    Notes
    -----
    While both the Humidex and the heat index are calculated using dew point the Humidex uses a dew point of 7 °C
    (45 °F) as a base, whereas the heat index uses a dew point base of 14 °C (57 °F). Further, the heat index uses
    heat balance equations which account for many variables other than vapour pressure, which is used exclusively in the
    Humidex calculation.

    References
    ----------
    :cite:cts:`blazejczyk_comparison_2012`
    """
    thresh = 20  # degC
    t = convert_units_to(tas, "degC")
    t = t.where(t > thresh)
    r = convert_units_to(hurs, "%")

    out = (
        -8.78469475556
        + 1.61139411 * t
        + 2.33854883889 * r
        - 0.14611605 * t * r
        - 0.012308094 * t * t
        - 0.0164248277778 * r * r
        + 0.002211732 * t * t * r
        + 0.00072546 * t * r * r
        - 0.000003582 * t * t * r * r
    )
    out = out.assign_attrs(units="degC")
    return convert_units_to(out, tas.units)


@declare_units(tasmin="[temperature]", tasmax="[temperature]")
def tas(tasmin: xr.DataArray, tasmax: xr.DataArray) -> xr.DataArray:
    """
    Average temperature from minimum and maximum temperatures.

    We assume a symmetrical distribution for the temperature and retrieve the average value as Tg = (Tx + Tn) / 2.

    Parameters
    ----------
    tasmin : xarray.DataArray
        Minimum (daily) Temperature.
    tasmax : xarray.DataArray
        Maximum (daily) Temperature.

    Returns
    -------
    xarray.DataArray
        Mean (daily) Temperature [same units as tasmin].

    Examples
    --------
    >>> from xclim.indices import tas
    >>> tas = tas(tasmin_dataset, tasmax_dataset)
    """
    tasmax = convert_units_to(tasmax, tasmin)
    tas = (tasmax + tasmin) / 2
    tas.attrs["units"] = tasmin.attrs["units"]
    return tas


@declare_units(uas="[speed]", vas="[speed]", calm_wind_thresh="[speed]")
def uas_vas_to_sfcwind(
    uas: xr.DataArray, vas: xr.DataArray, calm_wind_thresh: Quantified = "0.5 m/s"
) -> tuple[xr.DataArray, xr.DataArray]:
    """
    Wind speed and direction from the eastward and northward wind components.

    Computes the magnitude and angle of the wind vector from its northward and eastward components,
    following the meteorological convention that sets calm wind to a direction of 0° and northerly wind to 360°.

    Parameters
    ----------
    uas : xr.DataArray
        Eastward Wind Velocity.
    vas : xr.DataArray
        Northward Wind Velocity.
    calm_wind_thresh : Quantified
        The threshold under which winds are considered "calm" and for which the direction is set to 0.
        On the Beaufort scale, calm winds are defined as < 0.5 m/s.

    Returns
    -------
    wind : xr.DataArray, [m s-1]
        Wind Velocity.
    wind_from_dir : xr.DataArray, [°]
        Direction from which the wind blows, following the meteorological convention where 360 stands
        for North and 0 for calm winds.

    Notes
    -----
    Winds with a velocity less than `calm_wind_thresh` are given a wind direction of 0°,
    while stronger northerly winds are set to 360°.

    Examples
    --------
    >>> from xclim.indices import uas_vas_to_sfcwind
    >>> sfcWind = uas_vas_to_sfcwind(uas=uas_dataset, vas=vas_dataset, calm_wind_thresh="0.5 m/s")
    """
    # Converts the wind speed to m s-1
    uas = convert_units_to(uas, "m/s")
    vas = convert_units_to(vas, "m/s")
    wind_thresh = convert_units_to(calm_wind_thresh, "m/s")

    # Wind speed is the hypotenuse of "uas" and "vas"
    wind = cast(xr.DataArray, np.hypot(uas, vas))
    wind = wind.assign_attrs(units="m s-1")

    # Calculate the angle
    wind_from_dir_math = np.degrees(np.arctan2(vas, uas))

    # Convert the angle from the mathematical standard to the meteorological standard
    wind_from_dir = (270 - wind_from_dir_math) % 360.0

    # According to the meteorological standard, calm winds must have a direction of 0°
    # while northerly winds have a direction of 360°
    # On the Beaufort scale, calm winds are defined as < 0.5 m/s
    wind_from_dir = xr.where(wind_from_dir.round() == 0, 360, wind_from_dir)
    wind_from_dir = xr.where(wind < wind_thresh, 0, wind_from_dir)
    wind_from_dir.attrs["units"] = "degree"
    return wind, wind_from_dir


@declare_units(sfcWind="[speed]", sfcWindfromdir="[]")
def sfcwind_to_uas_vas(
    sfcWind: xr.DataArray,
    sfcWindfromdir: xr.DataArray,  # noqa
) -> tuple[xr.DataArray, xr.DataArray]:
    """
    Eastward and northward wind components from the wind speed and direction.

    Compute the eastward and northward wind components from the wind speed and direction.

    Parameters
    ----------
    sfcWind : xr.DataArray
        Wind Velocity.
    sfcWindfromdir : xr.DataArray
        Direction from which the wind blows, following the meteorological convention, where "360" denotes "North".

    Returns
    -------
    uas : xr.DataArray, [m s-1]
        Eastward Wind Velocity.
    vas : xr.DataArray, [m s-1]
        Northward Wind Velocity.

    Examples
    --------
    >>> from xclim.indices import sfcwind_to_uas_vas
    >>> uas, vas = sfcwind_to_uas_vas(sfcWind=sfcWind_dataset, sfcWindfromdir=sfcWindfromdir_dataset)
    """
    # Converts the wind speed to m s-1
    sfcWind = convert_units_to(sfcWind, "m/s")  # noqa

    # Converts the wind direction from the meteorological standard to the mathematical standard
    wind_from_dir_math = (-sfcWindfromdir + 270) % 360.0

    # TODO: This commented part should allow us to resample subdaily wind, but needs to be cleaned up and put elsewhere.
    # if resample is not None:
    #     wind = wind.resample(time=resample).mean(dim='time', keep_attrs=True)
    #
    #     # nb_per_day is the number of values each day. This should be calculated
    #     wind_from_dir_math_per_day = wind_from_dir_math.reshape((len(wind.time), nb_per_day))
    #     # Averages the subdaily angles around a circle, i.e. mean([0, 360]) = 0, not 180
    #     wind_from_dir_math = np.concatenate([[degrees(phase(sum(rect(1, radians(d)) for d in angles) / len(angles)))]
    #                                       for angles in wind_from_dir_math_per_day])

    uas = sfcWind * np.cos(np.radians(wind_from_dir_math))
    vas = sfcWind * np.sin(np.radians(wind_from_dir_math))
    uas.attrs["units"] = "m s-1"
    vas.attrs["units"] = "m s-1"
    return uas, vas


ESAT_FORMULAS_COEFFICIENTS = {
    "tetens30": {"water": [610.78, 17.269388, -35.86], "ice": [610.78, 21.8745584, -7.66]},
    "wmo08": {"water": [611.2, 17.62, -30.04], "ice": [611.2, 22.46, -0.54]},
    "buck81": {"water": [611.21, 17.502, -32.19], "ice": [611.15, 22.542, 0.32]},
    "aerk96": {"water": [610.94, 17.625, -30.12], "ice": [611.21, 22.587, 0.7]},
}
r"""Coefficients for the saturation vapor pressure formulas of the Auguste-Roche-Magnus form.

Keys are method names, values are dictionaries with entries for the "water" and "ice" variants of the
coefficients which are given as list of 3 elements :math:`A`, :math:`B` and :math:`C` for the following
saturation vapor pressure equation:

.. math::

   e_{sat} = A e^{B\frac{T - T_0}{T + C}}

Where :math:`T` is the air temperature in K and :math:`T_0` is the freezing temperature, 273.16 K.
"""


def _saturation_vapor_pressure_over_water(tas: xr.DataArray, method: str):
    """Saturation vapor pressure with reference to water."""
    e_sat: xr.DataArray
    if method == "ecmwf":
        method = "buck81"
    if method == "sonntag90":
        e_sat = 100 * np.exp(
            -6096.9385 / tas  # type: ignore
            + 16.635794
            + -2.711193e-2 * tas  # type: ignore
            + 1.673952e-5 * tas**2
            + 2.433502 * np.log(tas)  # numpy's log is ln
        )
    elif method == "goffgratch46":
        Tb = 373.16  # Water boiling temp [K]
        eb = 101325  # e_sat at Tb [Pa]
        e_sat = eb * 10 ** (
            -7.90298 * ((Tb / tas) - 1)  # type: ignore
            + 5.02808 * np.log10(Tb / tas)  # type: ignore
            + -1.3817e-7 * (10 ** (11.344 * (1 - tas / Tb)) - 1)
            + 8.1328e-3 * (10 ** (-3.49149 * ((Tb / tas) - 1)) - 1)  # type: ignore
        )
    elif method == "its90":
        e_sat = np.exp(
            -2836.5744 / tas**2
            + -6028.076559 / tas
            + 19.54263612
            + -2.737830188e-2 * tas
            + 1.6261698e-5 * tas**2
            + 7.0229056e-10 * tas**3
            + -1.8680009e-13 * tas**4
            + 2.7150305 * np.log(tas)
        )
    elif method in ESAT_FORMULAS_COEFFICIENTS:
        A, B, C = ESAT_FORMULAS_COEFFICIENTS[method]["water"]
        e_sat = A * np.exp(B * (tas - 273.16) / (tas + C))
    else:
        valid = ["sonntag90", "goffgratch46", "its90", "ecmwf"] + list(ESAT_FORMULAS_COEFFICIENTS.keys())
        raise ValueError(f"Method {method} is not in {valid}")
    return e_sat


def _saturation_vapor_pressure_over_ice(tas: xr.DataArray, method: str):
    """Saturation vapor pressure with reference to ice."""
    e_sat: xr.DataArray
    if method == "ecmwf":
        method = "aerk96"
    if method in "sonntag90":
        e_sat = 100 * np.exp(
            -6024.5282 / tas  # type: ignore
            + 24.7219
            + 1.0613868e-2 * tas  # type: ignore
            + -1.3198825e-5 * tas**2
            + -0.49382577 * np.log(tas)
        )
    elif method in "goffgratch46":
        Tp = 273.16  # Triple-point temperature [K]
        ep = 611.73  # e_sat at Tp [Pa]
        e_sat = ep * 10 ** (
            -9.09718 * ((Tp / tas) - 1)  # type: ignore
            + -3.56654 * np.log10(Tp / tas)  # type: ignore
            + 0.876793 * (1 - tas / Tp)
        )
    elif method in "its90":
        e_sat = np.exp(
            -5866.6426 / tas
            + 22.32870244
            + 1.39387003e-2 * tas
            + -3.4262402e-5 * tas**2
            + 2.7040955e-8 * tas**3
            + 6.7063522e-1 * np.log(tas)
        )
    elif method in ESAT_FORMULAS_COEFFICIENTS:
        A, B, C = ESAT_FORMULAS_COEFFICIENTS[method]["ice"]
        e_sat = A * np.exp(B * (tas - 273.16) / (tas + C))
    else:
        valid = ["sonntag90", "goffgratch46", "its90", "ecmwf"] + list(ESAT_FORMULAS_COEFFICIENTS.keys())
        raise ValueError(f"Method {method} is not in {valid}")
    return e_sat


@declare_units(tas="[temperature]", ice_thresh="[temperature]", water_thresh="[temperature]")
def saturation_vapor_pressure(
    tas: xr.DataArray,
    ice_thresh: Quantified | None = None,
    method: str = "sonntag90",
    interp_power: float | None = None,
    water_thresh: Quantified = "0 °C",
) -> xr.DataArray:  # noqa: E501
    r"""
    Saturation vapour pressure from temperature.

    Parameters
    ----------
    tas : xr.DataArray
        Mean Temperature.
    ice_thresh : Quantified, optional
        Threshold temperature under which to switch to equations in reference to ice instead of water.
        If None (default) everything is computed with reference to water.
        If given, see `interp_power` for more options.
    method : {"goffgratch46", "sonntag90", "tetens30", "wmo08", "its90", "buck81", "aerk96", "ecmwf"}
        Which saturation vapour pressure formula to use, see notes.
    interp_power : int or None
        Interpolation options for mixing saturation over water and over ice. See notes.
    water_thresh :  Quantified
        When ``interp_power`` is given, this is the threshold temperature above which the formulas
        with reference to water are used.

    Returns
    -------
    xarray.DataArray, [Pa]
        Saturation Vapour Pressure.

    See Also
    --------
    ESAT_FORMULAS_COEFFICIENTS : Coefficients for methods "tetens30", "wmo08", "aerk96" and "buck81".

    Notes
    -----
    In all cases implemented here :math:`log(e_{sat})` is an empirically fitted function (usually a polynomial)
    where coefficients can be different when ice is taken as reference instead of water. Available methods are:

    - "goffgratch46", based on :cite:t:`goff_low-pressure_1946`,
      values and equation taken from :cite:t:`vomel_saturation_2016`.
    - "sonntag90"", taken from :cite:t:`sonntag_important_1990`.
    - "tetens30", based on :cite:t:`tetens_uber_1930`, values and equation taken from :cite:t:`vomel_saturation_2016`.
    - "wmo08", taken from :cite:t:`world_meteorological_organization_guide_2008`.
    - "its90", taken from :cite:t:`hardy_its-90_1998`.
    - "buck81", taken from :cite:t:`buck_new_1981`.
    - "aerk96", corresponds to formulas AERK and AERKi of :cite:t:`alduchov_improved_1996`
    - "ecmwf", taken from :cite:t:`ecwmf_physical_2016`. This uses "buck91" for saturation over water
      and "aerk96" for saturation over ice.

    **Water vs ice**

    This function implements 3 cases:

    - **All water**. When ``interp_power`` is None (default) and ``ice_thresh`` is None (default).
      Formulas use water as a reference. This might lead to relative humidities above 100 % for cold temperatures.
      This is usually what observational products use (:cite:t:`world_meteorological_organization_guide_2008`), and also
      how the dew point of ERA5 is computed.
    - **Binary water-ice transition**. When ``interp_power is None (default) and ``ice_thresh`` is given.
      The formulas with reference to water are used for temperatures above ``ice_thresh`` and the ones with reference
      to ice are used for temperatures equal to or under ``ice_thresh``. Often used in models, this is what MetPy does.
    - **Interpolation between water and ice**. When ``interp_power``, ``ice_thresh`` and ``water_thresh`` are all given,
      formulas with reference to water are used for temperatures above ``water_thresh``, the formulas with reference
      to ice are used for temperatures below ``ice_thresh`` and an interpolation is used in between.

    .. math::

       e_{sat} = \alpha e_{sat(water)}(T) + (1 - \alpha) e_{sat(ice)}(T)

       \alpha = \left(\frac{T - T_i}{T_w - T_i}\right)^{\beta}

    Where :math:`T_{ice}` is ``ice_thresh``, :math:`T_{w}` is ``water_thresh`` and :math:`\beta` is ``interp_power``.

    As a note, a computation resembling what ECMWF's IFS does to compute relative humidity would use:
    ``method = 'ecmwf'``, ``ice_thresh = 250.16 K``, ``water_thresh = 273.16 K`` (default) and ``interp_power = 2``
    (:cite:t:`ecwmf_physical_2016`). Take note, however, that the 2m dew point temperature given by the IFS
    (ERA5, ERA5-Land) is computed with reference to water only.

    References
    ----------
    :cite:cts:`ecwmf_physical_2016,goff_low-pressure_1946,hardy_its-90_1998,sonntag_important_1990,tetens_uber_1930,vomel_saturation_2016,world_meteorological_organization_guide_2008,buck_new_1981,alduchov_improved_1996`

    Examples
    --------
    >>> from xclim.indices import saturation_vapor_pressure
    >>> rh = saturation_vapor_pressure(tas=tas_dataset, ice_thresh="0 degC", method="wmo08")
    """
    # Dropped explicit support of 4 letter codes, but don't want a breaking change
    method = {"TE30": "tetens30", "GG46": "goffgratch46", "SO90": "sonntag90"}.get(method, method)
    method = method.casefold()

    tas = convert_units_to(tas, "K")
    if ice_thresh is None and interp_power is None:
        # all water
        e_sat = _saturation_vapor_pressure_over_water(tas, method)
    elif ice_thresh is not None and interp_power is None:
        # binary case
        thresh = convert_units_to(ice_thresh, "K")
        e_sat_w = _saturation_vapor_pressure_over_water(tas, method)
        e_sat_i = _saturation_vapor_pressure_over_ice(tas, method)
        e_sat = xr.where(tas > thresh, e_sat_w, e_sat_i)
    else:  # ice_thresh is not None and interp_power is not None
        T_w = convert_units_to(water_thresh, "K")
        T_i = convert_units_to(ice_thresh, "K")
        e_sat_w = _saturation_vapor_pressure_over_water(tas, method)
        e_sat_i = _saturation_vapor_pressure_over_ice(tas, method)
        alpha = ((tas - T_i) / (T_w - T_i)) ** interp_power
        e_sat = xr.where(tas < T_i, e_sat_i, xr.where(tas > T_w, e_sat_w, alpha * e_sat_w + (1 - alpha) * e_sat_i))

    e_sat = e_sat.assign_attrs(units="Pa")
    return e_sat


@declare_units(huss="[]", ps="[pressure]")
def vapor_pressure(huss: xr.DataArray, ps: xr.DataArray):
    r"""
    Vapour pressure.

    Computes the water vapour partial pressure in Pa from the specific humidity and the total pressure.

    Parameters
    ----------
    huss : xr.DataArray
        Specific humidity [kg/kg].
    ps : xr.DataArray
        Pressure.

    Returns
    -------
    xr.DataArray, [pressure]
      Water vapour partial pressure.

    Notes
    -----
    The vapour pressure :math:`\epsilon` is computed with:

    .. math::

        e = \frac{pq}{\epsilon\left(1 + q\left(\frac{1}{\epsilon} - 1\right)\right)}

    Where :math:`p` is the pressure, :math:`q` is the specific humidity and :math:`\epsilon` us the ratio of the dry air
    gas constant to the water vapor gas constant : :math:`\frac{R_{dry}}{R_{vapor}} = 0.621981`.
    """
    eps = 0.621981
    e = ps * huss / (eps * (1 + huss * (1 / eps - 1)))
    return e.assign_attrs(units=ps.attrs["units"])


@declare_units(tas="[temperature]", hurs="[]", ice_thresh="[temperature]", water_thresh="[temperature]")
def vapor_pressure_deficit(
    tas: xr.DataArray,
    hurs: xr.DataArray,
    ice_thresh: Quantified | None = None,
    method: str = "sonntag90",
    interp_power: float | None = None,
    water_thresh: Quantified = "0 °C",
) -> xr.DataArray:
    """
    Vapour pressure deficit.

    The measure of the moisture deficit of the air, computed from temperature and relative

    Parameters
    ----------
    tas : xarray.DataArray
        Mean daily temperature.
    hurs : xarray.DataArray
        Relative humidity.
    ice_thresh : Quantified, optional
        Threshold temperature under which to switch to equations in reference to ice instead of water.
        If None (default) everything is computed with reference to water.
    method : {"goffgratch46", "sonntag90", "tetens30", "wmo08", "its90", "ecmwf"}
        Method used to calculate saturation vapour pressure, see notes of :py:func:`saturation_vapor_pressure`.
        Default is "sonntag90".
    interp_power : int or None
        Optional interpolation for mixing saturation vapour pressures computed over water and ice.
        See :py:func:`saturation_vapor_pressure`.
    water_thresh :  Quantified
        When ``interp_power`` is given, this is the threshold temperature above which the formulas with reference
        to water are used.

    Returns
    -------
    xarray.DataArray, [Pa]
        Vapour pressure deficit.

    See Also
    --------
    saturation_vapor_pressure : Vapour pressure at saturation.
    """
    svp = saturation_vapor_pressure(
        tas, ice_thresh=ice_thresh, method=method, interp_power=interp_power, water_thresh=water_thresh
    )

    hurs = convert_units_to(hurs, "%")
    vpd = cast(xr.DataArray, (1 - (hurs / 100)) * svp)

    vpd = vpd.assign_attrs(units=svp.attrs["units"])
    return vpd


@declare_units(
    tas="[temperature]",
    tdps="[temperature]",
    huss="[]",
    ps="[pressure]",
    ice_thresh="[temperature]",
    water_thresh="[temperature]",
)
def relative_humidity(
    tas: xr.DataArray,
    tdps: xr.DataArray | None = None,
    huss: xr.DataArray | None = None,
    ps: xr.DataArray | None = None,
    ice_thresh: Quantified | None = None,
    method: str = "sonntag90",
    interp_power: float | None = None,
    water_thresh: Quantified = "0 °C",
    invalid_values: str = "clip",
) -> xr.DataArray:
    r"""
    Relative humidity.

    Compute relative humidity from temperature and either dewpoint temperature or specific humidity
    and pressure through the saturation vapour pressure.

    Parameters
    ----------
    tas : xr.DataArray
        Mean Temperature.
    tdps : xr.DataArray, optional
        Dewpoint Temperature.
        If specified, overrides `huss` and `ps`.
    huss : xr.DataArray, optional
        Specific Humidity. Must be given if `tdps` is not given.
    ps : xr.DataArray, optional
        Air Pressure. Must be given if `tdps` is not given.
    ice_thresh : Quantified, optional
        Threshold temperature under which to switch to equations in reference to ice instead of water.
        If None (default) everything is computed with reference to water. Does nothing if 'method' is "bohren98".
    method : {"bohren98", "goffgratch46", "sonntag90", "tetens30", "wmo08", "ecmwf"}
        Which method to use, see notes of this function and of :py:func:`saturation_vapor_pressure`.
    interp_power : int or None
        Optional interpolation for mixing saturation vapour pressures computed over water and ice.
        See :py:func:`saturation_vapor_pressure`.
    water_thresh :  Quantified
        When ``interp_power`` is given, this is the threshold temperature above which the formulas with reference
        to water are used.
    invalid_values : {"clip", "mask", None}
        What to do with values outside the 0-100 range. If "clip" (default), clips everything to 0 - 100,
        if "mask", replaces values outside the range by np.nan, and if `None`, does nothing.

    Returns
    -------
    xr.DataArray, [%]
        Relative Humidity.

    Notes
    -----
    In the following, let :math:`T`, :math:`T_d`, :math:`q` and :math:`p` be the temperature,
    the dew point temperature, the specific humidity and the air pressure.

    **For the "bohren98" method** : This method does not use the saturation vapour pressure directly,
    but rather uses an approximation of the ratio of :math:`\frac{e_{sat}(T_d)}{e_{sat}(T)}`.
    With :math:`L` the enthalpy of vaporization of water and :math:`R_w` the gas constant for water vapour,
    the relative humidity is computed as:

    .. math::

       RH = e^{\frac{-L (T - T_d)}{R_wTT_d}}

    From :cite:t:`bohren_atmospheric_1998`, formula taken from :cite:t:`lawrence_relationship_2005`.
    :math:`L = 2.5\times 10^{-6}` J kg-1, exact for :math:`T = 273.15` K, is used.

    **Other methods**: With :math:`w`, :math:`w_{sat}`, :math:`e_{sat}` the mixing ratio,
    the saturation mixing ratio and the saturation vapour pressure.
    If the dewpoint temperature is given, relative humidity is computed as:

    .. math::

       RH = 100\frac{e_{sat}(T_d)}{e_{sat}(T)}

    Otherwise, the specific humidity and the air pressure must be given so relative humidity can be computed as:

    .. math::

       RH = 100\frac{w}{w_{sat}}
       w = \frac{q}{1-q}
       w_{sat} = 0.622\frac{e_{sat}}{P - e_{sat}}

    The methods differ by how :math:`e_{sat}` is computed.
    See the doc of :py:func:`xclim.core.utils.saturation_vapor_pressure`.

    References
    ----------
    :cite:cts:`bohren_atmospheric_1998,lawrence_relationship_2005`

    Examples
    --------
    >>> from xclim.indices import relative_humidity
    >>> rh = relative_humidity(
    ...     tas=tas_dataset,
    ...     tdps=tdps_dataset,
    ...     huss=huss_dataset,
    ...     ps=ps_dataset,
    ...     ice_thresh="0 degC",
    ...     method="wmo08",
    ...     invalid_values="clip",
    ... )
    """
    hurs: xr.DataArray
    if method in ("bohren98", "BA90"):
        if tdps is None:
            raise ValueError("To use method 'bohren98' (BA98), dewpoint must be given.")
        tdps = convert_units_to(tdps, "K")
        tas = convert_units_to(tas, "K")
        L = 2.501e6
        Rw = (461.5,)
        hurs = 100 * np.exp(-L * (tas - tdps) / (Rw * tas * tdps))  # type: ignore
    elif tdps is not None:
        e_sat_dt = saturation_vapor_pressure(
            tas=tdps, ice_thresh=ice_thresh, method=method, interp_power=interp_power, water_thresh=water_thresh
        )
        e_sat_t = saturation_vapor_pressure(
            tas=tas, ice_thresh=ice_thresh, method=method, interp_power=interp_power, water_thresh=water_thresh
        )
        hurs = 100 * e_sat_dt / e_sat_t  # type: ignore
    elif huss is not None and ps is not None:
        ps = convert_units_to(ps, "Pa")
        huss = convert_units_to(huss, "")
        tas = convert_units_to(tas, "K")

        e_sat = saturation_vapor_pressure(
            tas=tas, ice_thresh=ice_thresh, method=method, interp_power=interp_power, water_thresh=water_thresh
        )

        w = huss / (1 - huss)
        w_sat = 0.62198 * e_sat / (ps - e_sat)  # type: ignore
        hurs = 100 * w / w_sat
    else:
        raise ValueError("`huss` and `ps` must be provided if `tdps` is not given.")

    if invalid_values == "clip":
        hurs = hurs.clip(0, 100)
    elif invalid_values == "mask":
        hurs = hurs.where((hurs <= 100) & (hurs >= 0))
    hurs = hurs.assign_attrs(units="%")
    return hurs


@declare_units(
    tas="[temperature]", hurs="[]", ps="[pressure]", ice_thresh="[temperature]", water_thresh="[temperature]"
)
def specific_humidity(
    tas: xr.DataArray,
    hurs: xr.DataArray,
    ps: xr.DataArray,
    ice_thresh: Quantified | None = None,
    method: str = "sonntag90",
    interp_power: float | None = None,
    water_thresh: Quantified = "0 °C",
    invalid_values: str | None = None,
) -> xr.DataArray:
    r"""
    Specific humidity from temperature, relative humidity, and pressure.

    Specific humidity is the ratio between the mass of water vapour
    and the mass of moist air :cite:p:`world_meteorological_organization_guide_2008`.

    Parameters
    ----------
    tas : xr.DataArray
        Mean Temperature.
    hurs : xr.DataArray
        Relative Humidity.
    ps : xr.DataArray
        Air Pressure.
    ice_thresh : Quantified, optional
        Threshold temperature under which to switch to equations in reference to ice instead of water.
        If None (default) everything is computed with reference to water.
    method : {"goffgratch46", "sonntag90", "tetens30", "wmo08", "ecmwf"}
        Which method to use, see notes of this function and of :py:func:`saturation_vapor_pressure`.
    interp_power : int or None
        Optional interpolation for mixing saturation vapour pressures computed over water and ice.
        See :py:func:`saturation_vapor_pressure`.
    water_thresh :  Quantified
        When ``interp_power`` is given, this is the threshold temperature above which the formulas with reference
        to water are used.
    invalid_values : {"clip", "mask", None}
        What to do with values larger than the saturation specific humidity and lower than 0.
        If "clip" (default), clips everything to 0 - q_sat
        if "mask", replaces values outside the range by np.nan,
        if None, does nothing.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Specific Humidity.

    Notes
    -----
    In the following, let :math:`T`, :math:`hurs` (in %) and :math:`p` be the temperature,
    the relative humidity and the air pressure. With :math:`w`, :math:`w_{sat}`, :math:`e_{sat}` the mixing ratio,
    the saturation mixing ratio and the saturation vapour pressure, specific humidity :math:`q` is computed as:

    .. math::

       w_{sat} = 0.622\frac{e_{sat}}{P - e_{sat}}
       w = w_{sat} * hurs / 100
       q = w / (1 + w)

    The methods differ by how :math:`e_{sat}` is computed. See :py:func:`xclim.core.utils.saturation_vapor_pressure`.

    If `invalid_values` is not `None`, the saturation specific humidity :math:`q_{sat}` is computed as:

    .. math::

       q_{sat} = w_{sat} / (1 + w_{sat})

    References
    ----------
    :cite:cts:`world_meteorological_organization_guide_2008`

    Examples
    --------
    >>> from xclim.indices import specific_humidity
    >>> rh = specific_humidity(
    ...     tas=tas_dataset,
    ...     hurs=hurs_dataset,
    ...     ps=ps_dataset,
    ...     ice_thresh="0 degC",
    ...     method="wmo08",
    ...     invalid_values="mask",
    ... )
    """
    ps = convert_units_to(ps, "Pa")
    hurs = convert_units_to(hurs, "")
    tas = convert_units_to(tas, "K")

    e_sat = saturation_vapor_pressure(
        tas=tas, ice_thresh=ice_thresh, method=method, interp_power=interp_power, water_thresh=water_thresh
    )

    w_sat = 0.621981 * e_sat / (ps - e_sat)  # type: ignore
    w = w_sat * hurs
    q: xr.DataArray = w / (1 + w)

    if invalid_values is not None:
        q_sat = w_sat / (1 + w_sat)
        if invalid_values == "clip":
            q = q.clip(0, q_sat)
        elif invalid_values == "mask":
            q = q.where((q <= q_sat) & (q >= 0))
    q = q.assign_attrs(units="")
    return q


@declare_units(tdps="[temperature]", ps="[pressure]", ice_thresh="[temperature]", water_thresh="[temperature]")
def specific_humidity_from_dewpoint(
    tdps: xr.DataArray,
    ps: xr.DataArray,
    ice_thresh: Quantified | None = None,
    method: str = "sonntag90",
    interp_power: float | None = None,
    water_thresh: Quantified = "0 °C",
) -> xr.DataArray:
    r"""
    Specific humidity from dewpoint temperature and air pressure.

    Specific humidity is the ratio between the mass of water vapour
    and the mass of moist air :cite:p:`world_meteorological_organization_guide_2008`.

    Parameters
    ----------
    tdps : xr.DataArray
        Dewpoint Temperature.
    ps : xr.DataArray
        Air Pressure.
    ice_thresh : Quantified, optional
        Threshold temperature under which to switch to saturated vapour pressure equations
        in reference to ice instead of water. See :py:func:`saturation_vapor_pressure`.
    method : {"goffgratch46", "sonntag90", "tetens30", "wmo08", "buck81", "aerk96", "ecmwf"}
        Method to compute the saturation vapour pressure.
    interp_power : int or None
        Optional interpolation for mixing saturation vapour pressures computed over water and ice.
        See :py:func:`saturation_vapor_pressure`.
    water_thresh :  Quantified
        When ``interp_power`` is given, this is the threshold temperature above which the formulas with reference
        to water are used.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Specific Humidity.

    Notes
    -----
    If :math:`e` is the water vapour pressure, and :math:`p` the total air pressure, then specific humidity is given by

    .. math::

       q = m_w e / ( m_a (p - e) + m_w e )

    where :math:`m_w` and :math:`m_a` are the molecular weights of water and dry air respectively. This formula is often
    written with :math:`ε = m_w / m_a`, which simplifies to :math:`q = ε e / (p - e (1 - ε))`.

    References
    ----------
    :cite:cts:`world_meteorological_organization_guide_2008`

    Examples
    --------
    >>> from xclim.indices import specific_humidity_from_dewpoint
    >>> rh = specific_humidity_from_dewpoint(
    ...     tdps=tas_dataset,
    ...     ps=ps_dataset,
    ...     method="wmo08",
    ... )
    """
    EPSILON = 0.621981  # molar weight of water vs dry air []
    e = saturation_vapor_pressure(
        tas=tdps, method=method, ice_thresh=ice_thresh, interp_power=interp_power, water_thresh=water_thresh
    )  # vapour pressure [Pa]
    ps = convert_units_to(ps, "Pa")  # total air pressure

    q: xr.DataArray = EPSILON * e / (ps - e * (1 - EPSILON))
    q = q.assign_attrs(units="")
    return q


@declare_units(huss="[]", ps="[pressure]")
def dewpoint_from_specific_humidity(
    huss: xr.DataArray, ps: xr.DataArray, method: str = "buck81", variant: str = "water"
):
    r"""
    Dewpoint temperature computed from specific humidity and pressure.

    The temperature at which the current vapour pressure would be the saturation vapour pressure.
    Only a subset of the :py:func:`saturation_vapor_pressure` methods are supported.

    Parameters
    ----------
    huss : xr.DataArray
        Specific humidity [kg/kg].
    ps : xr.DataArray
        Pressure.
    method : {'tetens30', 'wmo08', 'aerk96', 'buck81'}
        The formula to use for saturation vapour pressure.
        Only the formulas using the easily invertible August-Roche-Magnus form are available.
    variant : {'water', 'ice'}
        Which variant of the saturation vapour pressure formula to take.

    Returns
    -------
    xr.DataArray, [temperature]
        Dewpoint temperature.

    See Also
    --------
    saturation_vapor_pressure: Computations of the saturation vapour pressure with more notes.
    ESAT_FORMULAS_COEFFICIENTS: Coefficients of the August-Roche-Magnus form equation for saturation vapour pressure.

    Notes
    -----
    The calculation is based on the following, using the August-Roche-Magnus form
    for the saturation vapour pressure formula :

    .. math::

       e(q, p) = e_{sat}(T_d) = A \mathrm{e}^{B * \frac{T_d - T_0}{T_d + C}}}

       T_d = \frac{-T_0 - C\frac{1}{B}\mathrm{ln}\frac{e}{A}}{\frac{1}{B}\mathrm{ln}\frac{e}{A} - 1}

    Where :math:`e` is the :py:func:`vapor_pressure`, :math:`q` is the specific humidiy, :math:`p` is the pressure,
    :math:`e_{sat}` is the :py:func:`saturation_vapor_pressure`, :math:`T_0` is the freezing temperature 273.16 K and
    :math:`T_d` is the dewpoint temperature. :math:`A`, :math:`B` and :math:`C` are method-specific and
    variant-specific coefficients.

    To imitate the calculations of ECMWF's IFS (ERA5, ERA5-Land), use ``method='buck81'``
    and ``reference='water'`` (the defaults).
    """
    # To avoid 0 in log below, we mask points with no water vapour at all
    huss = huss.where(huss > 0)
    e = vapor_pressure(huss, ps)

    method = method.casefold()
    A, B, C = ESAT_FORMULAS_COEFFICIENTS[method][variant]

    f = np.log(e / A) / B
    tdps = (-273.16 - C * f) / (f - 1)
    return tdps.assign_attrs(units="K", units_metadata="temperature: on_scale")


@declare_units(pr="[precipitation]", tas="[temperature]", thresh="[temperature]")
def snowfall_approximation(
    pr: xr.DataArray,
    tas: xr.DataArray,
    thresh: Quantified = "0 degC",
    method: str = "binary",
) -> xr.DataArray:
    """
    Snowfall approximation from total precipitation and temperature.

    Solid precipitation estimated from precipitation and temperature according to a given method.

    Parameters
    ----------
    pr : xarray.DataArray
        Mean daily Precipitation Flux.
    tas : xarray.DataArray, optional
        Mean, Maximum, or Minimum daily Temperature.
    thresh : Quantified
        Freezing point temperature. Non-scalar values are not allowed with method "brown".
    method : {"binary", "brown", "auer"}
        Which method to use when approximating snowfall from total precipitation. See notes.

    Returns
    -------
    xarray.DataArray, [same units as pr]
        Solid Precipitation Flux.

    See Also
    --------
    rain_approximation : Rainfall approximation from total precipitation and temperature.

    Notes
    -----
    The following methods are available to approximate snowfall and are drawn from the
    Canadian Land Surface Scheme :cite:p:`verseghy_class_2009,melton_atmosphericvarscalcf90_2019`.

    - ``'binary'`` : When the temperature is under the freezing threshold, precipitation
      is assumed to be solid. The method is agnostic to the type of temperature used
      (mean, maximum or minimum).
    - ``'brown'`` : The phase between the freezing threshold goes from solid to liquid linearly
      over a range of 2°C over the freezing point.
    - ``'auer'`` : The phase between the freezing threshold goes from solid to liquid as a degree six
      polynomial over a range of 6°C over the freezing point.

    References
    ----------
    :cite:cts:`verseghy_class_2009,melton_atmosphericvarscalcf90_2019`
    """
    prsn: xr.DataArray
    if method == "binary":
        thresh = convert_units_to(thresh, tas)
        prsn = pr.where(tas <= thresh, 0)

    elif method == "brown":
        if not np.isscalar(thresh):
            raise ValueError("Non-scalar `thresh` are not allowed with method `brown`.")

        # Freezing point + 2C in the native units
        thresh_plus_2 = convert_units_to(thresh, "degC") + 2
        upper = convert_units_to(f"{thresh_plus_2} degC", tas)
        thresh = convert_units_to(thresh, tas)

        # Interpolate fraction over temperature (in units of tas)
        t = xr.DataArray([-np.inf, thresh, upper, np.inf], dims=("tas",), attrs={"units": "degC"})
        fraction = xr.DataArray([1.0, 1.0, 0.0, 0.0], dims=("tas",), coords={"tas": t})

        # Multiply precip by snowfall fraction
        prsn = pr * fraction.interp(tas=tas, method="linear")

    elif method == "auer":
        dtas = convert_units_to(tas, "K") - convert_units_to(thresh, "K")

        # Create nodes for the snowfall fraction: -inf, thresh, ..., thresh+6, inf [degC]
        t = np.concatenate([[-273.15], np.linspace(0, 6, 100, endpoint=False), [6, 1e10]])
        t = xr.DataArray(t, dims="tas", name="tas", coords={"tas": t})

        # The polynomial coefficients, valid between thresh and thresh + 6 (defined in CLASS)
        coeffs = xr.DataArray(
            [100, 4.6664, -15.038, -1.5089, 2.0399, -0.366, 0.0202],
            dims=("degree",),
            coords={"degree": range(7)},
        )

        fraction = xr.polyval(t.tas, coeffs).clip(0, 100) / 100
        fraction[0] = 1
        fraction[-2:] = 0

        # Convert snowfall fraction coordinates to native tas units
        prsn = pr * fraction.interp(tas=dtas, method="linear")

    else:
        raise ValueError(f"Method {method} not one of 'binary', 'brown' or 'auer'.")

    prsn = prsn.assign_attrs(units=pr.attrs["units"])
    return prsn


@declare_units(pr="[precipitation]", tas="[temperature]", thresh="[temperature]")
def rain_approximation(
    pr: xr.DataArray,
    tas: xr.DataArray,
    thresh: Quantified = "0 degC",
    method: str = "binary",
) -> xr.DataArray:
    """
    Rainfall approximation from total precipitation and temperature.

    Liquid precipitation estimated from precipitation and temperature according to a given method.
    This is a convenience method based on :py:func:`snowfall_approximation`, see the latter for details.

    Parameters
    ----------
    pr : xarray.DataArray
        Mean daily Precipitation Flux.
    tas : xarray.DataArray, optional
        Mean, Maximum, or Minimum daily Temperature.
    thresh : Quantified
        Freezing point temperature. Non-scalar values are not allowed with method 'brown'.
    method : {"binary", "brown", "auer"}
        Which method to use when approximating snowfall from total precipitation. See notes.

    Returns
    -------
    xarray.DataArray, [same units as pr]
        Liquid precipitation rate.

    See Also
    --------
    snowfall_approximation : Snowfall approximation from total precipitation and temperature.

    Notes
    -----
    This method computes the snowfall approximation and subtracts it from the total
    precipitation to estimate the liquid rain precipitation.
    """
    prra: xr.DataArray = pr - snowfall_approximation(pr, tas, thresh=thresh, method=method)
    prra = prra.assign_attrs(units=pr.attrs["units"])
    return prra


@declare_units(snd="[length]", snr="[mass]/[volume]", const="[mass]/[volume]")
def snd_to_snw(
    snd: xr.DataArray,
    snr: Quantified | None = None,
    const: Quantified = "312 kg m-3",
    out_units: str | None = None,
) -> xr.DataArray:
    """
    Snow amount from snow depth and density.

    Parameters
    ----------
    snd : xr.DataArray
        Snow Depth.
    snr : Quantified, optional
        Snow Density.
    const : Quantified
        Constant snow density.
        `const` is only used if `snr` is `None`.
    out_units : str, optional
        Desired units of the snow amount output.
        If `None`, output units simply follow from `snd * snr`.

    Returns
    -------
    xr.DataArray
        Snow Amount.

    Notes
    -----
    The estimated mean snow density value of 312 kg m-3 is taken from :cite:t:`sturm_swe_2010`.

    References
    ----------
    :cite:cts:`sturm_swe_2010`
    """
    density = snr if (snr is not None) else const
    snw: xr.DataArray = rate2flux(snd, density=density, out_units=out_units).rename("snw")
    # TODO: Leave this operation to rate2flux? Maybe also the variable renaming above?
    snw = snw.assign_attrs(standard_name="surface_snow_amount")
    return snw


@declare_units(snw="[mass]/[area]", snr="[mass]/[volume]", const="[mass]/[volume]")
def snw_to_snd(
    snw: xr.DataArray,
    snr: Quantified | None = None,
    const: Quantified = "312 kg m-3",
    out_units: str | None = None,
) -> xr.DataArray:
    """
    Snow depth from snow amount and density.

    Parameters
    ----------
    snw : xr.DataArray
        Snow amount.
    snr : Quantified, optional
        Snow density.
    const : Quantified
        Constant snow density.
        `const` is only used if `snr` is `None`.
    out_units : str, optional
        Desired units of the snow depth output. If `None`, output units simply follow from `snw / snr`.

    Returns
    -------
    xr.DataArray
        Snow Depth.

    Notes
    -----
    The estimated mean snow density value of 312 kg m-3 is taken from :cite:t:`sturm_swe_2010`.

    References
    ----------
    :cite:cts:`sturm_swe_2010`
    """
    density = snr if (snr is not None) else const
    snd: xr.DataArray = flux2rate(snw, density=density, out_units=out_units).rename("snd")
    snd = snd.assign_attrs(standard_name="surface_snow_thickness")
    return snd


@declare_units(prsn="[mass]/[area]/[time]", snr="[mass]/[volume]", const="[mass]/[volume]")
def prsn_to_prsnd(
    prsn: xr.DataArray,
    snr: xr.DataArray | None = None,
    const: Quantified = "100 kg m-3",
    out_units: str | None = None,
) -> xr.DataArray:
    """
    Snowfall rate from snowfall flux and density.

    Parameters
    ----------
    prsn : xr.DataArray
        Snowfall Flux.
    snr : xr.DataArray, optional
        Snow Density.
    const : Quantified
        Constant snow density.
        `const` is only used if `snr` is `None`.
    out_units : str, optional
        Desired units of the snowfall rate.
        If `None`, output units simply follow from `snd * snr`.

    Returns
    -------
    xr.DataArray
        Snowfall Rate.

    Notes
    -----
    The estimated mean snow density value of 100 kg m-3 is taken from :cite:cts:`frei_snowfall_2018, cbcl_climate_2020`.

    References
    ----------
    :cite:cts:`frei_snowfall_2018, cbcl_climate_2020`
    """
    density = snr if snr else const
    prsnd: xr.DataArray = flux2rate(prsn, density=density, out_units=out_units).rename("prsnd")
    return prsnd


@declare_units(prsnd="[length]/[time]", snr="[mass]/[volume]", const="[mass]/[volume]")
def prsnd_to_prsn(
    prsnd: xr.DataArray,
    snr: xr.DataArray | None = None,
    const: Quantified = "100 kg m-3",
    out_units: str | None = None,
) -> xr.DataArray:
    """
    Snowfall flux from snowfall rate and density.

    Parameters
    ----------
    prsnd : xr.DataArray
        Snowfall Rate.
    snr : xr.DataArray, optional
        Snow Density.
    const : Quantified
        Constant Snow Density.
        `const` is only used if `snr` is `None`.
    out_units : str, optional
        Desired units of the snowfall rate. If `None`, output units simply follow from `snd * snr`.

    Returns
    -------
    xr.DataArray
        Snowfall Flux.

    Notes
    -----
    The estimated mean snow density value of 100 kg m-3 is taken from :cite:cts:`frei_snowfall_2018, cbcl_climate_2020`.

    References
    ----------
    :cite:cts:`frei_snowfall_2018, cbcl_climate_2020`
    """
    density = snr if snr else const
    prsn: xr.DataArray = rate2flux(prsnd, density=density, out_units=out_units).rename("prsn")
    prsn = prsn.assign_attrs(standard_name="snowfall_flux")
    return prsn


@declare_units(rls="[radiation]", rlds="[radiation]")
def longwave_upwelling_radiation_from_net_downwelling(rls: xr.DataArray, rlds: xr.DataArray) -> xr.DataArray:
    """
    Calculate upwelling thermal radiation from net thermal radiation and downwelling thermal radiation.

    Parameters
    ----------
    rls : xr.DataArray
        Surface net thermal radiation.
    rlds : xr.DataArray
        Surface downwelling thermal radiation.

    Returns
    -------
    xr.DataArray, [same units as rlds]
        Surface upwelling thermal radiation (rlus).
    """
    rls = convert_units_to(rls, rlds)
    rlus: xr.DataArray = rlds - rls
    rlus = rlus.assign_attrs(units=rlds.units)
    return rlus


@declare_units(rss="[radiation]", rsds="[radiation]")
def shortwave_upwelling_radiation_from_net_downwelling(rss: xr.DataArray, rsds: xr.DataArray) -> xr.DataArray:
    """
    Calculate upwelling solar radiation from net solar radiation and downwelling solar radiation.

    Parameters
    ----------
    rss : xr.DataArray
        Surface net solar radiation.
    rsds : xr.DataArray
        Surface downwelling solar radiation.

    Returns
    -------
    xr.DataArray, [same units as rsds]
        Surface upwelling solar radiation (rsus).
    """
    rss = convert_units_to(rss, rsds)
    rsus: xr.DataArray = rsds - rss
    rsus = rsus.assign_attrs(units=rsds.units)
    return rsus


@declare_units(rsds="[radiation]")
def clearness_index(rsds: xr.DataArray) -> xr.DataArray:
    r"""
    Compute the clearness index.

    The clearness index is the ratio between the shortwave downwelling radiation
    and the total extraterrestrial radiation on a given day.

    Parameters
    ----------
    rsds : xr.DataArray
        Surface downwelling solar radiation.

    Returns
    -------
    xr.DataArray, [unitless]
        Clearness index.

    Notes
    -----
    Clearness Index (ci) is defined as:

    .. math :

       ci = rsds / \text{extraterrestrial_solar_radiation}

    References
    ----------
    :cite:cts:`lauret_solar_2022`
    """
    rtop = extraterrestrial_solar_radiation(rsds.time, rsds.lat)
    rtop = convert_units_to(rtop, rsds)
    with xr.set_options(keep_attrs=True):
        ci = xr.where(rsds != 0, rsds / rtop, 0)
    ci = ci.assign_attrs(units="")
    return ci


@declare_units(ci="[]")
def shortwave_downwelling_radiation_from_clearness_index(ci: xr.DataArray) -> xr.DataArray:
    r"""
    Compute the surface downwelling solar radiation from clearness index.

    Parameters
    ----------
    ci : xr.DataArray
        Clearness index.

    Returns
    -------
    xr.DataArray, [unitless]
        Surface downwelling solar radiation.

    See Also
    --------
    clearness_index : Inverse transformation, and definition of the clearness index.

    Notes
    -----
    The conversion from Clearness Index is defined as:

    .. math :

       rsds = ci * \text{extraterrestrial_solar_radiation}
    """
    rtop = extraterrestrial_solar_radiation(ci.time, ci.lat)
    with xr.set_options(keep_attrs=True):
        rsds = (rtop * ci).assign_attrs(units=rtop.units)
    return rsds


@declare_units(
    tas="[temperature]",
    sfcWind="[speed]",
)
def wind_chill_index(
    tas: xr.DataArray,
    sfcWind: xr.DataArray,
    method: str = "CAN",
    mask_invalid: bool = True,
) -> xr.DataArray:
    r"""
    Wind chill index.

    The Wind Chill Index is an estimation of how cold the weather feels to the average person.
    It is computed from the air temperature and the 10-m wind. As defined by the Environment and Climate Change Canada
    (:cite:cts:`mekis_observed_2015`), two equations exist, the conventional one and one for slow winds
    (usually < 5 km/h), see Notes.

    Parameters
    ----------
    tas : xarray.DataArray
        Surface air temperature.
    sfcWind : xarray.DataArray
        Surface wind speed (10 m).
    method : {'CAN', 'US'}
        If "CAN" (default), a "slow wind" equation is used where winds are slower than 5 km/h, see Notes.
    mask_invalid : bool
        Whether to mask values when the inputs are outside their validity range. or not.
        If True (default), points where the temperature is above a threshold are masked.
        The threshold is 0°C for the canadian method and 50°F for the american one.
        With the latter method, points where sfcWind < 3 mph are also masked.

    Returns
    -------
    xarray.DataArray, [degC]
        Wind Chill Index.

    Notes
    -----
    Following the calculations of Environment and Climate Change Canada, this function switches from the standardized
    index to another one for slow winds. The standard index is the same as used by the National Weather Service of the
    USA :cite:p:`us_department_of_commerce_wind_nodate`. Given a temperature at surface :math:`T` (in °C) and 10-m
    wind speed :math:`V` (in km/h), the Wind Chill Index :math:`W` (dimensionless) is computed as:

    .. math::

       W = 13.12 + 0.6125*T - 11.37*V^0.16 + 0.3965*T*V^0.16

    Under slow winds (:math:`V < 5` km/h), and using the canadian method, it becomes:

    .. math::

       W = T + \frac{-1.59 + 0.1345 * T}{5} * V

    Both equations are invalid for temperature over 0°C in the canadian method.

    The american Wind Chill Temperature index (WCT), as defined by USA's National Weather Service, is computed when
    `method='US'`. In that case, the maximal valid temperature is 50°F (10 °C) and minimal wind speed is 3 mph
    (4.8 km/h).

    For more information, see:

    - National Weather Service FAQ: :cite:p:`us_department_of_commerce_wind_nodate`.
    - The New Wind Chill Equivalent Temperature Chart: :cite:p:`osczevski_new_2005`.

    References
    ----------
    :cite:cts:`mekis_observed_2015,us_department_of_commerce_wind_nodate`
    """
    tas = convert_units_to(tas, "degC")
    sfcWind = convert_units_to(sfcWind, "km/h")

    V = sfcWind**0.16
    W: xr.DataArray = 13.12 + 0.6215 * tas - 11.37 * V + 0.3965 * tas * V

    if method.upper() == "CAN":
        W = xr.where(sfcWind < 5, tas + sfcWind * (-1.59 + 0.1345 * tas) / 5, W)
    elif method.upper() != "US":
        raise ValueError(f"`method` must be one of 'US' and 'CAN'. Got '{method}'.")

    if mask_invalid:
        mask = {"CAN": tas <= 0, "US": (sfcWind > 4.828032) & (tas <= 10)}
        W = W.where(mask[method.upper()])

    W = W.assign_attrs(units="degC")
    return W


@declare_units(
    delta_tas="[temperature]",
    pr_baseline="[precipitation]",
)
def clausius_clapeyron_scaled_precipitation(
    delta_tas: xr.DataArray,
    pr_baseline: xr.DataArray,
    cc_scale_factor: float = 1.07,
) -> xr.DataArray:
    r"""
    Scale precipitation according to the Clausius-Clapeyron relation.

    Parameters
    ----------
    delta_tas : xarray.DataArray
        Difference in temperature between a baseline climatology and another climatology.
    pr_baseline : xarray.DataArray
        Baseline precipitation to adjust with Clausius-Clapeyron.
    cc_scale_factor : float
        Clausius Clapeyron scale factor. (default  = 1.07).

    Returns
    -------
    xarray.DataArray
        Baseline precipitation scaled to other climatology using Clausius-Clapeyron relationship.

    Warnings
    --------
    Make sure that `delta_tas` is computed over a baseline compatible with `pr_baseline`. So for example,
    if `delta_tas` is the climatological difference between a baseline and a future period, then `pr_baseline`
    should be precipitations over a period within the same baseline.

    Notes
    -----
    The Clausius-Clapeyron equation for water vapour under typical atmospheric conditions states that the saturation
    water vapour pressure :math:`e_s` changes approximately exponentially with temperature

    .. math::
       \frac{\mathrm{d}e_s(T)}{\mathrm{d}T} \approx 1.07 e_s(T)

    This function assumes that precipitation can be scaled by the same factor.
    """
    # Get difference in temperature.  Time-invariant baseline temperature (from above) is broadcast.
    delta_tas = convert_units_to(delta_tas, "delta_degreeC")

    # Calculate scaled precipitation.
    pr_out: xr.DataArray = pr_baseline * (cc_scale_factor**delta_tas)
    pr_out = pr_out.assign_attrs(units=pr_baseline.attrs["units"])
    return pr_out


def _get_D_from_M(time):  # noqa: N802
    start = time[0].dt.strftime("%Y-%m-01").item()
    yrmn = time[-1].dt.strftime("%Y-%m").item()
    end = f"{yrmn}-{time[-1].dt.daysinmonth.item()}"
    return xr.DataArray(
        xr.date_range(
            start,
            end,
            freq="D",
            calendar=time.dt.calendar,
            use_cftime=(time.dtype == "O"),
        ),
        dims="time",
        name="time",
    )


@declare_units(
    net_radiation="[radiation]",
    tas="[temperature]",
    wind="[speed]",
    es="[pressure]",
    ea="[pressure]",
    delta_svp="[pressure] / [temperature]",
    gamma="[pressure] [temperature]",
    G="[radiation]",
)
def fao_allen98(net_radiation, tas, wind, es, ea, delta_svp, gamma, G="0 MJ m-2 day-1"):
    r"""
    FAO-56 Penman-Monteith equation.

    Estimates reference evapotranspiration from a hypothetical short grass reference surface (
    height = 0.12m, surface resistance = 70 s m-1, albedo  = 0.23 and a ``moderately dry soil surface resulting from
    about a weekly irrigation frequency``).
    Based on equation 6 in based on :cite:t:`allen_crop_1998`.

    Parameters
    ----------
    net_radiation : xarray.DataArray
        Net radiation at crop surface [MJ m-2 day-1].
    tas : xarray.DataArray
        Air temperature at 2 m height [degC].
    wind : xarray.DataArray
        Wind speed at 2 m height [m s-1].
    es : xarray.DataArray
        Saturation vapour pressure [kPa].
    ea : xarray.DataArray
        Actual vapour pressure [kPa].
    delta_svp : xarray.DataArray
        Slope of saturation vapour pressure curve [kPa degC-1].
    gamma : xarray.DataArray
        Psychrometric constant [kPa deg C].
    G : float, optional
        Soil heat flux (G) [MJ m-2 day-1] (For daily default to 0).

    Returns
    -------
    xarray.DataArray
        Potential Evapotranspiration from a hypothetical grass reference surface [mm day-1].

    References
    ----------
    :cite:t:`allen_crop_1998`
    """
    net_radiation = convert_units_to(net_radiation, "MJ m-2 day-1")
    wind = convert_units_to(wind, "m s-1")
    tasK = convert_units_to(tas, "K")
    es = convert_units_to(es, "kPa")
    ea = convert_units_to(ea, "kPa")
    delta_svp = convert_units_to(delta_svp, "kPa degC-1")
    gamma = convert_units_to(gamma, "kPa degC")
    G = convert_units_to(G, "MJ m-2 day-1")
    a1 = 0.408 * delta_svp * (net_radiation - G)
    a2 = gamma * 900 / (tasK) * wind * (es - ea)
    a3 = delta_svp + (gamma * (1 + 0.34 * wind))

    return ((a1 + a2) / a3).assign_attrs(units="mm day-1")


@declare_units(
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
    pr="[precipitation]",
)
def potential_evapotranspiration(
    tasmin: xr.DataArray | None = None,
    tasmax: xr.DataArray | None = None,
    tas: xr.DataArray | None = None,
    lat: xr.DataArray | None = None,
    hurs: xr.DataArray | None = None,
    rsds: xr.DataArray | None = None,
    rsus: xr.DataArray | None = None,
    rlds: xr.DataArray | None = None,
    rlus: xr.DataArray | None = None,
    sfcWind: xr.DataArray | None = None,
    pr: xr.DataArray | None = None,
    method: str = "BR65",
    peta: float = 0.00516409319477,
    petb: float = 0.0874972822289,
) -> xr.DataArray:
    r"""
    Potential evapotranspiration.

    The potential for water evaporation from soil and transpiration by plants if the water supply is sufficient,
    according to a given method.

    Parameters
    ----------
    tasmin : xarray.DataArray, optional
        Minimum daily Temperature.
    tasmax : xarray.DataArray, optional
        Maximum daily Temperature.
    tas : xarray.DataArray, optional
        Mean daily Temperature.
    lat : xarray.DataArray, optional
        Latitude.
        If not provided, it is sought on `tasmin` or `tas` using cf-xarray accessors.
    hurs : xarray.DataArray, optional
        Relative Humidity.
    rsds : xarray.DataArray, optional
        Surface Downwelling Shortwave Radiation.
    rsus : xarray.DataArray, optional
        Surface Upwelling Shortwave Radiation.
    rlds : xarray.DataArray, optional
        Surface Downwelling Longwave Radiation.
    rlus : xarray.DataArray, optional
        Surface Upwelling Longwave Radiation.
    sfcWind : xarray.DataArray, optional
        Surface Wind Velocity (at 10 m).
    pr : xarray.DataArray
        Mean daily Precipitation Flux.
    method : {"baierrobertson65", "BR65", "hargreaves85", "HG85", "thornthwaite48", "TW48", "mcguinnessbordne05", "MB05", "allen98", "FAO_PM98", "droogersallen02", "DA02"}
        Which method to use, see Notes.
    peta : float
        Used only with method MB05 as :math:`a` for calculation of PET, see Notes section.
        Default value resulted from calibration of PET over the UK.
    petb : float
        Used only with method MB05 as :math:`b` for calculation of PET, see Notes section.
        Default value resulted from calibration of PET over the UK.

    Returns
    -------
    xarray.DataArray
        Potential Evapotranspiration.

    Notes
    -----
    Available methods are:

        - "baierrobertson65" or "BR65", based on :cite:t:`baier_estimation_1965`.
          Requires tasmin and tasmax, daily [D] freq.

        - "hargreaves85" or "HG85", based on :cite:t:`george_h_hargreaves_reference_1985`.
          Requires tasmin and tasmax, daily [D] freq. (optional: tas can be given in addition of tasmin and tasmax).

        - "mcguinnessbordne05" or "MB05", based on :cite:t:`tanguy_historical_2018`.
          Requires tas, daily [D] freq, with latitudes 'lat'.

        - "thornthwaite48" or "TW48", based on :cite:t:`thornthwaite_approach_1948`.
          Requires tasmin and tasmax, monthly [MS] or daily [D] freq.
          (optional: tas can be given instead of tasmin and tasmax).

        - "allen98" or "FAO_PM98", based on :cite:t:`allen_crop_1998`. Modification of Penman-Monteith method.
          Requires tasmin and tasmax, relative humidity, radiation flux and wind speed (10 m wind will be converted to 2 m).

        - "droogersallen02" or "DA02", based on :cite:t:`droogers2002`.
          Requires tasmin, tasmax and precipitation, monthly [MS] or daily [D] freq. (optional: tas can be given in addition of tasmin and tasmax).

    The McGuinness-Bordne :cite:p:`mcguinness_comparison_1972` equation is:

    .. math::

       PET[mm day^{-1}] = a * \frac{S_0}{\lambda}T_a + b * \frac{S_0}{\lambda}

    where :math:`a` and :math:`b` are empirical parameters; :math:`S_0` is the extraterrestrial radiation [MJ m-2 day-1],
    assuming a solar constant of 1367 W m-2; :math:`\\lambda` is the latent heat of vaporisation [MJ kg-1]
    and :math:`T_a` is the air temperature [°C]. The equation was originally derived for the USA,
    with :math:`a=0.0147` and :math:`b=0.07353`. The default parameters used here are calibrated for the UK,
    using the method described in :cite:t:`tanguy_historical_2018`.

    Methods "BR65", "HG85", "MB05" and "DA02" use an approximation of the extraterrestrial radiation.
    See :py:func:`~xclim.indices._helpers.extraterrestrial_solar_radiation`.

    References
    ----------
    :cite:cts:`baier_estimation_1965,george_h_hargreaves_reference_1985,tanguy_historical_2018,thornthwaite_approach_1948,mcguinness_comparison_1972,allen_crop_1998,droogers2002`
    """  # noqa: E501
    # ^ Ignoring "line too long" as it comes from un-splittable constructs
    if lat is None:
        _lat = _gather_lat(tasmin if tas is None else tas)
    else:
        _lat = lat

    pet: xr.DataArray
    if method in ["baierrobertson65", "BR65"]:
        _tasmin = convert_units_to(tasmin, "degF")
        _tasmax = convert_units_to(tasmax, "degF")

        re = extraterrestrial_solar_radiation(_tasmin.time, _lat, chunks=_tasmin.chunksizes)
        re = convert_units_to(re, "cal cm-2 day-1")

        # Baier et Robertson(1965) formula
        pet = 0.094 * (-87.03 + 0.928 * _tasmax + 0.933 * (_tasmax - _tasmin) + 0.0486 * re)
        pet = pet.clip(0)

    elif method in ["hargreaves85", "HG85"]:
        _tasmin = convert_units_to(tasmin, "degC")
        _tasmax = convert_units_to(tasmax, "degC")
        if tas is None:
            _tas = (_tasmin + _tasmax) / 2
        else:
            _tas = convert_units_to(tas, "degC")

        ra = extraterrestrial_solar_radiation(_tasmin.time, _lat, chunks=_tasmin.chunksizes)
        ra = convert_units_to(ra, "MJ m-2 d-1")

        # Is used to convert the radiation to evaporation equivalents in mm (kg/MJ)
        ra = ra * 0.408

        # Hargreaves and Samani (1985) formula
        pet = 0.0023 * ra * (_tas + 17.8) * (_tasmax - _tasmin) ** 0.5
        pet = pet.clip(0)

    elif method in ["droogersallen02", "DA02"]:
        _tasmin = convert_units_to(tasmin, "degC")
        _tasmax = convert_units_to(tasmax, "degC")
        _pr = convert_units_to(pr, "mm/month", context="hydro")
        if tas is None:
            _tas = (_tasmin + _tasmax) / 2
        else:
            _tas = convert_units_to(tas, "degC")

        _tasmin = _tasmin.resample(time="MS").mean()
        _tasmax = _tasmax.resample(time="MS").mean()
        _tas = _tas.resample(time="MS").mean()
        _pr = _pr.resample(time="MS").mean()

        # Monthly accumulated radiation
        time_d = _get_D_from_M(_tasmin.time)
        ra = extraterrestrial_solar_radiation(time_d, _lat)
        ra = convert_units_to(ra, "MJ m-2 d-1")
        ra = ra.resample(time="MS").sum()
        # Is used to convert the radiation to evaporation equivalents in mm (kg/MJ)
        ra = ra * 0.408

        tr = _tasmax - _tasmin
        tr = tr.where(tr > 0, 0)

        # Droogers and Allen (2002) formula
        ab = tr - 0.0123 * _pr
        pet = 0.0013 * ra * (_tas + 17.0) * ab**0.76
        pet = xr.where(np.isnan(ab**0.76), 0, pet)
        pet = pet.clip(0)  # mm/month

    elif method in ["mcguinnessbordne05", "MB05"]:
        if tas is None:
            _tasmin = convert_units_to(tasmin, "degC")
            _tasmax = convert_units_to(tasmax, "degC")
            _tas: xr.DataArray = (_tasmin + _tasmax) / 2
            _tas = _tas.assign_attrs(units="degC")
        else:
            _tas = convert_units_to(tas, "degC")

        tasK = convert_units_to(_tas, "K")

        ext_rad = extraterrestrial_solar_radiation(_tas.time, _lat, solar_constant="1367 W m-2", chunks=_tas.chunksizes)
        latentH = 4185.5 * (751.78 - 0.5655 * tasK)
        radDIVlat = ext_rad / latentH

        # parameters from calibration provided by Dr Maliko Tanguy @ CEH
        # (calibrated for PET over the UK)
        a = peta
        b = petb

        pet = radDIVlat * a * _tas + radDIVlat * b

    elif method in ["thornthwaite48", "TW48"]:
        if tas is None:
            _tasmin = convert_units_to(tasmin, "degC")
            _tasmax = convert_units_to(tasmax, "degC")
            _tas = (_tasmin + _tasmax) / 2
        else:
            _tas = convert_units_to(tas, "degC")
        _tas = _tas.clip(0)
        _tas = _tas.resample(time="MS").mean(dim="time")

        # Thornthwaite measures half-days
        time_d = _get_D_from_M(_tas.time)
        dl = day_lengths(time_d, _lat) / 12
        dl_m = dl.resample(time="MS").mean(dim="time")

        # annual heat index
        id_m = (_tas / 5) ** 1.514
        id_y = id_m.resample(time="YS").sum(dim="time")

        tas_idy_a = []
        for base_time, indexes in _tas.resample(time="YS").groups.items():
            tas_y = _tas.isel(time=indexes)
            id_v = id_y.sel(time=base_time)
            a = 6.75e-7 * id_v**3 - 7.71e-5 * id_v**2 + 0.01791 * id_v + 0.49239

            frac = (10 * tas_y / id_v) ** a
            tas_idy_a.append(frac)

        tas_idy_a = xr.concat(tas_idy_a, dim="time")

        # Thornthwaite(1948) formula
        pet = 1.6 * dl_m * tas_idy_a  # cm/month
        pet = 10 * pet  # mm/month

    elif method in ["allen98", "FAO_PM98"]:
        _tasmax = convert_units_to(tasmax, "degC")
        _tasmin = convert_units_to(tasmin, "degC")
        _hurs = convert_units_to(hurs, "1")
        if sfcWind is None:
            raise ValueError("Wind speed is required for Allen98 method.")

        # wind speed at two meters
        wa2 = wind_speed_height_conversion(sfcWind, h_source="10 m", h_target="2 m")
        wa2 = convert_units_to(wa2, "m s-1")

        with xr.set_options(keep_attrs=True):
            # mean temperature [degC]
            tas_m = (_tasmax + _tasmin) / 2
            # mean saturation vapour pressure [kPa]
            es = (1 / 2) * (saturation_vapor_pressure(_tasmax) + saturation_vapor_pressure(_tasmin))
            es = convert_units_to(es, "kPa")
            # mean actual vapour pressure [kPa]
            ea = es * _hurs

            # slope of saturation vapour pressure curve  [kPa degC-1]
            delta = (4098 * es / (tas_m + 237.3) ** 2).assign_attrs(units="kPa degC-1")
            # net radiation
            Rn = convert_units_to(rsds - rsus - (rlus - rlds), "MJ m-2 d-1")

            P = 101.325  # Atmospheric pressure [kPa]
            gamma = 0.665e-03 * P  # psychrometric const = C_p*P/(eps*lam) [kPa degC-1]

            pet = fao_allen98(Rn, tas_m, wa2, es, ea, delta, f"{gamma} kPa degC")

    else:
        raise NotImplementedError(f"'{method}' method is not implemented.")

    pet = pet.assign_attrs(units="mm")
    rate = amount2rate(pet, out_units="mm/d")
    out: xr.DataArray = convert_units_to(rate, "kg m-2 s-1", context="hydro")
    return out


@vectorize
def _utci(tas, sfcWind, dt, wvp):
    """Return the empirical polynomial function for UTCI. See :py:func:`universal_thermal_climate_index`."""
    # Taken directly from the original Fortran code by Peter Bröde.
    # http://www.utci.org/public/UTCI%20Program%20Code/UTCI_a002.f90
    # tas -> Ta (surface temperature, °C)
    # sfcWind -> va (surface wind speed, m/s)
    # dt -> D_Tmrt (tas - t_mrt, K)
    # wvp -> Pa (water vapour partial pressure, kPa)
    return (
        tas
        + 6.07562052e-1
        + -2.27712343e-2 * tas
        + 8.06470249e-4 * tas * tas
        + -1.54271372e-4 * tas * tas * tas
        + -3.24651735e-6 * tas * tas * tas * tas
        + 7.32602852e-8 * tas * tas * tas * tas * tas
        + 1.35959073e-9 * tas * tas * tas * tas * tas * tas
        + -2.25836520e0 * sfcWind
        + 8.80326035e-2 * tas * sfcWind
        + 2.16844454e-3 * tas * tas * sfcWind
        + -1.53347087e-5 * tas * tas * tas * sfcWind
        + -5.72983704e-7 * tas * tas * tas * tas * sfcWind
        + -2.55090145e-9 * tas * tas * tas * tas * tas * sfcWind
        + -7.51269505e-1 * sfcWind * sfcWind
        + -4.08350271e-3 * tas * sfcWind * sfcWind
        + -5.21670675e-5 * tas * tas * sfcWind * sfcWind
        + 1.94544667e-6 * tas * tas * tas * sfcWind * sfcWind
        + 1.14099531e-8 * tas * tas * tas * tas * sfcWind * sfcWind
        + 1.58137256e-1 * sfcWind * sfcWind * sfcWind
        + -6.57263143e-5 * tas * sfcWind * sfcWind * sfcWind
        + 2.22697524e-7 * tas * tas * sfcWind * sfcWind * sfcWind
        + -4.16117031e-8 * tas * tas * tas * sfcWind * sfcWind * sfcWind
        + -1.27762753e-2 * sfcWind * sfcWind * sfcWind * sfcWind
        + 9.66891875e-6 * tas * sfcWind * sfcWind * sfcWind * sfcWind
        + 2.52785852e-9 * tas * tas * sfcWind * sfcWind * sfcWind * sfcWind
        + 4.56306672e-4 * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind
        + -1.74202546e-7 * tas * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind
        + -5.91491269e-6 * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind
        + 3.98374029e-1 * dt
        + 1.83945314e-4 * tas * dt
        + -1.73754510e-4 * tas * tas * dt
        + -7.60781159e-7 * tas * tas * tas * dt
        + 3.77830287e-8 * tas * tas * tas * tas * dt
        + 5.43079673e-10 * tas * tas * tas * tas * tas * dt
        + -2.00518269e-2 * sfcWind * dt
        + 8.92859837e-4 * tas * sfcWind * dt
        + 3.45433048e-6 * tas * tas * sfcWind * dt
        + -3.77925774e-7 * tas * tas * tas * sfcWind * dt
        + -1.69699377e-9 * tas * tas * tas * tas * sfcWind * dt
        + 1.69992415e-4 * sfcWind * sfcWind * dt
        + -4.99204314e-5 * tas * sfcWind * sfcWind * dt
        + 2.47417178e-7 * tas * tas * sfcWind * sfcWind * dt
        + 1.07596466e-8 * tas * tas * tas * sfcWind * sfcWind * dt
        + 8.49242932e-5 * sfcWind * sfcWind * sfcWind * dt
        + 1.35191328e-6 * tas * sfcWind * sfcWind * sfcWind * dt
        + -6.21531254e-9 * tas * tas * sfcWind * sfcWind * sfcWind * dt
        + -4.99410301e-6 * sfcWind * sfcWind * sfcWind * sfcWind * dt
        + -1.89489258e-8 * tas * sfcWind * sfcWind * sfcWind * sfcWind * dt
        + 8.15300114e-8 * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind * dt
        + 7.55043090e-4 * dt * dt
        + -5.65095215e-5 * tas * dt * dt
        + -4.52166564e-7 * tas * tas * dt * dt
        + 2.46688878e-8 * tas * tas * tas * dt * dt
        + 2.42674348e-10 * tas * tas * tas * tas * dt * dt
        + 1.54547250e-4 * sfcWind * dt * dt
        + 5.24110970e-6 * tas * sfcWind * dt * dt
        + -8.75874982e-8 * tas * tas * sfcWind * dt * dt
        + -1.50743064e-9 * tas * tas * tas * sfcWind * dt * dt
        + -1.56236307e-5 * sfcWind * sfcWind * dt * dt
        + -1.33895614e-7 * tas * sfcWind * sfcWind * dt * dt
        + 2.49709824e-9 * tas * tas * sfcWind * sfcWind * dt * dt
        + 6.51711721e-7 * sfcWind * sfcWind * sfcWind * dt * dt
        + 1.94960053e-9 * tas * sfcWind * sfcWind * sfcWind * dt * dt
        + -1.00361113e-8 * sfcWind * sfcWind * sfcWind * sfcWind * dt * dt
        + -1.21206673e-5 * dt * dt * dt
        + -2.18203660e-7 * tas * dt * dt * dt
        + 7.51269482e-9 * tas * tas * dt * dt * dt
        + 9.79063848e-11 * tas * tas * tas * dt * dt * dt
        + 1.25006734e-6 * sfcWind * dt * dt * dt
        + -1.81584736e-9 * tas * sfcWind * dt * dt * dt
        + -3.52197671e-10 * tas * tas * sfcWind * dt * dt * dt
        + -3.36514630e-8 * sfcWind * sfcWind * dt * dt * dt
        + 1.35908359e-10 * tas * sfcWind * sfcWind * dt * dt * dt
        + 4.17032620e-10 * sfcWind * sfcWind * sfcWind * dt * dt * dt
        + -1.30369025e-9 * dt * dt * dt * dt
        + 4.13908461e-10 * tas * dt * dt * dt * dt
        + 9.22652254e-12 * tas * tas * dt * dt * dt * dt
        + -5.08220384e-9 * sfcWind * dt * dt * dt * dt
        + -2.24730961e-11 * tas * sfcWind * dt * dt * dt * dt
        + 1.17139133e-10 * sfcWind * sfcWind * dt * dt * dt * dt
        + 6.62154879e-10 * dt * dt * dt * dt * dt
        + 4.03863260e-13 * tas * dt * dt * dt * dt * dt
        + 1.95087203e-12 * sfcWind * dt * dt * dt * dt * dt
        + -4.73602469e-12 * dt * dt * dt * dt * dt * dt
        + 5.12733497e0 * wvp
        + -3.12788561e-1 * tas * wvp
        + -1.96701861e-2 * tas * tas * wvp
        + 9.99690870e-4 * tas * tas * tas * wvp
        + 9.51738512e-6 * tas * tas * tas * tas * wvp
        + -4.66426341e-7 * tas * tas * tas * tas * tas * wvp
        + 5.48050612e-1 * sfcWind * wvp
        + -3.30552823e-3 * tas * sfcWind * wvp
        + -1.64119440e-3 * tas * tas * sfcWind * wvp
        + -5.16670694e-6 * tas * tas * tas * sfcWind * wvp
        + 9.52692432e-7 * tas * tas * tas * tas * sfcWind * wvp
        + -4.29223622e-2 * sfcWind * sfcWind * wvp
        + 5.00845667e-3 * tas * sfcWind * sfcWind * wvp
        + 1.00601257e-6 * tas * tas * sfcWind * sfcWind * wvp
        + -1.81748644e-6 * tas * tas * tas * sfcWind * sfcWind * wvp
        + -1.25813502e-3 * sfcWind * sfcWind * sfcWind * wvp
        + -1.79330391e-4 * tas * sfcWind * sfcWind * sfcWind * wvp
        + 2.34994441e-6 * tas * tas * sfcWind * sfcWind * sfcWind * wvp
        + 1.29735808e-4 * sfcWind * sfcWind * sfcWind * sfcWind * wvp
        + 1.29064870e-6 * tas * sfcWind * sfcWind * sfcWind * sfcWind * wvp
        + -2.28558686e-6 * sfcWind * sfcWind * sfcWind * sfcWind * sfcWind * wvp
        + -3.69476348e-2 * dt * wvp
        + 1.62325322e-3 * tas * dt * wvp
        + -3.14279680e-5 * tas * tas * dt * wvp
        + 2.59835559e-6 * tas * tas * tas * dt * wvp
        + -4.77136523e-8 * tas * tas * tas * tas * dt * wvp
        + 8.64203390e-3 * sfcWind * dt * wvp
        + -6.87405181e-4 * tas * sfcWind * dt * wvp
        + -9.13863872e-6 * tas * tas * sfcWind * dt * wvp
        + 5.15916806e-7 * tas * tas * tas * sfcWind * dt * wvp
        + -3.59217476e-5 * sfcWind * sfcWind * dt * wvp
        + 3.28696511e-5 * tas * sfcWind * sfcWind * dt * wvp
        + -7.10542454e-7 * tas * tas * sfcWind * sfcWind * dt * wvp
        + -1.24382300e-5 * sfcWind * sfcWind * sfcWind * dt * wvp
        + -7.38584400e-9 * tas * sfcWind * sfcWind * sfcWind * dt * wvp
        + 2.20609296e-7 * sfcWind * sfcWind * sfcWind * sfcWind * dt * wvp
        + -7.32469180e-4 * dt * dt * wvp
        + -1.87381964e-5 * tas * dt * dt * wvp
        + 4.80925239e-6 * tas * tas * dt * dt * wvp
        + -8.75492040e-8 * tas * tas * tas * dt * dt * wvp
        + 2.77862930e-5 * sfcWind * dt * dt * wvp
        + -5.06004592e-6 * tas * sfcWind * dt * dt * wvp
        + 1.14325367e-7 * tas * tas * sfcWind * dt * dt * wvp
        + 2.53016723e-6 * sfcWind * sfcWind * dt * dt * wvp
        + -1.72857035e-8 * tas * sfcWind * sfcWind * dt * dt * wvp
        + -3.95079398e-8 * sfcWind * sfcWind * sfcWind * dt * dt * wvp
        + -3.59413173e-7 * dt * dt * dt * wvp
        + 7.04388046e-7 * tas * dt * dt * dt * wvp
        + -1.89309167e-8 * tas * tas * dt * dt * dt * wvp
        + -4.79768731e-7 * sfcWind * dt * dt * dt * wvp
        + 7.96079978e-9 * tas * sfcWind * dt * dt * dt * wvp
        + 1.62897058e-9 * sfcWind * sfcWind * dt * dt * dt * wvp
        + 3.94367674e-8 * dt * dt * dt * dt * wvp
        + -1.18566247e-9 * tas * dt * dt * dt * dt * wvp
        + 3.34678041e-10 * sfcWind * dt * dt * dt * dt * wvp
        + -1.15606447e-10 * dt * dt * dt * dt * dt * wvp
        + -2.80626406e0 * wvp * wvp
        + 5.48712484e-1 * tas * wvp * wvp
        + -3.99428410e-3 * tas * tas * wvp * wvp
        + -9.54009191e-4 * tas * tas * tas * wvp * wvp
        + 1.93090978e-5 * tas * tas * tas * tas * wvp * wvp
        + -3.08806365e-1 * sfcWind * wvp * wvp
        + 1.16952364e-2 * tas * sfcWind * wvp * wvp
        + 4.95271903e-4 * tas * tas * sfcWind * wvp * wvp
        + -1.90710882e-5 * tas * tas * tas * sfcWind * wvp * wvp
        + 2.10787756e-3 * sfcWind * sfcWind * wvp * wvp
        + -6.98445738e-4 * tas * sfcWind * sfcWind * wvp * wvp
        + 2.30109073e-5 * tas * tas * sfcWind * sfcWind * wvp * wvp
        + 4.17856590e-4 * sfcWind * sfcWind * sfcWind * wvp * wvp
        + -1.27043871e-5 * tas * sfcWind * sfcWind * sfcWind * wvp * wvp
        + -3.04620472e-6 * sfcWind * sfcWind * sfcWind * sfcWind * wvp * wvp
        + 5.14507424e-2 * dt * wvp * wvp
        + -4.32510997e-3 * tas * dt * wvp * wvp
        + 8.99281156e-5 * tas * tas * dt * wvp * wvp
        + -7.14663943e-7 * tas * tas * tas * dt * wvp * wvp
        + -2.66016305e-4 * sfcWind * dt * wvp * wvp
        + 2.63789586e-4 * tas * sfcWind * dt * wvp * wvp
        + -7.01199003e-6 * tas * tas * sfcWind * dt * wvp * wvp
        + -1.06823306e-4 * sfcWind * sfcWind * dt * wvp * wvp
        + 3.61341136e-6 * tas * sfcWind * sfcWind * dt * wvp * wvp
        + 2.29748967e-7 * sfcWind * sfcWind * sfcWind * dt * wvp * wvp
        + 3.04788893e-4 * dt * dt * wvp * wvp
        + -6.42070836e-5 * tas * dt * dt * wvp * wvp
        + 1.16257971e-6 * tas * tas * dt * dt * wvp * wvp
        + 7.68023384e-6 * sfcWind * dt * dt * wvp * wvp
        + -5.47446896e-7 * tas * sfcWind * dt * dt * wvp * wvp
        + -3.59937910e-8 * sfcWind * sfcWind * dt * dt * wvp * wvp
        + -4.36497725e-6 * dt * dt * dt * wvp * wvp
        + 1.68737969e-7 * tas * dt * dt * dt * wvp * wvp
        + 2.67489271e-8 * sfcWind * dt * dt * dt * wvp * wvp
        + 3.23926897e-9 * dt * dt * dt * dt * wvp * wvp
        + -3.53874123e-2 * wvp * wvp * wvp
        + -2.21201190e-1 * tas * wvp * wvp * wvp
        + 1.55126038e-2 * tas * tas * wvp * wvp * wvp
        + -2.63917279e-4 * tas * tas * tas * wvp * wvp * wvp
        + 4.53433455e-2 * sfcWind * wvp * wvp * wvp
        + -4.32943862e-3 * tas * sfcWind * wvp * wvp * wvp
        + 1.45389826e-4 * tas * tas * sfcWind * wvp * wvp * wvp
        + 2.17508610e-4 * sfcWind * sfcWind * wvp * wvp * wvp
        + -6.66724702e-5 * tas * sfcWind * sfcWind * wvp * wvp * wvp
        + 3.33217140e-5 * sfcWind * sfcWind * sfcWind * wvp * wvp * wvp
        + -2.26921615e-3 * dt * wvp * wvp * wvp
        + 3.80261982e-4 * tas * dt * wvp * wvp * wvp
        + -5.45314314e-9 * tas * tas * dt * wvp * wvp * wvp
        + -7.96355448e-4 * sfcWind * dt * wvp * wvp * wvp
        + 2.53458034e-5 * tas * sfcWind * dt * wvp * wvp * wvp
        + -6.31223658e-6 * sfcWind * sfcWind * dt * wvp * wvp * wvp
        + 3.02122035e-4 * dt * dt * wvp * wvp * wvp
        + -4.77403547e-6 * tas * dt * dt * wvp * wvp * wvp
        + 1.73825715e-6 * sfcWind * dt * dt * wvp * wvp * wvp
        + -4.09087898e-7 * dt * dt * dt * wvp * wvp * wvp
        + 6.14155345e-1 * wvp * wvp * wvp * wvp
        + -6.16755931e-2 * tas * wvp * wvp * wvp * wvp
        + 1.33374846e-3 * tas * tas * wvp * wvp * wvp * wvp
        + 3.55375387e-3 * sfcWind * wvp * wvp * wvp * wvp
        + -5.13027851e-4 * tas * sfcWind * wvp * wvp * wvp * wvp
        + 1.02449757e-4 * sfcWind * sfcWind * wvp * wvp * wvp * wvp
        + -1.48526421e-3 * dt * wvp * wvp * wvp * wvp
        + -4.11469183e-5 * tas * dt * wvp * wvp * wvp * wvp
        + -6.80434415e-6 * sfcWind * dt * wvp * wvp * wvp * wvp
        + -9.77675906e-6 * dt * dt * wvp * wvp * wvp * wvp
        + 8.82773108e-2 * wvp * wvp * wvp * wvp * wvp
        + -3.01859306e-3 * tas * wvp * wvp * wvp * wvp * wvp
        + 1.04452989e-3 * sfcWind * wvp * wvp * wvp * wvp * wvp
        + 2.47090539e-4 * dt * wvp * wvp * wvp * wvp * wvp
        + 1.48348065e-3 * wvp * wvp * wvp * wvp * wvp * wvp
    )


@declare_units(
    tas="[temperature]",
    hurs="[]",
    sfcWind="[speed]",
    mrt="[temperature]",
    rsds="[radiation]",
    rsus="[radiation]",
    rlds="[radiation]",
    rlus="[radiation]",
)
def universal_thermal_climate_index(
    tas: xr.DataArray,
    hurs: xr.DataArray,
    sfcWind: xr.DataArray,
    mrt: xr.DataArray | None = None,
    rsds: xr.DataArray | None = None,
    rsus: xr.DataArray | None = None,
    rlds: xr.DataArray | None = None,
    rlus: xr.DataArray | None = None,
    stat: str = "sunlit",
    mask_invalid: bool = True,
    wind_cap_min: bool = False,
) -> xr.DataArray:
    r"""
    Universal thermal climate index (UTCI).

    The UTCI is the equivalent temperature for the environment derived from a
    reference environment and is used to evaluate heat stress in outdoor spaces.

    Parameters
    ----------
    tas : xarray.DataArray
        Mean Temperature.
    hurs : xarray.DataArray
        Relative Humidity.
    sfcWind : xarray.DataArray
        Wind Velocity.
    mrt : xarray.DataArray, optional
        Mean Radiant Temperature.
    rsds : xr.DataArray, optional
        Surface Downwelling Shortwave Radiation.
        This is necessary if `mrt` is not `None`.
    rsus : xr.DataArray, optional
        Surface Upwelling Shortwave Radiation.
        This is necessary if `mrt` is not `None`.
    rlds : xr.DataArray, optional
        Surface Downwelling Longwave Radiation.
        This is necessary if `mrt` is not `None`.
    rlus : xr.DataArray, optional
        Surface Upwelling Longwave Radiation.
        This is necessary if `mrt` is not `None`.
    stat : {'instant', 'sunlit'}
        Which statistic to apply.
        If "instant", the instantaneous cosine of the solar zenith angle is calculated.
        If "sunlit", the cosine of the solar zenith angle is calculated during the sunlit period of each interval.
        This is necessary if `mrt` is not `None`.
    mask_invalid : bool
        If True (default), UTCI values are NaN where any of the inputs are outside their validity ranges:
        - -50°C < tas < 50°C.
        - -30°C < tas - mrt < 30°C.
        - 0.5 m/s < sfcWind < 17.0 m/s.
    wind_cap_min : bool
        If True, wind velocities are capped to a minimum of 0.5 m/s following :cite:t:`brode_utci_2012`
        usage guidelines. This ensures UTCI calculation for low winds. Default value False.

    Returns
    -------
    xarray.DataArray
        Universal Thermal Climate Index.

    Notes
    -----
    The calculation uses water vapour partial pressure, which is derived from relative
    humidity and saturation vapour pressure computed according to the ITS-90 equation.

    This code was inspired by the `pythermalcomfort` and `thermofeel` packages.

    For more information: https://www.utci.org/

    References
    ----------
    :cite:cts:`brode_utci_2009,brode_utci_2012,blazejczyk_introduction_2013`
    """
    e_sat = saturation_vapor_pressure(tas=tas, method="its90")
    tas = convert_units_to(tas, "degC")
    sfcWind = convert_units_to(sfcWind, "m/s")
    if wind_cap_min:
        sfcWind = sfcWind.clip(0.5, None)
    if mrt is None:
        mrt = mean_radiant_temperature(rsds=rsds, rsus=rsus, rlds=rlds, rlus=rlus, stat=stat)
    mrt = convert_units_to(mrt, "degC")
    delta = mrt - tas
    pa = convert_units_to(e_sat, "kPa") * convert_units_to(hurs, "1")

    utci: xr.DataArray = xr.apply_ufunc(
        _utci,
        tas,
        sfcWind,
        delta,
        pa,
        input_core_dims=[[], [], [], []],
        dask="parallelized",
        output_dtypes=[tas.dtype],
    )

    utci = utci.assign_attrs({"units": "degC"})
    if mask_invalid:
        utci = utci.where(
            (-50.0 < tas) & (tas < 50.0) & (-30 < delta) & (delta < 30) & (0.5 <= sfcWind) & (sfcWind < 17.0)
        )
    return utci


def _fdir_ratio(
    dates: xr.DataArray,
    csza: xr.DataArray,
    rsds: xr.DataArray,
) -> xr.DataArray:
    r"""
    Return ratio of direct solar radiation.

    The ratio of direct solar radiation is the fraction of the total horizontal solar irradiance
    due to the direct beam of the sun.

    Parameters
    ----------
    dates : xr.DataArray
        Series of dates and time of day.
    csza : xr.DataArray
        Cosine of the solar zenith angle during the sunlit period of each interval or at an instant.
    rsds : xr.DataArray
        Surface Downwelling Shortwave Radiation.

    Returns
    -------
    xarray.DataArray, [dimensionless]
        Ratio of direct solar radiation.

    Notes
    -----
    This code was inspired by the `PyWBGT` package.

    References
    ----------
    :cite:cts:`liljegren_modeling_2008,kong_explicit_2022`
    """
    d = distance_from_sun(dates)
    s_star = rsds * ((1367 * csza * (d ** (-2))) ** (-1))
    s_star = xr.where(s_star > 0.85, 0.85, s_star)
    fdir_ratio = np.exp(3 - 1.34 * s_star - 1.65 * (s_star ** (-1)))
    fdir_ratio = xr.where(fdir_ratio > 0.9, 0.9, fdir_ratio)
    return xr.where(
        (fdir_ratio <= 0) | (csza <= np.cos(89.5 / 180 * np.pi)) | (rsds <= 0),
        0,
        fdir_ratio,
    )


@declare_units(rsds="[radiation]", rsus="[radiation]", rlds="[radiation]", rlus="[radiation]")
def mean_radiant_temperature(
    rsds: xr.DataArray,
    rsus: xr.DataArray,
    rlds: xr.DataArray,
    rlus: xr.DataArray,
    stat: str = "sunlit",
) -> xr.DataArray:
    r"""
    Mean radiant temperature.

    The mean radiant temperature is the incidence of radiation on the body from all directions.

    Parameters
    ----------
    rsds : xr.DataArray
       Surface Downwelling Shortwave Radiation.
    rsus : xr.DataArray
        Surface Upwelling Shortwave Radiation.
    rlds : xr.DataArray
        Surface Downwelling Longwave Radiation.
    rlus : xr.DataArray
        Surface Upwelling Longwave Radiation.
    stat : {'instant', 'sunlit'}
        Which statistic to apply. If "instant", the instantaneous cosine of the solar zenith angle is calculated.
        If "sunlit", the cosine of the solar zenith angle is calculated during the sunlit period of each interval.

    Returns
    -------
    xarray.DataArray, [K]
        Mean Radiant Temperature.

    Warnings
    --------
    There are some issues in the calculation of `mrt` in extreme polar regions.

    Notes
    -----
    This code was inspired by the `thermofeel` package :cite:p:`brimicombe_thermofeel_2021`.

    References
    ----------
    :cite:cts:`di_napoli_mean_2020`
    """
    rsds = convert_units_to(rsds, "W m-2")
    rsus = convert_units_to(rsus, "W m-2")
    rlds = convert_units_to(rlds, "W m-2")
    rlus = convert_units_to(rlus, "W m-2")

    dates = rsds.time
    lat = _gather_lat(rsds)
    lon = _gather_lon(rsds)
    dec = solar_declination(dates)

    if stat == "sunlit":
        csza = cosine_of_solar_zenith_angle(
            dates,
            dec,
            lat,
            lon=lon,
            stat="average",
            sunlit=True,
            chunks=rsds.chunksizes,
        )
    elif stat == "instant":
        tc = time_correction_for_solar_angle(dates)
        csza = cosine_of_solar_zenith_angle(
            dates,
            dec,
            lat,
            lon=lon,
            time_correction=tc,
            stat="instant",
            chunks=rsds.chunksizes,
        )
    else:
        raise NotImplementedError("Argument 'stat' must be one of 'instant' or 'sunlit'.")

    fdir_ratio = _fdir_ratio(dates, csza, rsds)

    rsds_direct = fdir_ratio * rsds
    rsds_diffuse = rsds - rsds_direct

    gamma = np.arcsin(csza)
    fp = 0.308 * np.cos(gamma * 0.988 - (gamma**2 / 50000))
    i_star = xr.where(csza > 0.001, rsds_direct / csza, 0)

    mrt = cast(
        xr.DataArray,
        np.power(
            (
                (1 / 5.67e-8)  # Stefan-Boltzmann constant
                * (0.5 * rlds + 0.5 * rlus + (0.7 / 0.97) * (0.5 * rsds_diffuse + 0.5 * rsus + fp * i_star))
            ),
            0.25,
        ),
    )
    mrt = mrt.assign_attrs({"units": "K"})
    return mrt


@declare_units(wind_speed="[speed]", h="[length]", h_r="[length]")
def wind_profile(
    wind_speed: xr.DataArray,
    h: Quantified,
    h_r: Quantified,
    method: str = "power_law",
    **kwds,
) -> xr.DataArray:
    r"""
    Wind speed at a given height estimated from the wind speed at a reference height.

    Estimate the wind speed based on a power law profile relating wind speed to height above the surface.

    Parameters
    ----------
    wind_speed : xarray.DataArray
        Wind Speed at the reference height.
    h : Quantified
        Height at which to compute the Wind Speed.
    h_r : Quantified
        Reference height.
    method : {"power_law"}
        Method to use. Currently only "power_law" is implemented.
    **kwds : dict
        Additional keyword arguments to pass to the method.For power_law, this is alpha, which takes a default value
        of 1/7, but is highly variable based on topography, surface cover and atmospheric stability.

    Returns
    -------
    xarray.DataArray
        Wind Speed at the desired height.

    Notes
    -----
    The power law profile is given by:

    .. math::

       v = v_r \left( \frac{h}{h_r} \right)^{\alpha},

    where :math:`v_r` is the wind speed at the reference height, :math:`h` is the height at which the wind speed is
    desired, and :math:`h_r` is the reference height.
    """
    # Convert units to meters
    h = convert_units_to(h, "m")
    h_r = convert_units_to(h_r, "m")

    if method == "power_law":
        alpha = kwds.pop("alpha", 1 / 7)
        out: xr.DataArray = wind_speed * (h / h_r) ** alpha
        out = out.assign_attrs(units=wind_speed.attrs["units"])
        return out
    raise NotImplementedError(f"Method {method} not implemented.")


@declare_units(
    wind_speed="[speed]",
    air_density="[air_density]",
    cut_in="[speed]",
    rated="[speed]",
    cut_out="[speed]",
)
def wind_power_potential(
    wind_speed: xr.DataArray,
    air_density: xr.DataArray | None = None,
    cut_in: Quantified = "3.5 m/s",
    rated: Quantified = "13 m/s",
    cut_out: Quantified = "25 m/s",
) -> xr.DataArray:
    r"""
    Wind power potential estimated from an idealized wind power production factor.

    The actual power production of a wind farm can be estimated by multiplying its nominal (nameplate) capacity by the
    wind power potential, which depends on wind speed at the hub height, the turbine specifications and air density.

    Parameters
    ----------
    wind_speed : xarray.DataArray
        Wind Speed at the hub height.
        Use the `wind_profile` function to estimate from the surface wind speed.
    air_density : xarray.DataArray
        Air Density at the hub height. Defaults to 1.225 kg/m³.
        This is worth changing if applying in cold or mountainous regions with non-standard air density.
    cut_in : Quantified
        Cut-in wind speed. Default is 3.5 m/s.
    rated : Quantified
        Rated wind speed. Default is 13 m/s.
    cut_out : Quantified
        Cut-out wind speed. Default is 25 m/s.

    Returns
    -------
    xr.DataArray
        The power production factor. Multiply by the nominal capacity to get the actual power production.

    See Also
    --------
    wind_profile : Estimate wind speed at the hub height from the surface wind speed.

    Notes
    -----
    This estimate of wind power production is based on an idealized power curve with four wind regimes specified
    by the cut-in wind speed (:math:`u_i`), the rated speed (:math:`u_r`) and the cut-out speed (:math:`u_o`).
    Power production is zero for wind speeds below the cut-in speed, increases cubically between the cut-in
    and rated speed, is constant between the rated and cut-out speed, and is zero for wind speeds above the cut-out
    speed to avoid damage to the turbine :cite:p:`tobin_2018`:

    .. math::

       \begin{cases}
       0,  &  v < u_i \\
       (v^3 - u_i^3) / (u_r^3 - u_i^3),  & u_i ≤ v < u_r \\
       1, & u_r ≤ v < u_o \\
       0, & v ≥ u_o
       \end{cases}

    For non-standard air density (:math:`\rho`), the wind speed is scaled using
    :math:`v_n = v \left( \frac{\rho}{\rho_0} \right)^{1/3}`.

    The temporal resolution of wind time series has a significant influence on the results: mean daily wind
    speeds yield lower values than hourly wind speeds. Note however that percent changes in the wind power potential
    climate projections are similar across resolutions :cite:p:`chen_2020`.

    To compute the power production, multiply the power production factor by the nominal
    turbine capacity (e.g. 100), set the units attribute (e.g. "MW"), resample and sum with
    `xclim.indices.generic.select_resample_op(power, op="sum", freq="D")`, then convert to
    the desired units (e.g. "MWh") using `xclim.core.units.convert_units_to`.

    References
    ----------
    :cite:cts:`chen_2020,tobin_2018`.
    """
    # Convert units
    cut_in = convert_units_to(cut_in, wind_speed)
    rated = convert_units_to(rated, wind_speed)
    cut_out = convert_units_to(cut_out, wind_speed)

    # Correct wind speed for air density
    if air_density is not None:
        default_air_density = convert_units_to("1.225 kg/m^3", air_density)
        f = (air_density / default_air_density) ** (1 / 3)
    else:
        f = 1

    v = wind_speed * f

    out: xr.DataArray = xr.apply_ufunc(_wind_power_factor, v, cut_in, rated, cut_out)
    out = out.assign_attrs(units="")
    return out


@vectorize
def _wind_power_factor(v, cut_in, rated, cut_out):
    """Wind power factor function"""
    if v < cut_in:
        return 0.0
    if v < rated:
        return (v**3 - cut_in**3) / (rated**3 - cut_in**3)
    if v < cut_out:
        return 1.0
    return 0.0
