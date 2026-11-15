// magarray_dump: a recording or a live port through the C++ decoder, summarised.
//   magarray_dump FILE.bsr                 counts per board, as `magarray info` prints them
//   magarray_dump --port /dev/ttyUSB1 [--seconds N] [--record BASE]   live, receive only
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>
#include <thread>

#include "magarray/board.hpp"

namespace {

struct Tally {
    std::size_t scans = 0;
    std::uint32_t first_ticks = 0, last_ticks = 0;
    std::map<std::uint32_t, std::size_t> steps;
    int peak = 0;
};

void count(std::map<magarray::Scan::Key, Tally>& boards, const magarray::Scan& s) {
    Tally& t = boards[s.key()];
    if (t.scans) ++t.steps[s.ticks - t.last_ticks];
    else t.first_ticks = s.ticks;
    t.last_ticks = s.ticks;
    ++t.scans;
    for (const auto& f : s.field)
        for (int v : f) t.peak = std::max(t.peak, std::abs(v));
}

void print(const std::map<magarray::Scan::Key, Tally>& boards, const magarray::DecoderStats& st) {
    std::printf("framing %s; scans %zu; checksum errors %zu; oversize %zu; malformed %zu; unknown types %zu; skipped %zu B\n",
                magarray::to_string(st.framing), st.scans, st.checksum_errors, st.oversize, st.malformed, st.unknown_types,
                st.skipped_bytes);
    for (const auto& [key, t] : boards) {
        std::printf("  board %u channel %s: %zu scans; tick steps {", key.second,
                    key.first ? std::to_string(*key.first).c_str() : "-", t.scans);
        for (const auto& [step, n] : t.steps) std::printf(" %u: %zu", step, n);
        std::printf(" }; peak |count| %d\n", t.peak);
    }
}

}  // namespace

int main(int argc, char** argv) {
    std::string port, record;
    double seconds = 10;
    std::string file;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--port" && i + 1 < argc) port = argv[++i];
        else if (a == "--record" && i + 1 < argc) record = argv[++i];
        else if (a == "--seconds" && i + 1 < argc) seconds = std::atof(argv[++i]);
        else file = a;
    }
    std::map<magarray::Scan::Key, Tally> boards;
    if (port.empty()) {
        if (file.empty()) {
            std::fprintf(stderr, "usage: magarray_dump FILE | --port DEV [--seconds N] [--record BASE]\n");
            return 2;
        }
        const magarray::DecoderStats st = magarray::replay(file, [&](const magarray::Scan& s) { count(boards, s); });
        std::printf("%s: ", file.c_str());
        print(boards, st);
        return 0;
    }
    magarray::BoardOptions options;
    options.open = [port] { return magarray::open_serial(port); };
    if (!record.empty()) options.record = record;
    magarray::Board board(std::move(options));
    const auto until = std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
    while (std::chrono::steady_clock::now() < until) {
        board.wait_for(std::chrono::milliseconds(200));
        board.drain([&](const magarray::Scan& s) { count(boards, s); });
        const magarray::BoardStatus st = board.status();
        std::fprintf(stderr, "\r%zu B, %zu scans%s%s\033[K", st.bytes, st.decoder.scans, st.connected ? "" : "  not reading: ",
                     st.connected ? "" : st.error.c_str());
    }
    board.stop();
    board.drain([&](const magarray::Scan& s) { count(boards, s); });
    std::fprintf(stderr, "\n");
    print(boards, board.status().decoder);
    return boards.empty() ? 1 : 0;
}
