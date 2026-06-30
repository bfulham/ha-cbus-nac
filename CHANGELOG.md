# Changelog

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
