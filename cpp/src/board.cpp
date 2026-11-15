#include "magarray/board.hpp"

#include <array>

namespace magarray {

Board::Board(BoardOptions options) : options_(std::move(options)), decoder_(options_.framing) {
    if (!options_.open) throw std::invalid_argument("Board: options.open is required");
    if (options_.record)
        writer_ = std::make_unique<recording::Writer>(recording::recording_path(*options_.record),
                                                      options_.record_note, options_.overwrite_recording);
    thread_ = std::jthread([this](const std::stop_token& stop) { run(stop); });
}

Board::~Board() {
    stop();
}

void Board::stop() noexcept {
    thread_.request_stop();
    ready_.notify_all();
    if (thread_.joinable()) thread_.join();
}

std::vector<Scan> Board::take() {
    std::lock_guard lock(mutex_);
    std::vector<Scan> out;
    out.swap(queue_);
    return out;
}

bool Board::wait_for(std::chrono::milliseconds timeout) {
    std::unique_lock lock(mutex_);
    return ready_.wait_for(lock, timeout, [this] { return !queue_.empty() || status_.finished; }) && !queue_.empty();
}

BoardStatus Board::status() const {
    std::lock_guard lock(mutex_);
    BoardStatus s = status_;
    s.decoder = decoder_.stats();
    return s;
}

void Board::push(std::vector<Scan>& scans) {
    if (scans.empty()) return;
    {
        std::lock_guard lock(mutex_);
        for (Scan& s : scans) queue_.push_back(std::move(s));
        if (queue_.size() > options_.queue_capacity) {
            const std::size_t excess = queue_.size() - options_.queue_capacity;
            queue_.erase(queue_.begin(), queue_.begin() + static_cast<std::ptrdiff_t>(excess));
            status_.dropped += excess;
        }
    }
    scans.clear();
    ready_.notify_all();
}

void Board::run(const std::stop_token& stop) {
    std::array<std::byte, 4096> buf{};
    std::vector<Scan> scans;
    bool first = true;
    while (!stop.stop_requested()) {
        std::unique_ptr<ByteSource> source;
        try {
            source = options_.open();
        } catch (const std::exception& e) {
            std::lock_guard lock(mutex_);
            status_.connected = false;
            status_.error = e.what();
        }
        if (!source) {
            std::mutex m;
            std::unique_lock lock(m);
            std::condition_variable_any().wait_for(lock, stop, options_.reconnect_delay, [] { return false; });
            continue;
        }
        {
            std::lock_guard lock(mutex_);
            status_.connected = true;
            status_.error.clear();
            if (!first) ++status_.reconnects;
            first = false;
            decoder_.restart();
        }
        while (!stop.stop_requested()) {
            std::optional<std::size_t> n;
            try {
                n = source->read(buf, options_.read_timeout);
            } catch (const std::exception& e) {
                std::lock_guard lock(mutex_);
                status_.error = e.what();
                n = std::nullopt;
            }
            if (!n) break;  // the source is gone: reconnect
            if (*n == 0) continue;
            const HostNs received = now_ns();
            const std::span<const std::byte> data(buf.data(), *n);
            if (writer_) writer_->write(data, received);
            {
                std::lock_guard lock(mutex_);
                status_.bytes += *n;
                decoder_.feed(data, received, scans);
            }
            push(scans);
        }
        std::lock_guard lock(mutex_);
        status_.connected = false;
    }
    if (writer_) writer_->close();
    std::lock_guard lock(mutex_);
    status_.connected = false;
    status_.finished = true;
    ready_.notify_all();
}

}  // namespace magarray
