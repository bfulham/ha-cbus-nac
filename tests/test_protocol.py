import asyncio

from protocol import (
    CbusCniConnection,
    checksum,
    encode_lighting_command,
    parse_cni_line,
)


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



def test_confirmation_consumed_without_carriage_return():
    """PCI/CNI confirmations are two bytes and have no CR/LF terminator."""

    async def run_test():
        connection = CbusCniConnection(
            "127.0.0.1", 10001, 56, lambda event: None, lambda state: None
        )
        future = asyncio.get_running_loop().create_future()
        connection._confirmations["j"] = future
        buffer = bytearray(b"j.")

        connection._consume_receive_buffer(buffer)

        assert not buffer
        assert future.done()
        assert future.result() is True

    asyncio.run(run_test())


def test_confirmation_and_packet_in_same_tcp_buffer():
    """A confirmation immediately followed by a normal packet must parse both."""

    async def run_test():
        events = []
        connection = CbusCniConnection(
            "127.0.0.1", 10001, 56, events.append, lambda state: None
        )
        future = asyncio.get_running_loop().create_future()
        connection._confirmations["j"] = future

        payload = bytes.fromhex("050138007921")
        packet = payload + bytes([checksum(payload)])
        buffer = bytearray(b"j." + packet.hex().upper().encode("ascii") + b"\r\n")

        connection._consume_receive_buffer(buffer)

        assert not buffer
        assert future.result() is True
        assert len(events) == 1
        assert events[0].group == 0x21
        assert events[0].level == 255

    asyncio.run(run_test())


def test_commands_are_written_before_prior_confirmations_arrive():
    """Concurrent HA service calls must not be serialised by acknowledgement wait."""

    class FakeWriter:
        def __init__(self):
            self.writes = []

        def write(self, data):
            self.writes.append(data)

        async def drain(self):
            await asyncio.sleep(0)

    async def run_test():
        connection = CbusCniConnection(
            "127.0.0.1", 10001, 56, lambda event: None, lambda state: None
        )
        writer = FakeWriter()
        connection._writer = writer
        connection._connected = True

        first = asyncio.create_task(connection.send_level(56, 1, 255))
        second = asyncio.create_task(connection.send_level(56, 2, 255))

        for _ in range(20):
            if len(writer.writes) == 2:
                break
            await asyncio.sleep(0)

        assert len(writer.writes) == 2
        tags = [write[-2:-1].decode("ascii") for write in writer.writes]
        assert tags[0] != tags[1]

        for tag in tags:
            connection._handle_line(f"{tag}.".encode("ascii"))
        await asyncio.gather(first, second)

    asyncio.run(run_test())
