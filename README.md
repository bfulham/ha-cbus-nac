# C-Bus NAC for Home Assistant

Direct, local Home Assistant integration for Clipsal/Schneider C-Bus through the built-in CNI service of a 5500NAC/5500SHAC or compatible Ethernet CNI. No C-Gate, MQTT bridge, add-on, or Lua code on the NAC is required.

> **v0.1.6 is an early hardware-test release.** The Toolkit importer and protocol framing are covered by local tests, but this package could not be exercised against the private CNI addresses in the supplied project. Start with a small number of non-critical groups and keep Toolkit available for recovery.

> **v0.1.6 sensor-device update:** motion and illuminance now belong to the same physical C-Bus sensor device. Re-upload the Toolkit project through **Reconfigure** after upgrading so PIR block programming is added to the stored project model.

## What v0.1.6 does

- Processes non-terminated PCI/CNI command confirmations immediately, avoiding the previous wait for the next MMI report.
- Pipelines simultaneous Home Assistant commands using independent CNI confirmation tags.

- Uploads a Toolkit `.cbz` backup or legacy XML during UI setup.
- Imports project names, network names, CNI IP addresses and ports.
- Supports multiple independent CNI connections in one project.
- Detects non-standard Lighting Application addresses from unit programming rather than assuming Application 56.
- Talks directly to each CNI using the public C-Bus PCI/CNI serial protocol over TCP.
- Receives physical ON, OFF and RAMP TO LEVEL commands as push updates.
- Uses standard MMI reports for cold-start on/off state.
- Creates lights and relay/control switches under each C-Bus network/controller device.
- Creates one physical device for each imported PIR/multisensor, containing its Motion and optional Illuminance entities.
- Detects PIR output blocks directly from Toolkit programming, so a separately named `Motion` group is not required.
- Uses the live C-Bus source unit address to avoid treating manual changes to a shared light group as motion.
- Imports 5753L/SENPIRIB and 5031PE/SENLL physical units as optional illuminance sensors.
- Reads lux values from each NAC's built-in Unit Parameter application over its JSON remote service, without requiring a Lighting broadcast group.
- Lets an updated Toolkit file be uploaded later using **Reconfigure** without changing address-based entity unique IDs.
- Allows per-network host/port overrides, including converting a project saved with a Serial interface to a TCP CNI connection.

## Supplied project findings

The supplied Toolkit 1.15.7 project is deliberately handled as a multi-CNI project:

| Toolkit network | Name | Saved connection | Referenced lighting applications |
|---:|---|---|---|
| 254 | ESS2 Race Control | `172.16.29.154:10001` | 61 |
| 253 | DB-L1-1 Function Rooms | `172.16.29.233:10001` | 62 |
| 252 | GF1 - Lobby | Serial `COM4` | 63 and 56 |
| 251 | Kitchen DB | `172.16.29.236:10002` | 64, 65 and 56 |
| 250 | DB-L2 Function | `172.16.29.234:10001` | 66 |
| 249 | Pits | `172.16.29.232:10001` | 67 |
| 248 | DB-L3 Function | `172.16.29.235:10001` | 68 |

Network 252 is imported but is not connected automatically because its project interface is `COM4`. Open **Configure → Network connections**, select network 252, enable it and enter the relevant NAC/CNI host and port.

## Installation

### HACS custom repository

1. Put this repository on GitHub.
2. In HACS, open **Integrations → ⋮ → Custom repositories**.
3. Add the repository URL as category **Integration**.
4. Install **C-Bus NAC** and restart Home Assistant.

### Manual

Copy `custom_components/cbus_nac` to `/config/custom_components/cbus_nac` and restart Home Assistant.

## Setup

1. Open **Settings → Devices & services → Add integration**.
2. Search for **C-Bus NAC**.
3. Upload the Toolkit `.cbz` project.
4. Review the detected project and CNI connections.
5. Confirm setup.

All saved TCP CNI interfaces are enabled by default. The integration creates a connectivity binary sensor for each configured TCP network.

## Direct illuminance sensors (no broadcast group)

v0.1.6 imports the physical unit address and name for supported light-level sensors from the Toolkit project. For the supplied THEBEND project it detects 87 illuminance-capable units: 86 `5753L` multisensors and one `5031PE` light-level sensor.

This feature does **not** use a C-Bus Lighting group or light-level broadcast address. It uses the 5500NAC built-in **255 — Unit Parameter** application. The NAC polls the physical unit, and Home Assistant reads the resulting exported object through `/scada-remote/`. No Lua or other custom code is installed on the NAC.

### NAC preparation

On each NAC, create an object for every local sensor that should be exposed:

