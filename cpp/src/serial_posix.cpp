// A UART port on Linux: termios raw mode, an exclusive flock, DTR and RTS low, poll() with a
// timeout. Nothing here writes to the port.
#include <fcntl.h>
#include <poll.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#include <cerrno>
#include <system_error>

#include "magarray/board.hpp"

namespace magarray {

namespace {

speed_t baud_constant(unsigned baud) {
    switch (baud) {
        case 9600: return B9600;
        case 19200: return B19200;
        case 38400: return B38400;
        case 57600: return B57600;
        case 115200: return B115200;
        case 230400: return B230400;
        case 460800: return B460800;
        case 921600: return B921600;
        default: throw std::invalid_argument("unsupported baud rate");
    }
}

class SerialPort final : public ByteSource {
public:
    SerialPort(const std::filesystem::path& port, unsigned baud, bool assert_dtr) : path_(port.string()) {
        fd_ = ::open(path_.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
        if (fd_ < 0) throw std::system_error(errno, std::generic_category(), "open " + path_);
        if (::flock(fd_, LOCK_EX | LOCK_NB) != 0) {
            const int err = errno;
            ::close(fd_);
            throw std::system_error(err, std::generic_category(),
                                    "busy: another reader holds " + path_ + " (a suspended one?)");
        }
        termios tio{};
        if (::tcgetattr(fd_, &tio) != 0) fail("tcgetattr");
        ::cfmakeraw(&tio);
        tio.c_cflag |= CLOCAL | CREAD;
        tio.c_cflag &= ~static_cast<tcflag_t>(CRTSCTS);
        tio.c_cc[VMIN] = 0;
        tio.c_cc[VTIME] = 0;
        ::cfsetispeed(&tio, baud_constant(baud));
        ::cfsetospeed(&tio, baud_constant(baud));
        if (::tcsetattr(fd_, TCSANOW, &tio) != 0) fail("tcsetattr");
        int lines = TIOCM_RTS | (assert_dtr ? 0 : TIOCM_DTR);
        ::ioctl(fd_, TIOCMBIC, &lines);  // deassert; a USB adapter without modem lines ignores it
        if (assert_dtr) {
            int dtr = TIOCM_DTR;
            ::ioctl(fd_, TIOCMBIS, &dtr);
        }
        ::tcflush(fd_, TCIFLUSH);
    }
    ~SerialPort() override {
        if (fd_ >= 0) ::close(fd_);
    }

    std::optional<std::size_t> read(std::span<std::byte> out, std::chrono::milliseconds timeout) override {
        pollfd p{fd_, POLLIN, 0};
        const int r = ::poll(&p, 1, static_cast<int>(timeout.count()));
        if (r < 0) {
            if (errno == EINTR) return 0;
            return std::nullopt;
        }
        if (r == 0) return 0;
        if (p.revents & (POLLERR | POLLHUP | POLLNVAL)) return std::nullopt;
        const ssize_t n = ::read(fd_, out.data(), out.size());
        if (n < 0) return (errno == EAGAIN || errno == EINTR) ? std::optional<std::size_t>{0} : std::nullopt;
        if (n == 0) return std::nullopt;  // EOF: the device is gone
        return static_cast<std::size_t>(n);
    }

    [[nodiscard]] std::string description() const override { return path_; }

private:
    [[noreturn]] void fail(const char* what) {
        const int err = errno;
        ::close(fd_);
        throw std::system_error(err, std::generic_category(), std::string(what) + " " + path_);
    }
    std::string path_;
    int fd_ = -1;
};

}  // namespace

std::unique_ptr<ByteSource> open_serial(const std::filesystem::path& port, unsigned baud, bool assert_dtr) {
    return std::make_unique<SerialPort>(port, baud, assert_dtr);
}

}  // namespace magarray
