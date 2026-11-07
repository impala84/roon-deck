# Optional touchscreen white balance

A per-device profile at `/etc/pi-home/display-white-balance.json` applies RGB
multipliers to the main GTK application window. The profile is separate from
replaceable releases; application updates and reboot preserve it. Missing,
unreadable, oversized or invalid profiles fall back to the original colours.
Other devices have no correction unless their owner creates a profile.

On the measured official 10-inch Touch Display 2, the active RP1 DSI controller
exposed no gamma LUT or CTM. Therefore this is a GTK rendering adjustment, not a
hardware ICC calibration. The desktop/web browser, first-boot wizard and separate
native popup surfaces are outside the main-window correction. GTK acceleration on
the real Pi still requires acceptance testing; the render check verifies CPU/Cairo
snapshot pixels in CI, not GPU behaviour or performance on the touchscreen.

The owner selected the first measured correction as visually sufficient:

```json
{"rgb_gains": [0.9665, 0.8712, 1.0]}
```

Measured uncorrected white: x=0.319662, y=0.363352. First corrected white patch:
x=0.311595, y=0.325958. D65 reference: x=0.3127, y=0.3290. Full profiling and precise
greyscale correction were deliberately not pursued. Sensor measurements used
Argyll's base non-refresh mode without a panel-specific spectral correction, so
these are practical white-balance readings, not certified colour accuracy.

## Activate after updating the application

Close any temporary measurement window with Ctrl+C in its SSH terminal, then run
these commands one at a time on the Pi:

```sh
printf '%s\n' '{"rgb_gains":[0.9665,0.8712,1.0]}' | sudo tee /etc/pi-home/display-white-balance.json
```

```sh
sudo rc-service pi-home-display restart
```

The profile is read at display startup. Test ordinary white text, grey surfaces,
artwork, scrolling and touch on the real device after activation; no further
instrument readings are required for this owner-selected practical adjustment.
Do not reuse these gains on a different panel without checking its white balance.

## Disable

```sh
sudo mv /etc/pi-home/display-white-balance.json /etc/pi-home/display-white-balance.json.disabled
sudo rc-service pi-home-display restart
```

This restores the
original rendering and retains the profile for later use. Editing the gains never
changes source artwork, backend data, or browser colours. Limits are 0.1–1.0 per
channel; the matrix leaves alpha unchanged and applies no offset to black.
