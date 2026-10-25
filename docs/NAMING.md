# RoonDeck naming and compatibility

`RoonDeck` is the product name. `roon-deck` is the canonical repository,
package, command, image and newly created filesystem identifier.

## Canonical names

- GitHub: `impala84/roon-deck`
- checkout: `roon-deck`
- Python distribution and primary command: `roon-deck`
- future appliance images and build artifacts: `roon-deck-*`

## Compatibility identifiers

Existing appliances use `/opt/pi-home`, `/etc/pi-home`, `/var/lib/pi-home`,
`PI_HOME_*`, and `pi-home-*` OpenRC services. They contain configuration,
credentials, Roon pairing state and updater state, so they must not be renamed
in place without a transactional migration and rollback path.

The `pi-home` and `pi-bus-time-display` commands and the Python import package
`pi_bus_time_display` remain aliases during this migration. They are not
user-facing branding.

## Migration rule

New code must not introduce another `pi-home` identifier. A later appliance
release may make `/opt/roon-deck`, `/etc/roon-deck`, `/var/lib/roon-deck` and
`roon-deck-*` services canonical only after it:

1. preserves or links every existing configuration and state path;
2. updates service dependencies atomically;
3. proves rollback to the previous application release;
4. verifies in-place updates and fresh images on both release channels; and
5. retains compatibility aliases for at least one stable release.
