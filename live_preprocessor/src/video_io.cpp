#include "video_io.hpp"

#include <poll.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <algorithm>
#include <chrono>
#include <csignal>
#include <thread>

namespace aletheia::video {

void PipelineTiming::started(int64_t now_ms) {
  started_at_ms_ = now_ms;
  healthy_since_ms_ = -1;
  last_written_ms_ = -1;
}

int PipelineTiming::write_timeout_ms(int64_t now_ms) const {
  const int64_t elapsed = now_ms - started_at_ms_;
  if (started_at_ms_ >= 0 && elapsed >= 0 && elapsed < 10000)
    return std::max(250,static_cast<int>(10000 - elapsed));
  return 250;
}

void PipelineTiming::written(int64_t now_ms) {
  if (healthy_since_ms_ < 0 || (last_written_ms_ >= 0 && now_ms-last_written_ms_ > 5000))
    healthy_since_ms_ = now_ms;
  last_written_ms_ = now_ms;
  if (now_ms - healthy_since_ms_ >= 60000) failures_ = 0;
}

int PipelineTiming::failed(int64_t) {
  healthy_since_ms_ = -1;
  last_written_ms_ = -1;
  started_at_ms_ = -1;
  const int delay = std::min(30000, 1000 << std::min(failures_, 5U));
  if (failures_ < 5) ++failures_;
  return delay;
}

bool bind_parent_lifetime(pid_t expected_parent) {
  if (expected_parent <= 1) {
    errno = ECHILD;
    return false;
  }
  if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0) return false;
  if (getppid() != expected_parent) {
    raise(SIGTERM);
    errno = ECHILD;
    return false;
  }
  return true;
}

bool write_pipe(int fd, const uint8_t *bytes, size_t length, const std::atomic<bool> &running, int &failure_errno, int timeout_ms) {
  failure_errno = 0;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
  while (length) {
    if (!running) {
      failure_errno = ECANCELED;
      return false;
    }
    if (std::chrono::steady_clock::now() >= deadline) {
      failure_errno = ETIMEDOUT;
      return false;
    }
    const ssize_t count = write(fd, bytes, length);
    if (count > 0) {
      bytes += count;
      length -= static_cast<size_t>(count);
      continue;
    }
    if (count < 0 && errno == EINTR) continue;
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      pollfd descriptor{fd, POLLOUT, 0};
      if (poll(&descriptor, 1, 10) < 0 && errno != EINTR) {
        failure_errno = errno;
        return false;
      }
      continue;
    }
    failure_errno = count < 0 ? errno : EPIPE;
    return false;
  }
  return true;
}

bool stop_child(pid_t child, int timeout_ms) {
  if (child <= 0) return true;
  // An exited child must be reaped before signaling to avoid PID reuse races.
  const pid_t first = waitpid(child, nullptr, WNOHANG);
  if (first == child || (first < 0 && errno == ECHILD)) return true;
  for (const int signal : {SIGTERM, SIGKILL}) {
    kill(child, signal);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    do {
      const pid_t result = waitpid(child, nullptr, WNOHANG);
      if (result == child || (result < 0 && errno == ECHILD)) return true;
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    } while (std::chrono::steady_clock::now() < deadline);
  }
  return false;
}

}  // namespace aletheia::video
