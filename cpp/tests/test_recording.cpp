// The recording format: round trip, refusal to overwrite, a cut-short record, the legacy layout.
#include <gtest/gtest.h>
#include <unistd.h>

#include <cstring>
#include <filesystem>
#include <fstream>

#include "magarray/recording.hpp"

using namespace magarray;
namespace fs = std::filesystem;

namespace {

std::vector<std::byte> text(const char* s) {
    std::vector<std::byte> out(std::strlen(s));
    std::memcpy(out.data(), s, out.size());
    return out;
}

struct TempDir {
    fs::path path = fs::temp_directory_path() / fs::path("magarray-test-" + std::to_string(::getpid()));
    TempDir() { fs::create_directories(path); }
    ~TempDir() { fs::remove_all(path); }
};

}  // namespace

TEST(Recording, RoundTripWithHeaderAndNote) {
    TempDir d;
    const fs::path path = d.path / "run.bsr";
    {
        recording::Writer w(path, R"({"device":"magarray"})");
        w.write(text("abc"), 5);
        EXPECT_EQ(recording::read(path).records.size(), 1u);  // on disk before close
        w.write(text("defg"), 7);
    }
    const recording::Recording rec = recording::read(path);
    ASSERT_EQ(rec.records.size(), 2u);
    EXPECT_EQ(rec.records[0].arrival, 5);
    EXPECT_EQ(rec.records[1].bytes, text("defg"));
    EXPECT_EQ(rec.payload(), text("abcdefg"));
    EXPECT_EQ(rec.note, R"({"device":"magarray"})");
    EXPECT_TRUE(rec.steady_ns_at_start && rec.system_ns_at_start);
    EXPECT_FALSE(rec.legacy);
    EXPECT_TRUE(rec.timed);
    EXPECT_FALSE(rec.truncated);
}

TEST(Recording, NeverReplacedByAccidentAndNoEmptyFiles) {
    TempDir d;
    const fs::path path = d.path / "run.bsr";
    {
        recording::Writer w(path);
        w.write(text("x"), 1);
    }
    EXPECT_THROW({ recording::Writer again(path); }, std::system_error);
    { recording::Writer w(path, "{}", true); }  // nothing arrived: removed on close
    EXPECT_FALSE(fs::exists(path));
}

TEST(Recording, ACutShortRecordIsReportedAndTheRestKept) {
    TempDir d;
    const fs::path path = d.path / "run.bsr";
    {
        recording::Writer w(path);
        w.write(text("whole"), 3);
    }
    {
        std::ofstream f(path, std::ios::binary | std::ios::app);
        const char partial[] = "\x09\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00par";  // claims 16 bytes, has 3
        f.write(partial, sizeof partial - 1);
    }
    const recording::Recording rec = recording::read(path);
    ASSERT_EQ(rec.records.size(), 1u);
    EXPECT_EQ(rec.records[0].bytes, text("whole"));
    EXPECT_TRUE(rec.truncated);
}

TEST(Recording, LegacyLayoutsStillRead) {
    const recording::Recording rec = recording::read(fs::path(MAGARRAY_FIXTURES) / "center-ch2_board1_2s.chunks");
    EXPECT_TRUE(rec.legacy);
    EXPECT_TRUE(rec.timed);
    EXPECT_FALSE(rec.truncated);
    EXPECT_EQ(rec.records.size(), 24u);
    EXPECT_EQ(rec.payload().size(), 47227u);
    EXPECT_EQ(rec.records.front().arrival, 5449479608667);  // f64 seconds, rounded to ns, as Python does
    EXPECT_EQ(rec.records.back().arrival, 5451781652915);
    TempDir d;
    const fs::path bin = d.path / "old.bin";
    std::ofstream(bin, std::ios::binary) << "raw bytes only";
    const recording::Recording b = recording::read(bin);
    EXPECT_FALSE(b.timed);
    EXPECT_TRUE(b.legacy);
    ASSERT_EQ(b.records.size(), 1u);
    EXPECT_EQ(b.records[0].bytes, text("raw bytes only"));
}

TEST(Recording, PathAddsTheSuffixOnce) {
    EXPECT_EQ(recording::recording_path("runs/x"), fs::path("runs/x.bsr"));
    EXPECT_EQ(recording::recording_path("runs/x.bsr"), fs::path("runs/x.bsr"));
}
