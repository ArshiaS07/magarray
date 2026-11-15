/// @file recording.hpp
/// Byte-stream recordings (docs/recording-format.md): every read with its arrival time. The
/// reader also takes the legacy `.chunks` (f64 seconds, no header) and `.bin` (bytes only).
#ifndef MAGARRAY_RECORDING_HPP
#define MAGARRAY_RECORDING_HPP

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <span>
#include <string>
#include <vector>

#include "magarray/wire.hpp"

namespace magarray::recording {

inline constexpr std::string_view kMagic = "BSTREAM1";
inline constexpr std::string_view kSuffix = ".bsr";

struct Record {
    HostNs arrival{};  ///< ns on the host's steady clock; 0 when the file had no times
    std::vector<std::byte> bytes;
};

struct Recording {
    std::vector<Record> records;
    std::string note;  ///< the header's JSON, verbatim; empty for a legacy file
    std::optional<std::int64_t> steady_ns_at_start;
    std::optional<std::int64_t> system_ns_at_start;
    bool timed = true;       ///< false for a bytes-only legacy file
    bool legacy = false;
    bool truncated = false;  ///< the last record was cut short: the recorder stopped mid-write

    [[nodiscard]] std::vector<std::byte> payload() const;
};

/// Reads the whole file. Throws std::system_error if it cannot be opened.
[[nodiscard]] Recording read(const std::filesystem::path& path);

/// `<base>.bsr`, unless the suffix is already there.
[[nodiscard]] std::filesystem::path recording_path(const std::filesystem::path& base);

/// Writes a recording as reads arrive: unbuffered, so what has arrived is on disk even if the
/// process dies; refuses an existing file unless `overwrite`; a file that received nothing is
/// removed on close.
class Writer {
public:
    Writer(const std::filesystem::path& path, std::string_view note_json = "{}", bool overwrite = false);
    ~Writer();
    Writer(const Writer&) = delete;
    Writer& operator=(const Writer&) = delete;

    void write(std::span<const std::byte> data, HostNs arrival);
    void close();
    [[nodiscard]] std::size_t written() const noexcept { return written_; }
    [[nodiscard]] const std::filesystem::path& path() const noexcept { return path_; }

private:
    std::filesystem::path path_;
    int fd_ = -1;
    std::size_t written_ = 0;
};

}  // namespace magarray::recording

#endif  // MAGARRAY_RECORDING_HPP
