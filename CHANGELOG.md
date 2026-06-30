# Changelog

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
