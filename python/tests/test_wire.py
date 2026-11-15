import struct
import unittest
from pathlib import Path

import numpy as np

from magarray.source import read_recording
from magarray.wire import (
    BOARD_SYNC,
    CENTER_SYNC,
    SCAN_TYPE,
    WRAPPED_TYPE,
    FrameParser,
    StreamDecoder,
    decode_scan,
    encode_frame,
)

DATA = Path(__file__).parent / "data"


def scan_payload(ticks: int, n: int = 25, base: int = 1000) -> bytes:
    p = struct.pack("<I", ticks)
    for s in range(n):
        p += bytes([s]) + struct.pack("<hhhh", base + s, -2 * base, 3 * base, -(base + s) // 9)
    return p


def board_frame(ticks: int, board_id: int = 1, **kw) -> bytes:
    return encode_frame(BOARD_SYNC, SCAN_TYPE, board_id, scan_payload(ticks, **kw))


def center_frame(inner: bytes, channel: int = 2) -> bytes:
    return encode_frame(CENTER_SYNC, WRAPPED_TYPE, channel, inner)


class FrameParserTest(unittest.TestCase):
    def test_sizes_match_the_legacy_tools(self):
        self.assertEqual(len(board_frame(0)), 237)
        self.assertEqual(len(center_frame(board_frame(0))), 245)

    def test_byte_by_byte_with_garbage_in_front(self):
        p = FrameParser(BOARD_SYNC)
        out = []
        for b in b"\x01\x02\xfa" + board_frame(5) + board_frame(17):
            out += p.feed(bytes([b]))
        self.assertEqual([f.id for f in out], [1, 1])
        self.assertEqual(p.skipped, 3)

    def test_stray_sync_byte_before_a_frame(self):  # lost by the legacy parsers
        self.assertEqual(len(FrameParser(BOARD_SYNC).feed(b"\xfa" + board_frame(0))), 1)

    def test_frame_starting_inside_a_rejected_one_is_found(self):  # lost by the legacy parsers
        good = board_frame(7)
        false_start = BOARD_SYNC + bytes([SCAN_TYPE, 1, 20, 0]) + b"\x00" * 3  # claims 20 bytes, gets a real frame
        p = FrameParser(BOARD_SYNC)
        out = p.feed(false_start + good + b"\x00" * 20)
        self.assertEqual(len(out), 1)
        self.assertEqual(p.checksum_errors, 1)

    def test_impossible_length_resyncs_at_once(self):
        p = FrameParser(BOARD_SYNC, max_payload=300)
        out = p.feed(BOARD_SYNC + bytes([SCAN_TYPE, 1, 0xFF, 0xFF]) + board_frame(0))
        self.assertEqual(len(out), 1)
        self.assertEqual(p.oversize, 1)

    def test_empty_payload(self):
        out = FrameParser(BOARD_SYNC).feed(encode_frame(BOARD_SYNC, 0x10, 3, b""))
        self.assertEqual((out[0].type, out[0].id, out[0].payload), (0x10, 3, b""))


class ScanTest(unittest.TestCase):
    def test_decode(self):
        f = FrameParser(BOARD_SYNC).feed(board_frame(1234))[0]
        s = decode_scan(f, channel=None)
        self.assertEqual((s.board_id, s.ticks, len(s.sensor_ids)), (1, 1234, 25))
        np.testing.assert_array_equal(s.field[3], [1003, -2000, 3000])

    def test_malformed_payloads(self):
        frame = FrameParser(BOARD_SYNC).feed(encode_frame(BOARD_SYNC, SCAN_TYPE, 1, b"\x00" * 12))[0]
        self.assertIsNone(decode_scan(frame, None))  # (12 - 4) is not a whole number of records
        dup = scan_payload(0, n=2)
        dup = dup[:13] + bytes([0]) + dup[14:]  # second record claims sensor 0 too
        frame = FrameParser(BOARD_SYNC).feed(encode_frame(BOARD_SYNC, SCAN_TYPE, 1, dup))[0]
        self.assertIsNone(decode_scan(frame, None))


class StreamDecoderTest(unittest.TestCase):
    def test_auto_settles_on_center_and_keeps_the_channel(self):
        stream = center_frame(board_frame(0))[100:]  # joined midway
        stream += b"".join(center_frame(board_frame(12 * k)) for k in range(1, 6))
        d = StreamDecoder()
        scans = d.feed(stream)
        self.assertEqual(d.framing, "center")
        self.assertEqual({s.key for s in scans}, {(2, 1)})
        self.assertGreaterEqual(len(scans), 4)

    def test_auto_settles_on_direct(self):
        d = StreamDecoder()
        scans = d.feed(b"".join(board_frame(12 * k) for k in range(8)))
        self.assertEqual(d.framing, "direct")
        self.assertEqual({s.key for s in scans}, {(None, 1)})

    def test_several_boards_on_one_port(self):
        d = StreamDecoder("center")
        stream = b"".join(center_frame(board_frame(k, board_id=b), channel=b) for k in range(3) for b in range(4))
        d.feed(stream)
        self.assertEqual(sorted(d.stats.per_board), [(b, b) for b in range(4)])


class RecordingTest(unittest.TestCase):
    def test_bench_recording(self):  # the first 2 s of the 2026-10-28 capture, through the center board
        d = StreamDecoder()
        scans = [s for _, data in read_recording(DATA / "center-ch2_board1_2s.chunks") for s in d.feed(data)]
        self.assertEqual(d.framing, "center")
        self.assertGreater(len(scans), 150)
        self.assertEqual(d.stats.checksum_errors, 0)
        self.assertEqual({s.key for s in scans}, {(2, 1)})
        self.assertEqual(set(np.diff([s.ticks for s in scans]).tolist()), {12})

    def test_floating_line_gives_nothing(self):
        path = DATA / "floating-line_noise_10s.chunks"  # a lost link: junk, no frames
        d = StreamDecoder()
        self.assertEqual(sum(len(d.feed(data)) for _, data in read_recording(path)), 0)


if __name__ == "__main__":
    unittest.main()
