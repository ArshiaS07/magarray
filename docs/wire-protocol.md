# The board's wire protocol

The board: 5×5 LIS3MDL magnetometers and an MCU, streaming over UART, directly
or through a *center board* that carries up to four boards on one port. The
firmware is used as it is and its source was not read; what follows was
measured on the wire, with the layout first taken from two legacy host
programs by others. Direction: board → host only. Little-endian, no padding.

Evidence tags: **bench** (seen on the wire), **fit** (inferred from a magnet
moved over the board by the robot arm; the methods are in `mipe/docs/methods`),
**user** (stated, not yet seen), **unknown**.

## 1. Physical layer

| Item | Value | Evidence |
|---|---|---|
| Line | UART 921600 baud, 8N1, no flow control | bench |
| Modem lines | DTR and RTS unused; our readers hold both low | bench |
| Adapter | CP2102 (`/dev/serial/by-id/usb-Silicon_Labs_CP2102_…`) | bench |
| Logic levels, connector, pin-out | — | unknown |

## 2. Framing

```
FA 70 | type | id | len (u16) | payload (len bytes) | checksum (u16)
```

| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 2 | sync | `FA 70` |
| 2 | 1 | `type` | message type (section 4) |
| 3 | 1 | `id` | the board's id, counted from 0 |
| 4 | 2 | `len` | payload length, may be 0 |
| 6 | `len` | `payload` | |
| 6 + `len` | 2 | `checksum` | the sum of every byte from `type` through the payload, mod 65536 |

No sequence number, no version, no escaping; the sync pair can occur inside
a payload. All bench.

## 3. Receiving

1. Find the sync (`FA 70`, or `AD 69` behind a center board). A stream
   joined midway starts with a partial frame: discard up to the first sync.
2. Bound `len` by the largest payload expected; a larger one is a false sync.
3. Check the sum; a mismatch is a *checksum error*.
4. After any failure, resynchronise at the byte after the false sync, not
   after the rejected frame.
5. Validate the structure beyond the sum (4.1): a 16-bit sum misses reordered
   bytes. A frame with a wrong structure is *malformed*.
6. Count and skip unknown `type`s.
7. At port open, an adapter may deliver frames buffered from an earlier
   session: their board time is far behind. Readers that care drop scans
   until the board time runs on steadily.

`magarray.wire.StreamDecoder` does all of this and counts each case.

## 4. Messages

### 4.1 Scan (`type` 0x54)

One frame per scan: every sensor read once.

| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 4 | `time` | board time, u32 ticks |
| 4 + 9k | 1 | `sensor` | sensor id of record k |
| 5 + 9k | 2 | `x`, then `y`, `z` | i16 each: the field along the sensor's axes, in counts |
| 11 + 9k | 2 | `w` | i16: −0.10677·`x` on every sensor and sample (bench); carries nothing beyond `x` |

- **Records:** `(len − 4) / 9`; 25 for this board, so `len` = 229 and a frame
  is 237 bytes. Ids 0–24 in order. Structural checks: `(len − 4) mod 9 = 0`;
  ids unique.
- **Scan rate:** 80.1 Hz; `time` advances exactly 12 ticks per scan, never
  less or more in 63 562 scans. One tick is 1/960 s of host time; the board's
  clock runs within +1.6 ppm of the host (bench).
- **Each sensor samples at about 40 Hz on its own oscillator** (38.7–41.4 Hz),
  so about half of all readings repeat the previous scan's values exactly; a
  chance repeat is about 10⁻⁶ per reading. A reading is the sensor's latest
  sample, taken up to 25 ms before the scan. The decoder flags repeats
  (`fresh`); **a consumer that does not drop them counts every sample twice.**
- **Latency:** a fresh reading describes the field about 37 ms before its
  arrival at the host (fit, two sessions: 36.7 and 37.2 ms), covering
  sampling, the board, the center board and USB, less the arm's own delay.
- **Counts:** the full scale is ±4 gauss, 6842 counts/gauss, 14.6 nT a count
  (fit: a known magnet's moment comes out 1.07–1.09 × nominal only at this
  setting, and the sensors' offsets leave an Earth-like 44–47 µT). Saturation
  at ±32767. The firmware's setting would confirm it (unknown).
- **Axes:** right-handed; against the board's own grid frame, sensor x =
  board −x, y = +y, z = −z (into the board), each sensor within 1–3° of that
  (fit; the Earth's field points down only with right-handed axes).
- **Numbering (user, fit):** `id = row · 5 + column` from sensor 0, the
  corner next to the MCU; pitch 29.9 mm between rows and 25.0–25.4 mm along a
  row (fit).
- **Noise:** 29–42 counts per axis over 60 s at rest, including slow drift;
  21 counts for a 0.1 s mean (bench). Fast noise is uncorrelated between
  sensors.
- **Unknown:** how a scan's 25 reads spread over time; the LIS3MDL's mode;
  whether `time` marks a scan's start or end; what `w` is for.

### 4.2 Others

None seen.

## 5. Center-board envelope

The center board wraps each board frame, whole, in an outer frame of the same
layout and checksum rule: sync `AD 69`, `type` `0xAA`, `id` = the center
board's channel (counted from 1), payload = one complete board frame. A
wrapped scan is 245 bytes. The channel and the board's own `id` are
independent; the decoder keeps both. The bench board (id 0) arrives on
channel 1; an earlier board (id 1) on channel 2. A direct connection is not
yet seen on the wire (user: possible).

## 6. Bandwidth

92 160 B/s available; one board through the center board uses 80 × 245 =
19 600 B/s, so four would use 85 %.

## 7. Bench log

- 2026-10-28: 60 s through the center board at 921600 baud: 4805 scans, 0
  checksum errors, no missing scan. Earlier the same day, 0 bytes at every
  rate: wiring. After a link drop the RX line floated: about 420 B/s of
  `FF`/`FE`/`FD`, no frames, for minutes. **A lost link looks like junk, not
  silence.** Kept as a test fixture.
- 2026-11-04: 112 s under the arm; the first two scans were stale, 534 s old
  (the adapter's buffer). Board clock +1.57 ppm.
- 2026-11-08 and 09: 94 s and 795 s under the arm; the sessions behind the
  fit figures above. Peak 25 226 counts (77 % of full scale) at 40 mm.
- Open: four boards at once (channels, bandwidth); the firmware's settings.
