#include "magarray/recording.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <system_error>

namespace magarray::recording {

namespace {

template <class T>
T read_le(const std::byte* p) {
    T v{};
    std::memcpy(&v, p, sizeof v);  // little-endian host, as the Python side assumes
    return v;
}

// Records of (stamp, u32 length, bytes) from `i` on; `stamp_size` 8 for both layouts.
template <class Stamp, class ToNs>
std::pair<std::vector<Record>, bool> records_from(const std::vector<std::byte>& raw, std::size_t i, ToNs to_ns) {
    std::vector<Record> out;
    const std::size_t head = sizeof(Stamp) + 4;
    while (i + head <= raw.size()) {
        const Stamp t = read_le<Stamp>(raw.data() + i);
        const std::uint32_t n = read_le<std::uint32_t>(raw.data() + i + sizeof(Stamp));
        if (i + head + n > raw.size()) return {std::move(out), true};
        out.push_back(Record{to_ns(t), std::vector<std::byte>(raw.begin() + static_cast<std::ptrdiff_t>(i + head),
                                                              raw.begin() + static_cast<std::ptrdiff_t>(i + head + n))});
        i += head + n;
    }
    return {std::move(out), i != raw.size()};
}

void write_all(int fd, const void* data, std::size_t n) {
    const auto* p = static_cast<const std::byte*>(data);
    while (n) {
        const ssize_t w = ::write(fd, p, n);
        if (w < 0) {
            if (errno == EINTR) continue;
            throw std::system_error(errno, std::generic_category(), "write recording");
        }
        p += w;
        n -= static_cast<std::size_t>(w);
    }
}

}  // namespace

std::vector<std::byte> Recording::payload() const {
    std::vector<std::byte> out;
    for (const Record& r : records) out.insert(out.end(), r.bytes.begin(), r.bytes.end());
    return out;
}

std::filesystem::path recording_path(const std::filesystem::path& base) {
    if (base.extension() == kSuffix) return base;
    std::filesystem::path p = base;
    p += kSuffix;
    return p;
}

Recording read(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::system_error(errno, std::generic_category(), "open " + path.string());
    const std::string text((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    std::vector<std::byte> raw(text.size());
    std::memcpy(raw.data(), text.data(), text.size());
    Recording rec;
    if (raw.size() >= 28 && std::memcmp(raw.data(), kMagic.data(), 8) == 0) {
        rec.steady_ns_at_start = read_le<std::int64_t>(raw.data() + 8);
        rec.system_ns_at_start = read_le<std::int64_t>(raw.data() + 16);
        const std::uint32_t n = read_le<std::uint32_t>(raw.data() + 24);
        const std::size_t start = 28 + std::min<std::size_t>(n, raw.size() - 28);
        rec.note.assign(reinterpret_cast<const char*>(raw.data()) + 28, start - 28);
        auto [records, truncated] = records_from<std::int64_t>(raw, start, [](std::int64_t t) { return t; });
        rec.records = std::move(records);
        rec.truncated = truncated;
        return rec;
    }
    rec.legacy = true;
    if (path.extension() == ".bin") {
        rec.timed = false;
        rec.records.push_back(Record{0, std::move(raw)});
        return rec;
    }
    auto [records, truncated] =
        records_from<double>(raw, 0, [](double t) { return static_cast<HostNs>(std::llround(t * 1e9)); });
    rec.records = std::move(records);
    rec.truncated = truncated;
    return rec;
}

Writer::Writer(const std::filesystem::path& path, std::string_view note_json, bool overwrite) : path_(path) {
    if (!overwrite && std::filesystem::exists(path_))
        throw std::system_error(EEXIST, std::generic_category(), "already recorded: " + path_.string());
    if (path_.has_parent_path()) std::filesystem::create_directories(path_.parent_path());
    fd_ = ::open(path_.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd_ < 0) throw std::system_error(errno, std::generic_category(), "create " + path_.string());
    const std::int64_t steady = now_ns();
    const std::int64_t system =
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    const auto n = static_cast<std::uint32_t>(note_json.size());
    std::vector<std::byte> header(28 + note_json.size());
    std::memcpy(header.data(), kMagic.data(), 8);
    std::memcpy(header.data() + 8, &steady, 8);
    std::memcpy(header.data() + 16, &system, 8);
    std::memcpy(header.data() + 24, &n, 4);
    std::memcpy(header.data() + 28, note_json.data(), note_json.size());
    write_all(fd_, header.data(), header.size());
}

Writer::~Writer() {
    try {
        close();
    } catch (...) {  // a destructor cannot report; close() explicitly to see errors
    }
}

void Writer::write(std::span<const std::byte> data, HostNs arrival) {
    std::vector<std::byte> rec(12 + data.size());
    const auto n = static_cast<std::uint32_t>(data.size());
    std::memcpy(rec.data(), &arrival, 8);
    std::memcpy(rec.data() + 8, &n, 4);
    std::memcpy(rec.data() + 12, data.data(), data.size());
    write_all(fd_, rec.data(), rec.size());  // one write per read: a kill between reads loses nothing
    written_ += data.size();
}

void Writer::close() {
    if (fd_ < 0) return;
    ::close(fd_);
    fd_ = -1;
    if (written_ == 0) std::filesystem::remove(path_);
}

}  // namespace magarray::recording
