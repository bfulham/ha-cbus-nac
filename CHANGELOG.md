# Changelog

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
