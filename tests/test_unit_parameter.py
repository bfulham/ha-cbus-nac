import pytest

from unit_parameter import UnitParameterError, light_level_alias, parse_remote_objects


def test_light_level_alias():
    assert light_level_alias(21) == "0/255/21/2"


def test_parse_remote_objects_list():
    payload = '''[
      {"address":"0/255/21/2","data":123.5,"datatype":"lux"},
      {"address":"0/56/1","data":255}
    ]'''
    assert parse_remote_objects(payload) == {
        "0/255/21/2": 123.5,
        "0/56/1": 255.0,
    }


def test_parse_wrapped_remote_objects_and_text_value():
    payload = '{"objects":[{"address":"0/255/7/2","data":"84 lux"}]}'
    assert parse_remote_objects(payload) == {"0/255/7/2": 84.0}


def test_parse_address_mapping():
    payload = '{"0/255/7/2": 100, "status": "ok"}'
    assert parse_remote_objects(payload) == {"0/255/7/2": 100.0}


def test_parse_invalid_payload():
    with pytest.raises(UnitParameterError):
        parse_remote_objects("not json")
