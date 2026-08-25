#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

struct Options {
  std::string node_name;
  std::string topic;
  std::string gst_launch;
  std::string vaapi_device;
  std::string rtsp_url;
  int width{};
  int height{};
  int fps{};
  int bitrate_kbps{};
};

int parse_positive(const char *value, const char *name) {
  try {
    const int result = std::stoi(value);
    if (result > 0) {
      return result;
    }
  } catch (const std::exception &) {
  }
  throw std::runtime_error(std::string(name) + " 必须是正整数");
}

bool is_ros_name(const std::string &value) {
  if (value.empty() || !(std::isalpha(static_cast<unsigned char>(value.front())) || value.front() == '_')) return false;
  return std::all_of(value.begin(), value.end(), [](unsigned char character) {
    return std::isalnum(character) || character == '_';
  });
}

Options parse_options(int argc, char **argv) {
  Options options;
  for (int index = 1; index < argc; index += 2) {
    if (index + 1 >= argc) {
      throw std::runtime_error("视频输入参数缺少值");
    }
    const std::string key(argv[index]);
    const char *value = argv[index + 1];
    if (key == "--node-name") options.node_name = value;
    else if (key == "--topic") options.topic = value;
    else if (key == "--gst-launch") options.gst_launch = value;
    else if (key == "--vaapi-device") options.vaapi_device = value;
    else if (key == "--rtsp-url") options.rtsp_url = value;
    else if (key == "--width") options.width = parse_positive(value, "width");
    else if (key == "--height") options.height = parse_positive(value, "height");
    else if (key == "--fps") options.fps = parse_positive(value, "fps");
    else if (key == "--bitrate-kbps") options.bitrate_kbps = parse_positive(value, "bitrate-kbps");
    else throw std::runtime_error("未知视频输入参数：" + key);
  }
  if (!is_ros_name(options.node_name) || options.topic.empty() || options.gst_launch.empty() || options.vaapi_device.empty() || options.rtsp_url.empty() ||
      !options.width || !options.height || !options.fps || !options.bitrate_kbps) {
    throw std::runtime_error("必须提供安全的 node-name、topic、gst-launch、vaapi-device、rtsp-url、width、height、fps 和 bitrate-kbps");
  }
  return options;
}

