# ha_setup (retired)

These scripts configured the Home Assistant instance on the old HA OS Pi4. They
created helpers, template sensors, power analytics, the LCARS dashboards, the
Signal K MQTT discovery bridge, and the location/underway automations.

**Home Assistant was retired on 2026-10-14**, after its Pi died. It is not
coming back. Boat data now lives in Signal K on OpenPlotter (`openplotter.local`),
and the warm standby is an OpenPlotter replica. Nothing here is run any more.
The files are kept only as a reference for what HA used to do.

What replaced what:

- **Battery, solar and fuel data**: the ESP32 nodes and the Pi5 Venus now feed
  Signal K directly. See `defiant-analogs/README.md`.
- **Power dashboards**: the AvNav "Power" page (layout `user.defiant`, dashboard
  page 4).
- **Location and underway automations**: not yet replaced. `defiant state`
  still points at HA, so it only uses the local cache until it's re-pointed at
  Signal K.
