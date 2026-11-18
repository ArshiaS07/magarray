/// @file wire.hpp
/// The board's wire protocol (docs/wire-protocol.md): bytes in, scans out. No I/O, no threads.
/// Mirrors python/magarray/wire.py; both are tested against the same captures.
#ifndef MAGARRAY_WIRE_HPP
#define MAGARRAY_WIRE_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <utility>
#include <vector>

namespace magarray {

/// The host's steady clock in ns (CLOCK_MONOTONIC on Linux; the clock every recording uses).
using HostNs = std::int64_t;
[[nodiscard]] HostNs now_ns() noexcept;

constexpr std::array<std::byte, 2> kBoardSync{std::byte{0xFA}, std::byte{0x70}};
constexpr std::array<std::byte, 2> kCenterSync{std::byte{0xAD}, std::byte{0x69}};
constexpr std::uint8_t kScanType = 0x54;     ///< board frame: one scan of the array
constexpr std::uint8_t kWrappedType = 0xAA;  ///< center-board frame: one whole board frame
constexpr std::size_t kRecordSize = 9;       ///< sensor id, x, y, z, w
constexpr std::size_t kMaxPayload = 4 + kRecordSize * 256 + 8;  ///< longer is a false sync
constexpr double kTicksPerSecond = 960.0;    ///< board time (wire protocol 4.1)

struct Frame {
    std::uint8_t type{};
    std::uint8_t id{};
    std::vector<std::byte> payload;
};

/// One scan of one board, as on the wire: raw counts, nothing scaled.
struct Scan {
    HostNs received{};                   ///< arrival of the read that completed it; 0 when unknown
    std::optional<std::uint8_t> channel; ///< center-board channel; empty when read directly
    std::uint8_t board_id{};
    std::uint32_t ticks{};               ///< board time, as sent (wraps after 51.8 days)
    std::vector<std::uint8_t> sensor_ids;
    std::vector<std::array<std::int16_t, 3>> field;  ///< counts, sensor axes, per sensor
    std::vector<std::int16_t> w;                     ///< not interpreted
    /// Per sensor: the same counts as in this board's previous scan. The board reads every sensor
    /// each scan (12.5 ms), faster than an LIS3MDL updates its output (25 ms at 40 Hz), so about
    /// every other reading is the last sample again, not a new one. Nothing on the wire says so;
    /// equal counts on all three axes do (a new sample equal to the last one by chance is about one
    /// in a few million at the board's noise, some 40 counts per axis). Set by StreamDecoder; all
    /// false from decode_scan.
    std::vector<bool> repeated;

    using Key = std::pair<std::optional<std::uint8_t>, std::uint8_t>;
    [[nodiscard]] Key key() const { return {channel, board_id}; }
};

/// The sum of `body` mod 65536: the frame's checksum over type, id, length and payload.
[[nodiscard]] std::uint16_t checksum(std::span<const std::byte> body) noexcept;

/// The inverse of FrameParser, for tests and simulation.
[[nodiscard]] std::vector<std::byte> encode_frame(std::span<const std::byte, 2> sync, std::uint8_t type,
                                                  std::uint8_t id, std::span<const std::byte> payload);

/// Frames with one sync pair from a byte stream fed in pieces of any size. Joins a stream
/// midway; after a false sync (bad checksum, impossible length) it resumes one byte later, so a
/// real frame starting inside a rejected one is still found.
class FrameParser {
public:
    explicit FrameParser(std::array<std::byte, 2> sync, std::size_t max_payload = kMaxPayload) noexcept
        : sync_(sync), max_(max_payload) {}

    std::vector<Frame> feed(std::span<const std::byte> data);
    void reset() noexcept { buf_.clear(); }

    std::size_t frames = 0;
    std::size_t checksum_errors = 0;
    std::size_t oversize = 0;
    std::size_t skipped = 0;  ///< bytes that were not part of any frame

private:
    std::array<std::byte, 2> sync_;
    std::size_t max_;
    std::vector<std::byte> buf_;
};

/// A scan from a frame of kScanType; empty if the payload is malformed (a partial record, a
/// repeated sensor id).
[[nodiscard]] std::optional<Scan> decode_scan(const Frame& frame, std::optional<std::uint8_t> channel,
                                              HostNs received = 0);

enum class Framing : std::uint8_t { automatic, center, direct };
[[nodiscard]] const char* to_string(Framing f) noexcept;

struct DecoderStats {
    Framing framing = Framing::automatic;
    std::size_t scans = 0;
    std::size_t checksum_errors = 0;
    std::size_t oversize = 0;
    std::size_t malformed = 0;
    std::size_t unknown_types = 0;
    std::size_t skipped_bytes = 0;
    std::map<Scan::Key, std::size_t> per_board;
};

/// Scans from a board's stream, direct or through the center board. `automatic` settles on
/// `center` as soon as a center-board frame is valid, or on `direct` after a few board frames
/// and no center-board frame: a center stream also contains valid board frames, inside its own.
/// Scans decoded before it settles are dropped.
class StreamDecoder {
public:
    explicit StreamDecoder(Framing framing = Framing::automatic);

    /// Decodes `data`, appending scans to `out`; `received` stamps each.
    void feed(std::span<const std::byte> data, HostNs received, std::vector<Scan>& out);
    [[nodiscard]] std::vector<Scan> feed(std::span<const std::byte> data, HostNs received = 0);

    /// Drops partial frames, e.g. after a reconnect; the framing and the counts are kept.
    void restart() noexcept;

    [[nodiscard]] const DecoderStats& stats() const noexcept { return stats_; }
    [[nodiscard]] Framing framing() const noexcept { return stats_.framing; }

private:
    static constexpr std::size_t kDirectAfter = 4;
    void add(const Frame& frame, std::optional<std::uint8_t> channel, HostNs received, std::vector<Scan>& out);
    void update_counters();

    DecoderStats stats_;
    FrameParser center_;
    FrameParser direct_;
    std::map<std::uint8_t, FrameParser> inner_;
    /// Each board's last counts, per sensor id: what marks a repeat. Kept across restart(): a
    /// sensor's registers hold their sample through a reconnect.
    std::map<Scan::Key, std::map<std::uint8_t, std::array<std::int16_t, 3>>> last_;
};

}  // namespace magarray

#endif  // MAGARRAY_WIRE_HPP
