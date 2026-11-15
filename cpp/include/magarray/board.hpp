/// @file board.hpp
/// A board read live: a byte source behind a reader thread and a bounded queue, drained on the
/// caller's thread. The same shape as capsule's host `Device`, so a navigator drains every
/// device alike (mipe decisions 0007, 0008). Receive only: the port is opened with DTR and RTS
/// low and nothing is ever written to it.
#ifndef MAGARRAY_BOARD_HPP
#define MAGARRAY_BOARD_HPP

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "magarray/recording.hpp"
#include "magarray/wire.hpp"

namespace magarray {

/// Where bytes come from. `read` returns how many bytes it put into `out`: 0 on a timeout, and
/// an empty optional once the source is gone (unplugged, closed), after which it is discarded.
class ByteSource {
public:
    virtual ~ByteSource() = default;
    virtual std::optional<std::size_t> read(std::span<std::byte> out, std::chrono::milliseconds timeout) = 0;
    [[nodiscard]] virtual std::string description() const = 0;
};

/// A UART port (Linux): raw, 8N1, no flow control, DTR and RTS deasserted, locked exclusively so
/// a second reader fails to open instead of splitting the bytes. Throws std::system_error.
std::unique_ptr<ByteSource> open_serial(const std::filesystem::path& port, unsigned baud = 921600,
                                        bool assert_dtr = false);

struct BoardOptions {
    std::function<std::unique_ptr<ByteSource>()> open;  ///< called on start and on every reconnect
    Framing framing = Framing::automatic;
    std::size_t queue_capacity = 4096;                   ///< scans kept for the consumer; older ones are dropped
    std::chrono::milliseconds read_timeout{50};
    std::chrono::milliseconds reconnect_delay{500};
    std::optional<std::filesystem::path> record;         ///< tee every read to this `.bsr`
    std::string record_note = "{}";
    bool overwrite_recording = false;
};

struct BoardStatus {
    bool connected = false;
    bool finished = false;        ///< the reader thread has stopped
    std::size_t bytes = 0;
    std::size_t reconnects = 0;
    std::size_t dropped = 0;      ///< scans dropped because the consumer fell behind
    std::string error;            ///< the last open or read error, empty when none
    DecoderStats decoder;
};

class Board {
public:
    explicit Board(BoardOptions options);
    ~Board();
    Board(const Board&) = delete;
    Board& operator=(const Board&) = delete;

    /// Hands every queued scan, oldest first, to `sink(const Scan&)` on the caller's thread.
    /// @return how many.
    template <class Sink>
    std::size_t drain(Sink&& sink) {
        std::vector<Scan> taken = take();
        for (const Scan& s : taken) sink(s);
        return taken.size();
    }

    /// Blocks until a scan is queued or `timeout` passes. @return whether one is there.
    bool wait_for(std::chrono::milliseconds timeout);

    [[nodiscard]] BoardStatus status() const;
    void stop() noexcept;

private:
    std::vector<Scan> take();
    void run(const std::stop_token& stop);
    void push(std::vector<Scan>& scans);

    BoardOptions options_;
    StreamDecoder decoder_;
    std::unique_ptr<recording::Writer> writer_;
    mutable std::mutex mutex_;
    std::condition_variable_any ready_;
    std::vector<Scan> queue_;
    BoardStatus status_;
    std::jthread thread_;
};

/// A recording through the same decoder, synchronously, each scan stamped with its recorded
/// arrival; `sink(const Scan&)` per scan. @return the decoder's counts.
template <class Sink>
DecoderStats replay(const std::filesystem::path& path, Sink&& sink, Framing framing = Framing::automatic) {
    StreamDecoder decoder(framing);
    std::vector<Scan> scans;
    for (const recording::Record& r : recording::read(path).records) {
        scans.clear();
        decoder.feed(r.bytes, r.arrival, scans);
        for (const Scan& s : scans) sink(s);
    }
    return decoder.stats();
}

}  // namespace magarray

#endif  // MAGARRAY_BOARD_HPP
