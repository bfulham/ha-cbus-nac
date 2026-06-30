from pathlib import Path
import zipfile

from project import parse_project_path


XML = b'''<?xml version="1.0"?>
<Installation><DBVersion>2.3</DBVersion><Project><TagName>TEST</TagName><Address>TEST</Address>
<Network><TagName>Test Network</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber>
<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>10.0.0.2:10002</InterfaceAddress></Interface>
<Application><TagName>Custom Lighting</TagName><Address>61</Address>
<Group><TagName>Lobby Lights</TagName><Address>1</Address></Group>
<Group><TagName>Lobby Motion</TagName><Address>2</Address></Group></Application>
<Unit><TagName>Output</TagName><Address>1</Address><UnitType>RELDN4</UnitType>
<PP Name="Application" Value="0x3d 0xff"/><PP Name="GroupAddress" Value="0x1 0xff"/></Unit>
<Unit><TagName>Lobby Sensor</TagName><Address>20</Address><UnitType>SENPIRIB</UnitType>
<CatalogNumber>5753L</CatalogNumber><FirmwareVersion>2.4.00</FirmwareVersion>
<PP Name="Application" Value="0x3d 0xff"/>
<PP Name="GroupAddress" Value="0x1 0xff 0x2 0xff 0xff 0xff 0xff 0xff"/>
<PP Name="PIRLightMovement" Value="0x5"/><PP Name="PIRDarkMovement" Value="0x4"/>
<PP Name="SecondApplicationBlocks" Value="0x0"/></Unit>
<Unit><TagName>Corridor Sensor</TagName><Address>21</Address><UnitType>SENPIRIB</UnitType>
<CatalogNumber>5753L</CatalogNumber>
<PP Name="Application" Value="0x3d 0xff"/>
<PP Name="GroupAddress" Value="0x1 0xff 0xff 0xff 0xff 0xff 0xff 0xff"/>
<PP Name="PIRLightMovement" Value="0x1"/><PP Name="PIRDarkMovement" Value="0x1"/></Unit>
<Unit><TagName>Unassigned Sensor</TagName><Address>22</Address><UnitType>SENPIRIB</UnitType>
<CatalogNumber>5753L</CatalogNumber>
<PP Name="Application" Value="0x3d 0xff"/>
<PP Name="GroupAddress" Value="0xff 0xff 0xff 0xff 0xff 0xff 0xff 0xff"/>
<PP Name="PIRLightMovement" Value="0x1"/><PP Name="PIRDarkMovement" Value="0x1"/></Unit>
</Network></Project></Installation>'''


def test_parse_cbz(tmp_path: Path):
    cbz = tmp_path / "test.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("TEST.xml", XML)
    project = parse_project_path(cbz)
    network = project["networks"][0]
    assert project["project_name"] == "TEST"
    assert project["schema_version"] == 3
    assert network["interface"]["host"] == "10.0.0.2"
    assert network["interface"]["port"] == 10002
    assert network["active_applications"] == [61]
    groups = network["applications"][0]["groups"]
    assert groups[0]["platform"] == "switch"
    assert groups[1]["platform"] == "binary_sensor"

    units = {unit["address"]: unit for unit in network["units"]}
    lobby = units[20]
    assert lobby["supports_illuminance"] is True
    assert lobby["supports_motion"] is True
    assert lobby["motion_groups"] == [
        {
            "application": 61,
            "group": 2,
            "name": "Lobby Motion",
            "block": 2,
            "dedicated": True,
            "active_in_light": True,
            "active_in_dark": True,
            "active_in_both": True,
        }
    ]

    # A dedicated Motion group is not required. The physical source unit lets
    # the integration derive motion from the sensor's ordinary light output.
    corridor = units[21]
    assert corridor["motion_groups"] == [
        {
            "application": 61,
            "group": 1,
            "name": "Lobby Lights",
            "block": 0,
            "dedicated": False,
            "active_in_light": True,
            "active_in_dark": True,
            "active_in_both": True,
        }
    ]

    # With no programmed output group there is no C-Bus traffic to observe.
    assert units[22]["motion_groups"] == []
