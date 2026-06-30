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
</Network></Project></Installation>'''


def test_parse_cbz(tmp_path: Path):
    cbz = tmp_path / "test.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("TEST.xml", XML)
    project = parse_project_path(cbz)
    network = project["networks"][0]
    assert project["project_name"] == "TEST"
    assert network["interface"]["host"] == "10.0.0.2"
    assert network["interface"]["port"] == 10002
    assert network["active_applications"] == [61]
    groups = network["applications"][0]["groups"]
    assert groups[0]["platform"] == "switch"
    assert groups[1]["platform"] == "binary_sensor"
