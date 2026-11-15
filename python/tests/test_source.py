import math
import tempfile
import unittest
from pathlib import Path

from magarray.cli import default_port
from magarray.recording import MAGIC, Writer, read, recording_path
from magarray.source import read_recording

DATA = Path(__file__).parent / "data"


class RecordingTest(unittest.TestCase):
    def test_round_trip_with_header_and_note(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "run.bsr"
            w = Writer(path, note={"device": "magarray", "port": "ttyUSB1"})
            w.write(b"abc", 5)
            self.assertEqual(read(path).records, [(5, b"abc")])  # on disk before close: a kill loses nothing
            w.write(b"defg", 7)
            w.close()
            rec = read(path)
            self.assertEqual(path.read_bytes()[:8], MAGIC)
            self.assertEqual(rec.records, [(5, b"abc"), (7, b"defg")])
            self.assertEqual(rec.payload(), b"abcdefg")
            self.assertEqual(rec.note, {"device": "magarray", "port": "ttyUSB1"})
            self.assertIsInstance(rec.steady_ns_at_start, int)
            self.assertIsInstance(rec.system_ns_at_start, int)
            self.assertEqual((rec.legacy, rec.timed, rec.truncated), (False, True, False))

    def test_never_replaced_by_accident_and_no_empty_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "run.bsr"
            w = Writer(path)
            w.write(b"x", 1)
            w.close()
            with self.assertRaises(FileExistsError):
                Writer(path)
            Writer(path, overwrite=True).close()  # nothing arrived: no empty file left to block the name
            self.assertFalse(path.exists())

    def test_a_cut_short_record_is_reported_and_the_rest_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "run.bsr"
            w = Writer(path)
            w.write(b"whole", 3)
            w.close()
            with open(path, "ab") as f:
                f.write(b"\x09\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00par")  # claims 16 bytes, has 3
            rec = read(path)
            self.assertEqual(rec.records, [(3, b"whole")])
            self.assertTrue(rec.truncated)

    def test_legacy_layouts_still_read(self):
        rec = read(DATA / "center-ch2_board1_2s.chunks")
        self.assertTrue(rec.legacy and rec.timed and not rec.truncated)
        arrivals = [t for t, _ in rec.records]
        self.assertTrue(all(isinstance(t, int) for t in arrivals))
        self.assertEqual(arrivals, sorted(arrivals))
        self.assertGreater(len(rec.payload()), 40_000)
        seconds = [t for t, _ in read_recording(DATA / "center-ch2_board1_2s.chunks")]
        self.assertAlmostEqual(seconds[0], arrivals[0] / 1e9)
        with tempfile.TemporaryDirectory() as d:
            bin_path = Path(d) / "old.bin"
            bin_path.write_bytes(b"raw bytes only")
            rec = read(bin_path)
            self.assertEqual((rec.timed, rec.legacy, rec.records), (False, True, [(0, b"raw bytes only")]))
            self.assertTrue(math.isnan(read_recording(bin_path)[0][0]))

    def test_recording_path_adds_the_suffix_once(self):
        self.assertEqual(recording_path("runs/x"), Path("runs/x.bsr"))
        self.assertEqual(recording_path("runs/x.bsr"), Path("runs/x.bsr"))


class DefaultPortTest(unittest.TestCase):
    PHONE = "usb-SAMSUNG_SAMSUNG_Android_R5CW82BLCJL-if01"
    BOARD = "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"

    def ports(self, d, *names):
        for n in names:
            (Path(d) / n).touch()
        return Path(d)

    def test_the_board_over_a_phone_that_sorts_first(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(default_port(self.ports(d, self.PHONE, self.BOARD)), f"{d}/{self.BOARD}")

    def test_the_only_port_whatever_it_is(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(default_port(self.ports(d, self.PHONE)), f"{d}/{self.PHONE}")

    def test_asks_when_it_cannot_tell(self):
        with tempfile.TemporaryDirectory() as d:
            for names in ((), (self.PHONE, "usb-FTDI_capsule-if00"), (self.BOARD, self.BOARD.replace("0001", "0002"))):
                with self.subTest(names=names), self.assertRaises(SystemExit):
                    default_port(self.ports(tempfile.mkdtemp(dir=d), *names))


if __name__ == "__main__":
    unittest.main()