1. Open **Configurator → Objects → Add new object**.
2. Select **255 — Unit Parameter**.
3. Select the sensor's local C-Bus unit address.
4. Select **Light level**.
5. Enable **Export** for the object.
6. Enable **Remote services** under **Utilities → System → Services** and set its credentials.

The composed address used by Home Assistant is:

```text
0/255/<unit-address>/2
```

For example, Toolkit network 253 unit 21 is read from `0/255/21/2` on the NAC attached to network 253. The `0` is intentional: each NAC addresses its own local C-Bus network as network 0.

### Home Assistant configuration

1. After updating to v0.1.6, use **Reconfigure** and upload the Toolkit `.cbz` again. This updates the stored project model with physical unit records.
2. Open **Configure → Illuminance sensors**.
3. Enable physical illuminance sensors.
4. Enter the NAC Remote Services protocol, port, username and password. The same credentials are used for all imported NAC hosts.
5. Set a refresh interval; 60 seconds is the default.

One `/scada-remote/?m=json&r=objects` request is made per NAC per interval, rather than one request per sensor. A missing or non-exported Unit Parameter object only makes that individual illuminance entity unavailable; its `last_error` attribute explains which alias is missing.

This implementation deliberately does not attempt undocumented raw CAL/unit-commissioning commands through the CNI.

## Updating the project

Use the integration's three-dot menu and choose **Reconfigure**. Upload the newer `.cbz` file and review the change summary.

Unique IDs use:

```text
project-id : toolkit-network : application : group
```

Renaming a group therefore does not replace the entity or break automations. Home Assistant also does not overwrite a user-customised entity name.

## Connection overrides

Open **Configure → Network connections**, select a network, then optionally set:

- Enabled/disabled state.
- Host override.
- Port override.
- Application used for standard MMI monitoring.

Blank overrides follow the latest values imported from Toolkit, so changing an IP/port in a newly uploaded project takes effect automatically.

## Entity import rules in v0.1.6

Toolkit groups in applications referenced by programmed units are imported. By default, generated/internal names are skipped, including:

- Names beginning with `z`.
- Plain `Group 123` tags.
- Generated `D1A Fitting01` / `D2B Group04` style tags.
- `<Unused>` and obvious `DONT USE` groups.

Classification is conservative:

- Relay groups found in relay output programming, plus names such as `Relay`, `PIR Enable` and `DLT Trigger`, become switches.
- Other controllable groups become brightness-capable lights.
- Groups explicitly named `Motion`, `PIR` or `Occupancy` are no longer created as separate controller-level entities.
- Physical `SENPIRIB`/`5753L` units become their own devices. Their PIR Light Movement and PIR Dark Movement blocks are imported automatically and used to create one unit-backed Motion entity.

A dedicated Motion group is not required. If a PIR already controls an ordinary light group, the integration can derive motion from commands whose C-Bus source unit matches that PIR. Manual commands from switches or Home Assistant do not set the PIR entity. However, a PIR with **no programmed C-Bus output group at all** cannot report motion through the standard CNI stream, so its entity is created but remains unavailable with a configuration warning.

This is only an import heuristic. Home Assistant entity enable/disable and naming can be adjusted after setup. More complete output-channel capability parsing is planned for a later release.

## Important limitations

### CNI single-client behaviour

A CNI accepts one client. Toolkit cannot normally use the same NAC/CNI while Home Assistant is connected. Disable the relevant network under integration options before commissioning, then enable it again afterward.

### Cold-start brightness

Standard C-Bus MMI gives group existence and binary on/off/error state, not exact dimming level. Exact brightness becomes known after Home Assistant observes or sends a RAMP/level command. The integration does not invent a brightness value for an already-on group.

### Multiple applications on one CNI

Live SAL messages are decoded using the application address in each received packet, so applications 64 and 65 can coexist on network 251. Standard MMI monitoring is configured for one application per CNI; select the desired application in connection options. Other applications still receive live command updates but may have unknown state until activity occurs.

### Protocol scope

v0.1.6 supports the public Lighting Application command subset: ON, OFF, RAMP TO LEVEL and standard MMI. Trigger Control, Enable Control, Measurement, HVAC, scenes and routed bridge control are not yet implemented as native platforms.

## Debug logging

```yaml
logger:
  logs:
    custom_components.cbus_nac: debug
```

The integration also fires `cbus_nac_event` for every decoded group update with network, application, group, level, source unit and MMI information.

## Safety

Do not use this integration as the primary mechanism for emergency, fire, life-safety or other safety-critical functions. Keep TCP CNI ports on a trusted local VLAN and do not expose them to the internet.
