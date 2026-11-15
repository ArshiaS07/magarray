// Replay against the captures the Python decoder is tested on, and the Board's thread, queue and
// drain with an in-memory byte source that disconnects.
#include <gtest/gtest.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <memory>
#include <mutex>

#include "magarray/board.hpp"

using namespace magarray;
using namespace std::chrono_literals;
namespace fs = std::filesystem;

TEST(Replay, TheBenchCaptureDecodesAsInPython) {
    std::vector<Scan> scans;
    const DecoderStats st = replay(fs::path(MAGARRAY_FIXTURES) / "center-ch2_board1_2s.chunks",
                                   [&](const Scan& s) { scans.push_back(s); });
    EXPECT_EQ(st.framing, Framing::center);
    EXPECT_EQ(st.scans, 191u);
    EXPECT_EQ(st.checksum_errors, 0u);
    EXPECT_EQ(st.oversize, 0u);
    EXPECT_EQ(st.malformed, 0u);
    EXPECT_EQ(st.skipped_bytes, 233u);
    ASSERT_EQ(scans.size(), 191u);
    EXPECT_EQ(scans.front().key(), (Scan::Key{std::uint8_t{2}, std::uint8_t{1}}));
    EXPECT_EQ(scans.front().ticks, 428844u);
    EXPECT_EQ(scans.back().ticks, 431124u);
    for (std::size_t i = 1; i < scans.size(); ++i) EXPECT_EQ(scans[i].ticks - scans[i - 1].ticks, 12u);
    EXPECT_EQ(scans.front().sensor_ids.size(), 25u);
    EXPECT_EQ(scans.front().field[0], (std::array<std::int16_t, 3>{2211, -4616, 1304}));
    EXPECT_EQ(scans.front().field[24], (std::array<std::int16_t, 3>{-328, -5352, -541}));
    EXPECT_EQ(scans.front().w[0], -236);
    EXPECT_EQ(scans.front().received, 5449479608667);  // the recorded arrival, not now
}

TEST(Replay, AFloatingLineGivesNothing) {
    std::size_t n = 0;
    const DecoderStats st =
        replay(fs::path(MAGARRAY_FIXTURES) / "floating-line_noise_10s.chunks", [&](const Scan&) { ++n; });
    EXPECT_EQ(n, 0u);
    EXPECT_EQ(st.skipped_bytes, 1071u);
}

namespace {

// Serves a recording's bytes in its recorded reads, then reports the source gone; the second
// "connection" serves nothing and stays silent.
class ReplaySource final : public ByteSource {
public:
    ReplaySource(std::shared_ptr<std::atomic<int>> opens, recording::Recording rec) : opens_(opens), rec_(std::move(rec)) {
        ++*opens_;
    }
    std::optional<std::size_t> read(std::span<std::byte> out, std::chrono::milliseconds) override {
        if (*opens_ > 1) return 0;  // reconnected: silence
        if (i_ >= rec_.records.size()) return std::nullopt;  // the first connection ends
        const auto& b = rec_.records[i_++].bytes;
        const std::size_t n = std::min(out.size(), b.size());
        std::copy_n(b.begin(), n, out.begin());
        return n;
    }
    [[nodiscard]] std::string description() const override { return "replay"; }

private:
    std::shared_ptr<std::atomic<int>> opens_;
    recording::Recording rec_;
    std::size_t i_ = 0;
};

}  // namespace

TEST(Board, DrainsEveryScanAndReconnectsAfterTheSourceGoes) {
    auto opens = std::make_shared<std::atomic<int>>(0);
    const recording::Recording rec = recording::read(fs::path(MAGARRAY_FIXTURES) / "center-ch2_board1_2s.chunks");
    BoardOptions options;
    options.open = [opens, rec] { return std::make_unique<ReplaySource>(opens, rec); };
    options.reconnect_delay = 10ms;
    options.read_timeout = 5ms;
    Board board(std::move(options));
    std::size_t total = 0;
    const auto deadline = std::chrono::steady_clock::now() + 5s;
    while (std::chrono::steady_clock::now() < deadline && (total < 191 || board.status().reconnects == 0)) {
        board.wait_for(50ms);
        total += board.drain([](const Scan& s) { EXPECT_EQ(s.board_id, 1); });
    }
    EXPECT_EQ(total, 191u);
    const BoardStatus st = board.status();
    EXPECT_GE(st.reconnects, 1u);
    EXPECT_EQ(st.bytes, 47227u);
    EXPECT_EQ(st.decoder.scans, 191u);
    EXPECT_EQ(st.dropped, 0u);
    board.stop();
    EXPECT_TRUE(board.status().finished);
}
