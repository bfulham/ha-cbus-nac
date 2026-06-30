from protocol import checksum, encode_lighting_command, parse_cni_line


def test_checksum_official_on_example():
    payload = bytes.fromhex("0538007988")
    assert checksum(payload) == 0xC2
    assert encode_lighting_command(0x38, 0x88, 255) == b"\\0538007988C2"


def test_parse_on():
    payload = bytes.fromhex("050138007921")
    packet = payload + bytes([checksum(payload)])
    events = parse_cni_line(packet.hex())
    assert len(events) == 1
    assert events[0].application == 0x38
    assert events[0].group == 0x21
    assert events[0].level == 255


def test_parse_mmi():
    # 4 following bytes: app, start group, one packed state byte, checksum.
    payload = bytes([0xC4, 0x38, 0x00, 0b10_01_00_01])
    packet = payload + bytes([checksum(payload)])
    events = parse_cni_line(packet.hex())
    assert [(e.group, e.is_on) for e in events] == [(0, True), (2, True), (3, False)]


def test_parse_bytearray_from_receive_buffer():
    """The TCP receive buffer yields bytearray slices, not bytes."""
    payload = bytes.fromhex("050138007921")
    packet = payload + bytes([checksum(payload)])
    line = bytearray(packet.hex().upper().encode("ascii"))
    events = parse_cni_line(line)
    assert len(events) == 1
    assert events[0].application == 0x38
    assert events[0].group == 0x21
    assert events[0].level == 255
