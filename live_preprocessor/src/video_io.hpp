#pragma once
#include <sys/types.h>

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace aletheia::video {
// A whole startup window covers driver initialization even after fdsrc has
// consumed an initial frame. Normal playback keeps its short write deadline.
class PipelineTiming {
 public:
  void started(int64_t now_ms);
  int write_timeout_ms(int64_t now_ms) const;
  void written(int64_t now_ms);
  int failed(int64_t now_ms);
 private:
  int64_t started_at_ms_{-1};
  int64_t healthy_since_ms_{-1};
  int64_t last_written_ms_{-1};
  unsigned failures_{0};
};

// fd must be nonblocking. Timeout after a partial write invalidates the current
// parser stream: the caller must recreate its pipeline before the next frame.
bool write_pipe(int fd, const uint8_t *bytes, size_t length, const std::atomic<bool> &running, int &failure_errno, int timeout_ms = 250);
bool stop_child(pid_t child, int timeout_ms = 500);
// Linux: request SIGTERM if the owning runtime exits, including the race
// between reading its PID and installing the kernel parent-death signal.
bool bind_parent_lifetime(pid_t expected_parent);
}  // namespace aletheia::video
