# coding=utf-8
"""Objects for calculating solar-adjusted MRT from DataCollections."""
from __future__ import division

from ..solarcal import outdoor_sky_heat_exch, indoor_sky_heat_exch, \
    shortwave_from_horiz_solar, sharp_from_solar_and_body_azimuth
from ..parameter.solarcal import SolarCalParameter
from ._base import ComfortDataCollection

from ladybug.location import Location
from ladybug.sunpath import Sunpath
from ladybug.datacollection import HourlyDiscontinuousCollection

from ladybug.datatype.temperature import Temperature, MeanRadiantTemperature
from ladybug.datatype.temperaturedelta import RadiantTemperatureDelta
from ladybug.datatype.energyflux import Irradiance, EffectiveRadiantField, \
    HorizontalInfraredRadiationIntensity
from ladybug.datatype.energyintensity import Radiation
from ladybug.datatype.percentage import Percentage


class _SolarCalBase(ComfortDataCollection):
    """Base class used by all other objects that use SolarCal with DataCollections."""

    @property
    def location(self):
        """Ladybug Location object."""
        return self._location.duplicate()

    @property
    def fraction_body_exposed(self):
        """Data Collection of body fraction exposed to direct sun."""
        return self._fract_exp.duplicate()

    @property
    def floor_reflectance(self):
        """Data Collection of floor reflectance."""
        return self._flr_ref.duplicate()

    @property
    def solarcal_body_parameter(self):
        """SolarCal body parameters that are assigned to this object."""
        return self._body_par.duplicate()

    @property
    def mrt_delta(self):
        """Data Collection of total MRT delta in C."""
        return self._build_coll(self._dmrt, RadiantTemperatureDelta(), 'C')

    @property
    def mean_radiant_temperature(self):
        """Data Collection of total mean radiant temperature in C."""
        return self._build_coll(self._mrt, MeanRadiantTemperature(), 'C')

    def _radiation_check(self, data_coll, name):
        assert isinstance(data_coll, HourlyDiscontinuousCollection), \
            '{} must be an hourly collection. Got {}.'.format(name, type(data_coll))
        if isinstance(data_coll.header.data_type, Radiation):
            self._check_datacoll(data_coll, Radiation, 'Wh/m2', name)
            timestep = data_coll.header.analysis_period.timestep
            assert timestep == 1, '{} timestep must be 1 when using Radiation as the ' \
                'data type. Got timestep of {}'.format(name, timestep)
        else:
            self._check_datacoll(data_coll, Irradiance, 'W/m2', name)
        return data_coll

    def _body_par_check(self, body_par):
        if body_par is None:
            self._body_par = SolarCalParameter(posture='standing')
        else:
            assert isinstance(body_par, SolarCalParameter), \
                'solarcal_body_parameter must be a SolarCalParameter object. Got {}'\
                .format(type(body_par))
            self._body_par = body_par