class VideoIngest final : public rclcpp::Node {
 public:
  explicit VideoIngest(Options options)
      : Node(options.node_name), options_(std::move(options)) {
    std::signal(SIGPIPE, SIG_IGN);
    start_pipeline();
    const auto qos = rclcpp::SensorDataQoS().keep_last(1);
    subscription_ = create_subscription<sensor_msgs::msg::Image>(
        options_.topic, qos, [this](sensor_msgs::msg::Image::ConstSharedPtr image) {
          if (image->encoding != "rgb8" || image->width != static_cast<uint32_t>(options_.width) ||
              image->height != static_cast<uint32_t>(options_.height) || image->step != static_cast<uint32_t>(options_.width * 3) ||
              image->data.size() != static_cast<size_t>(options_.width * options_.height * 3)) {
            RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                                 "视频输入不匹配：期望 rgb8 %dx%d，收到 %s %ux%u step=%u bytes=%zu",
                                 options_.width, options_.height, image->encoding.c_str(), image->width, image->height,
                                 image->step, image->data.size());
            return;
          }
          {
            std::lock_guard<std::mutex> guard(frame_mutex_);
            latest_frame_ = std::move(image);
          }
          frame_ready_.notify_one();
        });
    worker_ = std::thread([this] { write_latest_frames(); });
  }

  ~VideoIngest() override {
    running_ = false;
    frame_ready_.notify_all();
    if (worker_.joinable()) worker_.join();
    stop_pipeline();
  }

 private:
  void start_pipeline() {
    stop_pipeline();
    int pipe_fds[2]{};
    if (pipe(pipe_fds) != 0) {
      throw std::runtime_error("无法创建 GStreamer 输入管道：" + std::string(std::strerror(errno)));
    }
    const pid_t child = fork();
    if (child < 0) {
      close(pipe_fds[0]);
      close(pipe_fds[1]);
      throw std::runtime_error("无法启动 GStreamer：" + std::string(std::strerror(errno)));
    }
    if (child == 0) {
      dup2(pipe_fds[0], STDIN_FILENO);
      close(pipe_fds[0]);
      close(pipe_fds[1]);
      const std::string blocksize = std::to_string(options_.width * options_.height * 3);
      const std::string bitrate = "bitrate=" + std::to_string(options_.bitrate_kbps);
      std::vector<std::string> arguments = {
          options_.gst_launch, "-q", "fdsrc", "fd=0", "do-timestamp=true", "blocksize=" + blocksize,
          // A Unix pipe can return partial reads even when the writer emits a
          // whole image. fdsrc produces arbitrary byte chunks, not complete
          // video buffers; rawvideoparse must reassemble RGB frames first.
          "!", "rawvideoparse", "format=rgb", "width=" + std::to_string(options_.width),
          "height=" + std::to_string(options_.height), "framerate=" + std::to_string(options_.fps) + "/1",
          "!", "queue", "max-size-buffers=1", "leaky=downstream", "!", "videoconvert",
          "!", "video/x-raw,format=NV12", "!", "vaapih264enc", bitrate, "keyframe-period=" + std::to_string(options_.fps),
          "!", "h264parse", "config-interval=-1", "!", "rtspclientsink", "location=" + options_.rtsp_url, "protocols=tcp",
      };
      std::vector<char *> argv;
      argv.reserve(arguments.size() + 1);
      for (auto &argument : arguments) argv.push_back(argument.data());
      argv.push_back(nullptr);
      execv(argv.front(), argv.data());
      std::cerr << "无法执行私有 gst-launch：" << std::strerror(errno) << std::endl;
      _exit(127);
    }
    close(pipe_fds[0]);
    pipe_write_fd_ = pipe_fds[1];
    pipeline_pid_ = child;
    RCLCPP_INFO(get_logger(), "已启动 VAAPI H.264 管线：topic=%s rtsp=%s", options_.topic.c_str(), options_.rtsp_url.c_str());
  }

  void stop_pipeline() {
    if (pipe_write_fd_ >= 0) {
      close(pipe_write_fd_);
      pipe_write_fd_ = -1;
    }
    if (pipeline_pid_ > 0) {
      kill(pipeline_pid_, SIGTERM);
      waitpid(pipeline_pid_, nullptr, 0);
      pipeline_pid_ = -1;
    }
  }

  bool write_frame(const sensor_msgs::msg::Image &image) {
    const uint8_t *cursor = image.data.data();
    size_t remaining = image.data.size();
    while (remaining > 0) {
      const ssize_t written = write(pipe_write_fd_, cursor, remaining);
      if (written > 0) {
        cursor += written;
        remaining -= static_cast<size_t>(written);
        continue;
      }
      if (written < 0 && errno == EINTR) continue;
      return false;
    }
    return true;
  }

  void write_latest_frames() {
    const auto frame_interval = std::chrono::microseconds(1'000'000 / options_.fps);
    auto next_frame_at = std::chrono::steady_clock::now();
    while (running_) {
      sensor_msgs::msg::Image::ConstSharedPtr frame;
      {
        std::unique_lock<std::mutex> lock(frame_mutex_);
        frame_ready_.wait(lock, [this] { return !running_ || latest_frame_ != nullptr; });
        if (!running_) return;
      }
      // ROS 相机源可以高于配置帧率；等待期间回调继续覆盖单槽，时间到达时
      // 只编码最新图像，绝不形成排队或把 20 FPS 误写进 15 FPS 输出。
      const auto now = std::chrono::steady_clock::now();
      if (now < next_frame_at) std::this_thread::sleep_until(next_frame_at);
      {
        std::lock_guard<std::mutex> guard(frame_mutex_);
        frame = std::move(latest_frame_);
      }
      if (!frame) continue;
      if (!write_frame(*frame)) {
        RCLCPP_ERROR(get_logger(), "GStreamer 输入管道已中断；丢弃当前帧并在下一帧前重启");
        if (running_) {
          try {
            start_pipeline();
          } catch (const std::exception &error) {
            RCLCPP_ERROR(get_logger(), "GStreamer 重启失败：%s", error.what());
          }
        }
      }
      next_frame_at = std::chrono::steady_clock::now() + frame_interval;
    }
  }

  Options options_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr subscription_;
  std::atomic<bool> running_{true};
  std::mutex frame_mutex_;
  std::condition_variable frame_ready_;
  sensor_msgs::msg::Image::ConstSharedPtr latest_frame_;
  std::thread worker_;
  int pipe_write_fd_{-1};
  pid_t pipeline_pid_{-1};
};

}  // namespace

int main(int argc, char **argv) {
  try {
    const Options options = parse_options(argc, argv);
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<VideoIngest>(options));
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "aletheia_video_ingest: " << error.what() << std::endl;
    return 2;
  }
}
