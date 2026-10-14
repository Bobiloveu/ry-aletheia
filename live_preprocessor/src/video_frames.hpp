#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace aletheia::video {

constexpr uint32_t kMaxDimension = 8192;
constexpr size_t kMaxPixels = 16U * 1024U * 1024U;
constexpr size_t kMaxFrameBytes = 64U * 1024U * 1024U;

struct FrameView {
  uint32_t width{}, height{}, stride{};
  std::string_view encoding;
  const uint8_t *bytes{};
  size_t byte_count{};
};

struct FrameLayout {
  uint32_t width{}, height{}, stride{};
  std::string format;
  bool operator==(const FrameLayout &other) const {
    return width == other.width && height == other.height && stride == other.stride && format == other.format;
  }
  bool operator!=(const FrameLayout &other) const { return !(*this == other); }
};

// Raw frames borrow the input owner's bytes; only JPEG needs a decoded buffer.
// Keep that owner alive until the pipe write completes.
struct PreparedFrame {
  FrameLayout layout;
  const uint8_t *borrowed{};
  size_t byte_count{};
  std::vector<uint8_t> decoded;
  const uint8_t *data() const { return decoded.empty() ? borrowed : decoded.data(); }
  size_t size() const { return decoded.empty() ? byte_count : decoded.size(); }
};

bool prepare_frame(const FrameView &source, PreparedFrame &output, std::string &error);

template <typename Frame>
class LatestFrameSlot {
 public:
  void publish(Frame frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    frame_ = std::move(frame);
  }
  Frame take() {
    std::lock_guard<std::mutex> lock(mutex_);
    return std::exchange(frame_, Frame{});
  }
  bool has_frame() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return bool(frame_);
  }

 private:
  mutable std::mutex mutex_;
  Frame frame_{};
};

class FrameBudget {
 public:
  explicit FrameBudget(int fps) : interval_us_(1'000'000 / fps) {}
  bool due(int64_t now_us) const { return now_us >= next_us_; }
  void consume(int64_t now_us) { next_us_ = now_us + interval_us_; }
  int64_t next_us() const { return next_us_; }

 private:
  int64_t interval_us_;
  int64_t next_us_{};
};

}  // namespace aletheia::video
