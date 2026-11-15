# NEA rain arrival for Home Assistant

Copy `custom_components/nea_rain` into Home Assistant's `custom_components` directory. Add this item to the existing `sensor:` list in `configuration.yaml`, or create that list if needed.

```yaml
sensor:
  - platform: nea_rain
```

The sensor uses the Home Assistant home coordinates by default. Add both `latitude` and `longitude` under the platform entry to override them. Check the configuration and restart Home Assistant to load the integration.

In **Developer tools → States**, verify that `sensor.home_rain_nowcast` is present. If there is an entity ID conflict, assign that ID to the radar sensor. In the Roon Deck Home layout, open **Add tiles → Home Assistant**, add **Home Rain Nowcast**, and save.

The sensor updates once a minute and reports the radar status, observation timestamp (`radar_at`), and estimated arrival timestamp (`arrival_at`) when available. Frames older than ten minutes make the sensor unavailable. A clear result means the projection shows no tracked rain reaching home in the next 30 minutes. Showers that form locally can give little warning.

## Historical replay

Install the dependencies listed in the integration manifest in a virtual environment. Run `python custom_components/nea_rain/nowcast.py --latitude LAT --longitude LON archive DIRECTORY YYYY-MM-DD [...]` to cache NEA frames. Replace `archive DIRECTORY YYYY-MM-DD [...]` with `replay DIRECTORY` to score 30-minute predictions at consecutive dry scans. The first subsequent wet scan in the target area is the observed onset. Consecutive prediction windows can refer to the same rain event.

Radar imagery supplied by Singapore's National Environment Agency under the Open Data Licence. [Weather Radar Images](https://data.gov.sg/datasets/d_418e9ac3414fd927b7405631e0a7bc82/view)