class OutdoorSolarCal(_SolarCalBase):
    """Outdoor SolarCal DataCollection object.

    Properties:
        location
        direct_normal_solar
        diffuse_horizontal_solar
        horizontal_infrared
        surface_temperatures
        fraction_body_exposed
        sky_exposure
        floor_reflectance
        solarcal_body_parameter
        shortwave_effective_radiant_field
        longwave_effective_radiant_field
        shortwave_mrt_delta
        longwave_mrt_delta
        mrt_delta
        mean_radiant_temperature
    """
    _model = 'Outdoor SolarCal'

    def __init__(self, location, direct_normal_solar, diffuse_horizontal_solar,
                 horizontal_infrared, surface_temperatures,
                 fraction_body_exposed=None, sky_exposure=None,
                 floor_reflectance=None, solarcal_body_parameter=None):
        """Perform a full outdoor sky radiant heat exchange using Data Collections.

        Args:
            location: A Ladybug Location object.
            direct_normal_solar: Hourly Data Collection with the direct normal solar
                irradiance in W/m2.
            diffuse_horizontal_solar: Hourly Data Collection with the diffuse
                horizontal solar irradiance in W/m2.
            surface_temperatures: Hourly Data Collection with the temperature of surfaces
                around the person in degrees Celcius. This includes the ground and
                any other surfaces blocking the view to the sky. Typically, outdoor
                dry bulb temperature is used when such surface temperatures are unknown.
            horizontal_infrared: Hourly Data Collection with the horizontal infrared
                radiation intensity from the sky in W/m2.
            fraction_body_exposed: A Data Collection or number between 0 and 1
                representing the fraction of the body exposed to direct sunlight.
                Note that this does not include the body’s self-shading; only the
                shading from surroundings.
                Default is 1 for a person standing in an open area.
            sky_exposure: A Data Collection or number between 0 and 1 representing the
                fraction of the sky vault in occupant’s view. Default is 1 for a person
                standing in an open area.
            floor_reflectance: A Data Collection or number between 0 and 1 that
                represents the reflectance of the floor. Default is for 0.25 which
                is characteristic of outdoor grass or dry bare soil.
            solarcal_body_parameter: Optional SolarCalParameter object to account for
                properties of the human geometry.
        """
        # check required inputs
        self._input_collections = []
        assert isinstance(location, Location), 'location must be a Ladybug Location' \
            ' object. Got {}.'.format(type(location))
        self._location = location
        self._dir_norm = self._radiation_check(
            diffuse_horizontal_solar, 'diffuse_horizontal_solar')
        self._diff_horiz = self._radiation_check(
            diffuse_horizontal_solar, 'diffuse_horizontal_solar')
        self._calc_length = len(self._dir_norm.values)
        self._base_collection = self._dir_norm
        self._horiz_ir = self._check_input(
            horizontal_infrared, HorizontalInfraredRadiationIntensity, 'W/m2',
            'horizontal_infrared')
        self._srf_temp = self._check_input(
            surface_temperatures, Temperature, 'C', 'surface_temperatures')

        # check optional inputs
        if fraction_body_exposed is not None:
            self._fract_exp = self._check_input(
                fraction_body_exposed, Percentage, 'fraction', 'fraction_body_exposed')
        else:
            self._fract_exp = self._base_collection.get_aligned_collection(
                1, Percentage(), 'fraction')
        if sky_exposure is not None:
            self._sky_exp = self._check_input(
                sky_exposure, Percentage, 'fraction', 'sky_exposure')
        else:
            self._sky_exp = self._base_collection.get_aligned_collection(
                1, Percentage(), 'fraction')
        if floor_reflectance is not None:
            self._flr_ref = self._check_input(
                floor_reflectance, Percentage, 'fraction', 'floor_reflectance')
        else:
            self._flr_ref = self._base_collection.get_aligned_collection(
                0.25, Percentage(), 'fraction')

        # check that all input data collections are aligned.
        HourlyDiscontinuousCollection.are_collections_aligned(self._input_collections)

        # check comfort parameters
        self._body_par_check(solarcal_body_parameter)

        # compute SolarCal
        self._calculate_solarcal()

    def _calculate_solarcal(self):
        """Compute SolarCal for each step of the Data Collection."""
        # empty lists to be filled
        self._s_erf = []
        self._s_dmrt = []
        self._l_erf = []
        self._l_dmrt = []
        self._dmrt = []
        self._mrt = []

        # get altitudes and sharps from solar position
        sp = Sunpath.from_location(self._location)
        _altitudes = []
        if self._body_par.body_azimuth is None:
            _sharps = [self._body_par.sharp] * self._calc_length
            for t_date in self._base_collection.datetimes:
                sun = sp.calculate_sun_from_date_time(t_date)
                _altitudes.append(sun.altitude)
        else:
            _sharps = []
            for t_date in self._base_collection.datetimes:
                sun = sp.calculate_sun_from_date_time(t_date)
                sharp = sharp_from_solar_and_body_azimuth(sun.azimuth,
                                                          self._body_par.body_azimuth)
                _sharps.append(sharp)
                _altitudes.append(sun.altitude)

        # calculate final ers and mrt deltas
        for t_srfs, horiz_ir, diff, dir, alt, sharp, sky_e, fract_e, flr_ref in \
                zip(self._srf_temp, self._horiz_ir, self._diff_horiz, self._dir_norm,
                    _altitudes, _sharps, self._sky_exp, self._fract_exp, self._flr_ref):

            result = outdoor_sky_heat_exch(t_srfs, horiz_ir, diff, dir, alt, sky_e,
                                           fract_e, flr_ref, self._body_par.posture,
                                           sharp, self._body_par.body_absorptivity,
                                           self._body_par.body_emissivity)
            self._s_erf.append(result['s_erf'])
            self._s_dmrt.append(result['s_dmrt'])
            self._l_erf.append(result['l_erf'])
            self._l_dmrt.append(result['l_dmrt'])
            self._dmrt.append(result['s_dmrt'] + result['l_dmrt'])
            self._mrt.append(result['mrt'])

    @property
    def diffuse_horizontal_solar(self):
        """Data Collection of diffuse horizontal irradiance in Wh/m2 or W/m2."""
        return self._diff_horiz.duplicate()

    @property
    def direct_normal_solar(self):
        """Data Collection of direct normal irradiance in Wh/m2 or W/m2."""
        return self._dir_norm.duplicate()

    @property
    def surface_temperatures(self):
        """Data Collection of surface temperature values in degrees C."""
        return self._srf_temp.duplicate()

    @property
    def horizontal_infrared(self):
        """Data Collection of horizontal infrared radiation intensity in W/m2."""
        return self._horiz_ir.duplicate()

    @property
    def sky_exposure(self):
        """Data Collection of sky view."""
        return self._sky_exp.duplicate()

    @property
    def shortwave_effective_radiant_field(self):
        """Data Collection of shortwave effective radiant field in W/m2."""
        return self._build_coll(self._s_erf, EffectiveRadiantField(), 'W/m2')

    @property
    def longwave_effective_radiant_field(self):
        """Data Collection of longwave effective radiant field in W/m2."""
        return self._build_coll(self._l_erf, EffectiveRadiantField(), 'W/m2')

    @property
    def shortwave_mrt_delta(self):
        """Data Collection of shortwave MRT delta in C."""
        return self._build_coll(self._s_dmrt, RadiantTemperatureDelta(), 'C')

    @property
    def longwave_mrt_delta(self):
        """Data Collection of longwave MRT delta in C."""
        return self._build_coll(self._l_dmrt, RadiantTemperatureDelta(), 'C')
