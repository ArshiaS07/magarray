#include "magarray/wire.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <set>

namespace magarray {

HostNs now_ns() noexcept {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::uint16_t checksum(std::span<const std::byte> body) noexcept {
    std::uint32_t sum = 0;
    for (std::byte b : body) sum += std::to_integer<std::uint32_t>(b);
    return static_cast<std::uint16_t>(sum & 0xFFFFu);
}

std::vector<std::byte> encode_frame(std::span<const std::byte, 2> sync, std::uint8_t type, std::uint8_t id,
                                    std::span<const std::byte> payload) {
    std::vector<std::byte> out;
    out.reserve(8 + payload.size());
    out.insert(out.end(), sync.begin(), sync.end());
    out.push_back(std::byte{type});
    out.push_back(std::byte{id});
    out.push_back(static_cast<std::byte>(payload.size() & 0xFF));
    out.push_back(static_cast<std::byte>((payload.size() >> 8) & 0xFF));
    out.insert(out.end(), payload.begin(), payload.end());
    const std::uint16_t sum = checksum(std::span<const std::byte>(out).subspan(2));
    out.push_back(static_cast<std::byte>(sum & 0xFF));
    out.push_back(static_cast<std::byte>(sum >> 8));
    return out;
}

std::vector<Frame> FrameParser::feed(std::span<const std::byte> data) {
    buf_.insert(buf_.end(), data.begin(), data.end());
    std::vector<Frame> out;
    for (;;) {
        const auto it = std::search(buf_.begin(), buf_.end(), sync_.begin(), sync_.end());
        if (it == buf_.end()) {
            const std::size_t keep = (!buf_.empty() && buf_.back() == sync_[0]) ? 1 : 0;  // maybe a sync's start
            skipped += buf_.size() - keep;
            buf_.erase(buf_.begin(), buf_.end() - static_cast<std::ptrdiff_t>(keep));
            break;
        }
        const auto i = static_cast<std::size_t>(it - buf_.begin());
        if (i) {
            skipped += i;
            buf_.erase(buf_.begin(), buf_.begin() + static_cast<std::ptrdiff_t>(i));
        }
        if (buf_.size() < 6) break;
        const std::size_t length = std::to_integer<std::size_t>(buf_[4]) | (std::to_integer<std::size_t>(buf_[5]) << 8);
        if (length > max_) {
            ++oversize;
            ++skipped;
            buf_.erase(buf_.begin());
            continue;
        }
        const std::size_t end = 8 + length;
        if (buf_.size() < end) break;
        const std::uint16_t sent =
            static_cast<std::uint16_t>(std::to_integer<unsigned>(buf_[end - 2]) | (std::to_integer<unsigned>(buf_[end - 1]) << 8));
        if (checksum(std::span<const std::byte>(buf_).subspan(2, end - 4)) != sent) {
            ++checksum_errors;
            ++skipped;
            buf_.erase(buf_.begin());
            continue;
        }
        out.push_back(Frame{std::to_integer<std::uint8_t>(buf_[2]), std::to_integer<std::uint8_t>(buf_[3]),
                            std::vector<std::byte>(buf_.begin() + 6, buf_.begin() + static_cast<std::ptrdiff_t>(end - 2))});
        ++frames;
        buf_.erase(buf_.begin(), buf_.begin() + static_cast<std::ptrdiff_t>(end));
    }
    return out;
}

std::optional<Scan> decode_scan(const Frame& frame, std::optional<std::uint8_t> channel, HostNs received) {
    const auto& p = frame.payload;
    if (p.size() < 4 || (p.size() - 4) % kRecordSize != 0) return std::nullopt;
    const std::size_t n = (p.size() - 4) / kRecordSize;
    Scan s;
    s.received = received;
    s.channel = channel;
    s.board_id = frame.id;
    std::uint32_t ticks = 0;
    std::memcpy(&ticks, p.data(), 4);  // little-endian host assumed, as the Python side does
    s.ticks = ticks;
    s.sensor_ids.reserve(n);
    s.field.reserve(n);
    s.w.reserve(n);
    std::set<std::uint8_t> seen;
    for (std::size_t k = 0; k < n; ++k) {
        const std::byte* r = p.data() + 4 + k * kRecordSize;
        const auto id = std::to_integer<std::uint8_t>(r[0]);
        if (!seen.insert(id).second) return std::nullopt;
        std::array<std::int16_t, 4> v{};
        std::memcpy(v.data(), r + 1, 8);
        s.sensor_ids.push_back(id);
        s.field.push_back({v[0], v[1], v[2]});
        s.w.push_back(v[3]);
    }
    s.repeated.assign(n, false);
    return s;
}

const char* to_string(Framing f) noexcept {
    switch (f) {
        case Framing::automatic: return "auto";
        case Framing::center: return "center";
        case Framing::direct: return "direct";
    }
    return "?";
}

StreamDecoder::StreamDecoder(Framing framing) : center_(kCenterSync), direct_(kBoardSync) {
    stats_.framing = framing;
}

std::vector<Scan> StreamDecoder::feed(std::span<const std::byte> data, HostNs received) {
    std::vector<Scan> out;
    feed(data, received, out);
    return out;
}

void StreamDecoder::feed(std::span<const std::byte> data, HostNs received, std::vector<Scan>& out) {
    Framing mode = stats_.framing;
    if (mode == Framing::automatic || mode == Framing::center) {
        for (const Frame& f : center_.feed(data)) {
            if (mode == Framing::automatic) mode = stats_.framing = Framing::center;
            if (f.type != kWrappedType) {
                ++stats_.unknown_types;
                continue;
            }
            auto [it, inserted] = inner_.try_emplace(f.id, kBoardSync);
            for (const Frame& g : it->second.feed(f.payload)) add(g, f.id, received, out);
        }
    }
    if (mode == Framing::automatic || mode == Framing::direct) {
        const std::vector<Frame> frames = direct_.feed(data);
        if (mode == Framing::automatic && direct_.frames >= kDirectAfter && center_.frames == 0)
            mode = stats_.framing = Framing::direct;
        if (mode == Framing::direct)
            for (const Frame& g : frames) add(g, std::nullopt, received, out);
    }
    update_counters();
}

void StreamDecoder::restart() noexcept {
    center_.reset();
    direct_.reset();
    for (auto& [id, p] : inner_) p.reset();
}

void StreamDecoder::add(const Frame& frame, std::optional<std::uint8_t> channel, HostNs received,
                        std::vector<Scan>& out) {
    if (frame.type != kScanType) {
        ++stats_.unknown_types;
        return;
    }
    std::optional<Scan> scan = decode_scan(frame, channel, received);
    if (!scan) {
        ++stats_.malformed;
        return;
    }
    ++stats_.scans;
    ++stats_.per_board[scan->key()];
    auto& last = last_[scan->key()];
    for (std::size_t k = 0; k < scan->sensor_ids.size(); ++k) {
        const auto [it, first] = last.try_emplace(scan->sensor_ids[k], scan->field[k]);
        if (!first) {
            scan->repeated[k] = it->second == scan->field[k];
            it->second = scan->field[k];
        }
    }
    out.push_back(std::move(*scan));
}

void StreamDecoder::update_counters() {
    std::vector<const FrameParser*> parsers;
    switch (stats_.framing) {
        case Framing::center:
            parsers.push_back(&center_);
            for (const auto& [id, p] : inner_) parsers.push_back(&p);
            break;
        case Framing::direct: parsers.push_back(&direct_); break;
        case Framing::automatic:
            parsers.push_back(&center_);
            parsers.push_back(&direct_);
            break;
    }
    stats_.checksum_errors = 0;
    stats_.oversize = 0;
    for (const FrameParser* p : parsers) {
        stats_.checksum_errors += p->checksum_errors;
        stats_.oversize += p->oversize;
    }
    stats_.skipped_bytes = (stats_.framing == Framing::direct ? direct_ : center_).skipped;
}

}  // namespace magarray
