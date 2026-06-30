# Changelog

## 0.1.6

- Create one Home Assistant device per physical `SENPIRIB`/`5753L` sensor, containing both Motion and Illuminance entities.
- Parse PIR Light Movement, PIR Dark Movement and block/group programming from Toolkit project files.
- Motion no longer requires a separately named Motion group; existing PIR-controlled light groups can be used automatically.
- Match live events by C-Bus source unit so manual light changes are not reported as PIR motion.
- Remove legacy controller-level motion-group entity registry entries.
- Keep a physical PIR entity visible but unavailable, with a clear warning, when the unit has no C-Bus output group capable of reporting motion.
- Mark CNI connection entities as diagnostic.
- Toolkit project data must be re-uploaded after upgrading so existing entries gain PIR block mappings.

## 0.1.5

- Fixed integration setup failing on current Home Assistant releases because `UnitOfIlluminance` was removed; illuminance entities now use the supported `LIGHT_LUX` constant.
- Stop all CNI and illuminance tasks when any platform fails to import or set up.
- Stop and replace a stale runtime before retrying setup, preventing orphaned clients from occupying the NAC single-client CNI ports.

## 0.1.4

- Import illuminance-capable physical units (`SENPIRIB`/`5753L` and `SENLL`/`5031PE`) from Toolkit CBZ/XML files.
- Add native Home Assistant illuminance sensors with lux units and measurement state class.
- Read values through the 5500NAC built-in Unit Parameter application and JSON Remote Services, without a Lighting broadcast group or Lua code.
- Poll the full exported NAC object list once per controller per interval to avoid one HTTP request per sensor.
- Add UI options for Remote Services credentials, HTTP/HTTPS, port, TLS verification and refresh interval.
- Add per-entity diagnostics for missing/non-exported Unit Parameter aliases.
- Toolkit project data must be re-uploaded after upgrading so existing entries gain physical unit records.

## 0.1.3

- Disabled Home Assistant's default per-platform action semaphore for C-Bus lights and switches.
- Multi-entity light/switch actions can now reach the integration concurrently instead of being dispatched one entity at a time.
- The existing per-CNI confirmation tags and 17-command in-flight limit continue to provide protocol-level flow control.

## 0.1.2

- Fixed command acknowledgements being delayed until the next CR-terminated MMI packet.
- Parse the PCI/CNI two-byte confirmation response immediately, as required by the serial-interface protocol.
- Allow multiple C-Bus commands to be in flight using independent confirmation tags instead of waiting for each command before writing the next.
- Apply requested Home Assistant state optimistically while live C-Bus traffic remains the source of truth.


## 0.1.1

- Fixed all TCP CNI connections repeatedly disconnecting when the first received line was stored as a `bytearray`.
- Normalised all bytes-like CNI input before decoding.
- Added regression coverage for `bytearray` input from the receive buffer.

## 0.1.0

- Initial direct TCP CNI implementation.
- Toolkit CBZ/XML upload and secure normalisation.
- Multi-network and custom Lighting Application support.
- Imported lights, switches, motion sensors and connection sensors.
- Updated-project upload through Home Assistant reconfiguration.
- Per-network host, port, enable and MMI application options.
