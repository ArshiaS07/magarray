// The decoder, from bytes: the same cases as python/tests/test_wire.py.
#include <gtest/gtest.h>

#include <cstring>

#include "magarray/wire.hpp"

using namespace magarray;

namespace {

std::vector<std::byte> scan_payload(std::uint32_t ticks, std::size_t n = 25, int base = 1000) {
    std::vector<std::byte> p(4 + n * kRecordSize);
    std::memcpy(p.data(), &ticks, 4);
    for (std::size_t s = 0; s < n; ++s) {
        std::byte* r = p.data() + 4 + s * kRecordSize;
        r[0] = static_cast<std::byte>(s);
        const std::int16_t v[4] = {static_cast<std::int16_t>(base + static_cast<int>(s)), static_cast<std::int16_t>(-2 * base),
                                   static_cast<std::int16_t>(3 * base), static_cast<std::int16_t>(-(base + static_cast<int>(s)) / 9)};
        std::memcpy(r + 1, v, 8);
    }
    return p;
}

std::vector<std::byte> board_frame(std::uint32_t ticks, std::uint8_t board_id = 1, std::size_t n = 25) {
    return encode_frame(kBoardSync, kScanType, board_id, scan_payload(ticks, n));
}

std::vector<std::byte> center_frame(const std::vector<std::byte>& inner, std::uint8_t channel = 2) {
    return encode_frame(kCenterSync, kWrappedType, channel, inner);
}

std::vector<std::byte> cat(std::initializer_list<std::vector<std::byte>> parts) {
    std::vector<std::byte> out;
    for (const auto& p : parts) out.insert(out.end(), p.begin(), p.end());
    return out;
}

std::vector<std::byte> bytes(std::initializer_list<int> v) {
    std::vector<std::byte> out;
    for (int b : v) out.push_back(static_cast<std::byte>(b));
    return out;
}

}  // namespace

TEST(FrameParser, SizesMatchTheLegacyTools) {
    EXPECT_EQ(board_frame(0).size(), 237u);
    EXPECT_EQ(center_frame(board_frame(0)).size(), 245u);
}

TEST(FrameParser, ByteByByteWithGarbageInFront) {
    FrameParser p(kBoardSync);
    const auto stream = cat({bytes({0x01, 0x02, 0xFA}), board_frame(5), board_frame(17)});
    std::vector<Frame> out;
    for (std::byte b : stream) {
        auto got = p.feed(std::span<const std::byte>(&b, 1));
        out.insert(out.end(), got.begin(), got.end());
    }
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].id, 1);
    EXPECT_EQ(p.skipped, 3u);
}

TEST(FrameParser, StraySyncByteBeforeAFrame) {
    EXPECT_EQ(FrameParser(kBoardSync).feed(cat({bytes({0xFA}), board_frame(0)})).size(), 1u);
}

TEST(FrameParser, FrameStartingInsideARejectedOneIsFound) {
    const auto good = board_frame(7);
    const auto false_start = cat({bytes({0xFA, 0x70, kScanType, 1, 20, 0}), bytes({0, 0, 0})});
    FrameParser p(kBoardSync);
    const auto out = p.feed(cat({false_start, good, std::vector<std::byte>(20)}));
    EXPECT_EQ(out.size(), 1u);
    EXPECT_EQ(p.checksum_errors, 1u);
}

TEST(FrameParser, ImpossibleLengthResyncsAtOnce) {
    FrameParser p(kBoardSync, 300);
    const auto out = p.feed(cat({bytes({0xFA, 0x70, kScanType, 1, 0xFF, 0xFF}), board_frame(0)}));
    EXPECT_EQ(out.size(), 1u);
    EXPECT_EQ(p.oversize, 1u);
}

TEST(FrameParser, EmptyPayload) {
    const auto out = FrameParser(kBoardSync).feed(encode_frame(kBoardSync, 0x10, 3, {}));
    ASSERT_EQ(out.size(), 1u);
    EXPECT_EQ(out[0].type, 0x10);
    EXPECT_EQ(out[0].id, 3);
    EXPECT_TRUE(out[0].payload.empty());
}

TEST(Scan, Decode) {
    const auto f = FrameParser(kBoardSync).feed(board_frame(1234))[0];
    const auto s = decode_scan(f, std::nullopt);
    ASSERT_TRUE(s);
    EXPECT_EQ(s->board_id, 1);
    EXPECT_EQ(s->ticks, 1234u);
    EXPECT_EQ(s->sensor_ids.size(), 25u);
    EXPECT_EQ(s->field[3], (std::array<std::int16_t, 3>{1003, -2000, 3000}));
    EXPECT_FALSE(s->channel.has_value());
}

TEST(Scan, MalformedPayloads) {
    auto frame = FrameParser(kBoardSync).feed(encode_frame(kBoardSync, kScanType, 1, std::vector<std::byte>(12)))[0];
    EXPECT_FALSE(decode_scan(frame, std::nullopt));  // (12 - 4) is not a whole number of records
    auto dup = scan_payload(0, 2);
    dup[13] = std::byte{0};  // the second record claims sensor 0 too
    frame = FrameParser(kBoardSync).feed(encode_frame(kBoardSync, kScanType, 1, dup))[0];
    EXPECT_FALSE(decode_scan(frame, std::nullopt));
}

TEST(StreamDecoder, AutoSettlesOnCenterAndKeepsTheChannel) {
    auto stream = center_frame(board_frame(0));
    stream.erase(stream.begin(), stream.begin() + 100);  // joined midway
    for (std::uint32_t k = 1; k < 6; ++k) stream = cat({stream, center_frame(board_frame(12 * k))});
    StreamDecoder d;
    const auto scans = d.feed(stream);
    EXPECT_EQ(d.framing(), Framing::center);
    EXPECT_GE(scans.size(), 4u);
    for (const Scan& s : scans) EXPECT_EQ(s.key(), (Scan::Key{std::uint8_t{2}, std::uint8_t{1}}));
}

TEST(StreamDecoder, AutoSettlesOnDirect) {
    std::vector<std::byte> stream;
    for (std::uint32_t k = 0; k < 8; ++k) stream = cat({stream, board_frame(12 * k)});
    StreamDecoder d;
    const auto scans = d.feed(stream);
    EXPECT_EQ(d.framing(), Framing::direct);
    for (const Scan& s : scans) EXPECT_EQ(s.key(), (Scan::Key{std::nullopt, std::uint8_t{1}}));
}

TEST(StreamDecoder, SeveralBoardsOnOnePort) {
    StreamDecoder d(Framing::center);
    std::vector<std::byte> stream;
    for (std::uint32_t k = 0; k < 3; ++k)
        for (std::uint8_t b = 0; b < 4; ++b) stream = cat({stream, center_frame(board_frame(k, b), b)});
    d.feed(stream);
    ASSERT_EQ(d.stats().per_board.size(), 4u);
    for (std::uint8_t b = 0; b < 4; ++b) EXPECT_EQ(d.stats().per_board.at(Scan::Key{b, b}), 3u);
}
