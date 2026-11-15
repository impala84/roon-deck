"""Expose the local NEA rain prediction as a polling sensor."""
from datetime import datetime, timedelta
import logging

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.helpers import config_validation as cv

from .nowcast import SGT, estimate, update_frames

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional("latitude"): cv.latitude,
    vol.Optional("longitude"): cv.longitude,
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if ("latitude" in config) != ("longitude" in config):
        _LOGGER.error("Set both latitude and longitude, or use the Home Assistant home location")
        return
    coordinates = (
        config.get("latitude", hass.config.latitude),
        config.get("longitude", hass.config.longitude),
    )
    async_add_entities([RainNowcast(coordinates)])


class RainNowcast(SensorEntity):
    _attr_name = "Home Rain Nowcast"
    _attr_unique_id = "nea_home_rain_nowcast"
    _attr_icon = "mdi:weather-pouring"
    _attr_available = False

    def __init__(self, coordinates):
        self._coordinates = coordinates
        self._frames = []
        self._last_error = None

    def _update_radar(self):
        try:
            update_frames(self._frames, self._coordinates)
        except (OSError, ValueError, KeyError, IndexError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            if message != self._last_error:
                _LOGGER.warning("NEA radar update failed: %s", message)
            self._last_error = message
        else:
            self._last_error = None
        return estimate(self._frames, datetime.now(SGT))

    async def async_update(self):
        result = await self.hass.async_add_executor_job(self._update_radar)
        self._attr_native_value = result["status"]
        self._attr_available = result["status"] != "unavailable"
        self._attr_extra_state_attributes = {
            key: result[key] for key in ("radar_at", "arrival_at") if key in result
        }
