#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

#include "shmsdk_camera_abi.hpp"

#include <cstdio>
#include <jpeglib.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csetjmp>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
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

enum class InputKind { kRos, kShmSdk };

struct Options {
  std::string node_name;
  InputKind input_kind{InputKind::kRos};
  std::string topic;
  std::string shm_channel;
  std::string encoding;
  std::string gst_launch;
  std::string vaapi_device;
  std::string rtsp_url;
  int width{};
  int height{};
  int fps{};
  int bitrate_kbps{};
};

struct JpegErrorManager {
  jpeg_error_mgr base;
  jmp_buf jump;
  char message[JMSG_LENGTH_MAX]{};
};

void jpeg_error_exit(j_common_ptr info) {
  auto *error = reinterpret_cast<JpegErrorManager *>(info->err);
  (*info->err->format_message)(info, error->message);
  longjmp(error->jump, 1);
}

int parse_positive(const char *value, const char *name) {
  try {
    const int result = std::stoi(value);
    if (result > 0) return result;
  } catch (const std::exception &) {
  }
  throw std::runtime_error(std::string(name) + " 必须是正整数");
}

bool is_ros_name(const std::string &value) {
  if (value.empty() || !(std::isalpha(static_cast<unsigned char>(value.front())) || value.front() == '_')) return false;
  return std::all_of(value.begin(), value.end(), [](unsigned char character) { return std::isalnum(character) || character == '_'; });
}

bool is_shmsdk_camera_channel(const std::string &value) {
  return value == "CamFront" || value == "CamBack" || value == "CamLeft" || value == "CamRight";
}

const char *input_kind_name(InputKind value) {
  return value == InputKind::kShmSdk ? "ShmSDK" : "ROS";
}

int64_t steady_millis() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

std::string ros_domain_id() {
  const char *value = std::getenv("ROS_DOMAIN_ID");
  return value && *value ? value : "0";
}

Options parse_options(int argc, char **argv) {
  Options options;
  for (int index = 1; index < argc; index += 2) {
    if (index + 1 >= argc) throw std::runtime_error("视频输入参数缺少值");
    const std::string key(argv[index]);
    const char *value = argv[index + 1];
    if (key == "--node-name") options.node_name = value;
    else if (key == "--input-kind") {
      const std::string kind(value);
      if (kind == "ros") options.input_kind = InputKind::kRos;
      else if (kind == "shmsdk") options.input_kind = InputKind::kShmSdk;
      else throw std::runtime_error("input-kind 当前仅支持 ros 或 shmsdk");
    } else if (key == "--topic") options.topic = value;
    else if (key == "--shm-channel") options.shm_channel = value;
    else if (key == "--encoding") options.encoding = value;
    else if (key == "--gst-launch") options.gst_launch = value;
    else if (key == "--vaapi-device") options.vaapi_device = value;
    else if (key == "--rtsp-url") options.rtsp_url = value;
    else if (key == "--width") options.width = parse_positive(value, "width");
    else if (key == "--height") options.height = parse_positive(value, "height");
    else if (key == "--fps") options.fps = parse_positive(value, "fps");
    else if (key == "--bitrate-kbps") options.bitrate_kbps = parse_positive(value, "bitrate-kbps");
    else throw std::runtime_error("未知视频输入参数：" + key);
  }
  const bool has_valid_source = options.input_kind == InputKind::kRos ? !options.topic.empty() : is_shmsdk_camera_channel(options.shm_channel);
  if (!is_ros_name(options.node_name) || !has_valid_source || (options.encoding != "rgb8" && options.encoding != "bgr8") ||
      options.gst_launch.empty() || options.vaapi_device.empty() || options.rtsp_url.empty() || !options.width || !options.height ||
      !options.fps || !options.bitrate_kbps) {
    throw std::runtime_error(
        "必须提供安全的 node-name、输入源、encoding(rgb8/bgr8)、gst-launch、vaapi-device、rtsp-url、width、height、fps 和 bitrate-kbps；"
        "shmsdk 输入仅允许 CamFront/CamBack/CamLeft/CamRight");
  }
  return options;
}

bool decode_jpeg_rgb(const std::vector<uint8_t> &encoded, int expected_width, int expected_height, std::vector<uint8_t> &decoded,
                     std::string &error) {
  if (encoded.empty() || encoded.size() > std::numeric_limits<unsigned long>::max()) {
    error = "JPEG 数据为空或过大";
    return false;
  }
  jpeg_decompress_struct decompress{};
  JpegErrorManager jpeg_error{};
  decompress.err = jpeg_std_error(&jpeg_error.base);
  jpeg_error.base.error_exit = jpeg_error_exit;
  if (setjmp(jpeg_error.jump) != 0) {
    jpeg_destroy_decompress(&decompress);
    error = std::string("JPEG 解码失败：") + jpeg_error.message;
    return false;
  }
  jpeg_create_decompress(&decompress);
  jpeg_mem_src(&decompress, encoded.data(), static_cast<unsigned long>(encoded.size()));
  jpeg_read_header(&decompress, TRUE);
  decompress.out_color_space = JCS_RGB;
  jpeg_start_decompress(&decompress);
  if (decompress.output_width != static_cast<JDIMENSION>(expected_width) ||
      decompress.output_height != static_cast<JDIMENSION>(expected_height) || decompress.output_components != 3) {
    jpeg_finish_decompress(&decompress);
    jpeg_destroy_decompress(&decompress);
    error = "JPEG 分辨率或通道数不匹配";
    return false;
  }
  const size_t image_size = static_cast<size_t>(expected_width) * static_cast<size_t>(expected_height) * 3U;
  decoded.resize(image_size);
  while (decompress.output_scanline < decompress.output_height) {
    JSAMPROW row = decoded.data() + static_cast<size_t>(decompress.output_scanline) * static_cast<size_t>(expected_width) * 3U;
    jpeg_read_scanlines(&decompress, &row, 1);
  }
  jpeg_finish_decompress(&decompress);
  jpeg_destroy_decompress(&decompress);
  return true;
}

void swap_red_blue(std::vector<uint8_t> &pixels) {
  for (size_t index = 0; index + 2 < pixels.size(); index += 3) std::swap(pixels[index], pixels[index + 2]);
}

class VideoIngest final : public rclcpp::Node {
 public:
  explicit VideoIngest(Options options) : Node(options.node_name), options_(std::move(options)) {
    std::signal(SIGPIPE, SIG_IGN);
    start_pipeline();
    input_diagnostic_timer_ = create_wall_timer(std::chrono::seconds(5), [this] { diagnose_input(); });
    if (options_.input_kind == InputKind::kRos) {
      const auto qos = rclcpp::SensorDataQoS().keep_last(1);
      subscription_ = create_subscription<sensor_msgs::msg::Image>(options_.topic, qos, [this](sensor_msgs::msg::Image::ConstSharedPtr image) {
        accept_ros_image(std::move(image));
      });
      RCLCPP_INFO(get_logger(), "视频输入已订阅：topic=%s expected=%s %dx%d fps=%d bitrate_kbps=%d ROS_DOMAIN_ID=%s QoS=SensorData/keep_last(1)",
                  options_.topic.c_str(), options_.encoding.c_str(), options_.width, options_.height, options_.fps, options_.bitrate_kbps,
                  ros_domain_id().c_str());
    } else {
      RCLCPP_INFO(get_logger(), "视频输入已连接到 ShmSDK：channel=%s expected=%s %dx%d fps=%d；仅读取 GetLastCamImage 最新帧，不管理 mempool",
                  options_.shm_channel.c_str(), options_.encoding.c_str(), options_.width, options_.height, options_.fps);
      shm_reader_ = std::thread([this] { read_shmsdk_frames(); });
    }
    worker_ = std::thread([this] { write_latest_frames(); });
  }

  ~VideoIngest() override {
    running_ = false;
    frame_ready_.notify_all();
    if (shm_reader_.joinable()) shm_reader_.join();
    if (worker_.joinable()) worker_.join();
    stop_pipeline();
  }

 private:
  std::string source_label() const {
    return options_.input_kind == InputKind::kShmSdk ? "ShmSDK/" + options_.shm_channel : "ROS:" + options_.topic;
  }

  void set_rejection(std::string detail) {
    std::lock_guard<std::mutex> guard(diagnostic_mutex_);
    last_rejection_ = std::move(detail);
  }

  std::string last_rejection() const {
    std::lock_guard<std::mutex> guard(diagnostic_mutex_);
    return last_rejection_;
  }

  void accept_ros_image(sensor_msgs::msg::Image::ConstSharedPtr image) {
    const int64_t received_at_ms = steady_millis();
    const uint64_t message_count = received_messages_.fetch_add(1) + 1;
    last_message_at_ms_.store(received_at_ms);
    const bool was_stalled = input_stalled_.exchange(false);
    if (message_count == 1 || was_stalled) {
      RCLCPP_INFO(get_logger(), "%s ROS 图像：topic=%s publishers=%zu encoding=%s size=%ux%u step=%u bytes=%zu",
                  message_count == 1 ? "已收到首个" : "已恢复接收", options_.topic.c_str(),
                  subscription_ ? subscription_->get_publisher_count() : 0U, image->encoding.c_str(), image->width, image->height,
                  image->step, image->data.size());
    }
    if (image->encoding != options_.encoding || image->width != static_cast<uint32_t>(options_.width) ||
        image->height != static_cast<uint32_t>(options_.height) || image->step != static_cast<uint32_t>(options_.width * 3) ||
        image->data.size() != static_cast<size_t>(options_.width) * static_cast<size_t>(options_.height) * 3U) {
      set_rejection("ROS 图像的编码、分辨率、step 或长度不匹配");
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "视频输入不匹配：期望 %s %dx%d，收到 %s %ux%u step=%u bytes=%zu", options_.encoding.c_str(), options_.width,
                           options_.height, image->encoding.c_str(), image->width, image->height, image->step, image->data.size());
      return;
    }
    publish_latest(std::move(image));
  }

  bool make_shmsdk_image(const aletheia::shmsdk::CamImage &input, sensor_msgs::msg::Image &output, std::string &error) const {
    if (input.width != static_cast<uint32_t>(options_.width) || input.height != static_cast<uint32_t>(options_.height)) {
      error = "ShmSDK 图像分辨率不匹配";
      return false;
    }
    std::vector<uint8_t> pixels;
    std::string source_encoding = input.encoding;
    std::transform(source_encoding.begin(), source_encoding.end(), source_encoding.begin(), [](unsigned char value) { return std::tolower(value); });
    const size_t expected_size = static_cast<size_t>(options_.width) * static_cast<size_t>(options_.height) * 3U;
    if (source_encoding == "jpeg" || source_encoding == "jpg") {
      if (!decode_jpeg_rgb(input.data, options_.width, options_.height, pixels, error)) return false;
      source_encoding = "rgb8";
    } else if (source_encoding == "rgb8" || source_encoding == "bgr8") {
      const uint32_t expected_step = static_cast<uint32_t>(options_.width * 3);
      if (input.step != expected_step || input.data.size() != expected_size) {
        error = "ShmSDK 原始图像的 step 或长度不匹配";
        return false;
      }
      pixels = input.data;
    } else {
      error = "ShmSDK 相机编码不支持：" + input.encoding;
      return false;
    }
    if (pixels.size() != expected_size) {
      error = "ShmSDK 解码后图像长度不匹配";
      return false;
    }
    if (source_encoding != options_.encoding) swap_red_blue(pixels);
    output.encoding = options_.encoding;
    output.width = static_cast<uint32_t>(options_.width);
    output.height = static_cast<uint32_t>(options_.height);
    output.step = static_cast<uint32_t>(options_.width * 3);
    output.is_bigendian = input.is_bigendian;
    output.data = std::move(pixels);
    return true;
  }

  void read_shmsdk_frames() {
    while (running_) {
      try {
        aletheia::shmsdk::CameraApi api;
        if (!api.initialize()) throw std::runtime_error("ShmSDK InitMem 返回失败；请确认小车 mempool 已运行");
        aletheia::shmsdk::Handle handle = -1;
        int64_t next_open_attempt_ms = 0;
        int64_t last_source_frame_ms = steady_millis();
        while (running_) {
        if (handle < 0) {
          const int64_t now = steady_millis();
          if (now < next_open_attempt_ms) {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            continue;
          }
          handle = api.open(options_.shm_channel);
          next_open_attempt_ms = now + 2000;
          if (handle < 0) {
            set_rejection("无法打开 ShmSDK 通道；请确认 mempool 和相机生产端正在运行");
            continue;
          }
          RCLCPP_INFO(get_logger(), "ShmSDK 相机通道已打开：channel=%s", options_.shm_channel.c_str());
          last_source_frame_ms = now;
        }
        aletheia::shmsdk::CamImage input;
        if (!api.get_last(handle, input)) {
          // A camera producer or mempool can restart without this sidecar
          // exiting. Reopen after a bounded quiet interval so a recovered
          // source is picked up without leaving a stale handle forever.
          if (steady_millis() - last_source_frame_ms > 5000) {
            RCLCPP_WARN(get_logger(), "ShmSDK 相机通道 5 秒无新帧，关闭并重新打开：channel=%s", options_.shm_channel.c_str());
            api.close(options_.shm_channel);
            handle = -1;
            next_open_attempt_ms = steady_millis() + 200;
            continue;
          }
          std::this_thread::sleep_for(std::chrono::milliseconds(2));
          continue;
        }
        const int64_t received_at_ms = steady_millis();
        last_source_frame_ms = received_at_ms;
        const uint64_t message_count = received_messages_.fetch_add(1) + 1;
        last_message_at_ms_.store(received_at_ms);
        const bool was_stalled = input_stalled_.exchange(false);
        if (message_count == 1 || was_stalled) {
          RCLCPP_INFO(get_logger(), "%s ShmSDK 图像：channel=%s encoding=%s size=%ux%u step=%u bytes=%zu",
                      message_count == 1 ? "已收到首个" : "已恢复接收", options_.shm_channel.c_str(), input.encoding.c_str(), input.width,
                      input.height, input.step, input.data.size());
        }
        auto image = std::make_shared<sensor_msgs::msg::Image>();
        std::string error;
        if (!make_shmsdk_image(input, *image, error)) {
          set_rejection(std::move(error));
          continue;
        }
        publish_latest(std::move(image));
        }
        if (handle >= 0) api.close(options_.shm_channel);
        return;
      } catch (const std::exception &error) {
        set_rejection(error.what());
        RCLCPP_ERROR(get_logger(), "ShmSDK 视频输入不可用：channel=%s；%s；2 秒后重试", options_.shm_channel.c_str(), error.what());
        std::this_thread::sleep_for(std::chrono::seconds(2));
      }
    }
  }

  void publish_latest(sensor_msgs::msg::Image::ConstSharedPtr image) {
    if (accepted_frames_.fetch_add(1) == 0) {
      RCLCPP_INFO(get_logger(), "视频输入已就绪：source=%s %s %dx%d，开始以 %d FPS 编码", source_label().c_str(),
                  options_.encoding.c_str(), options_.width, options_.height, options_.fps);
    }
    {
      std::lock_guard<std::mutex> guard(frame_mutex_);
      // One slot is intentional: a slower encoder always drops old images and
      // receives the newest source frame next; neither source has a queue.
      latest_frame_ = std::move(image);
    }
    frame_ready_.notify_one();
  }

  void start_pipeline() {
    stop_pipeline();
    int pipe_fds[2]{};
    if (pipe(pipe_fds) != 0) throw std::runtime_error("无法创建 GStreamer 输入管道：" + std::string(std::strerror(errno)));
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
      const std::string raw_format = options_.encoding == "bgr8" ? "bgr" : "rgb";
      std::vector<std::string> arguments = {
          options_.gst_launch, "-q", "fdsrc", "fd=0", "do-timestamp=true", "blocksize=" + blocksize,
          // fdsrc can split one pipe write. rawvideoparse reassembles fixed
          // RGB/BGR frames before the bounded, leaky encoder queue.
          "!", "rawvideoparse", "format=" + raw_format, "width=" + std::to_string(options_.width),
          "height=" + std::to_string(options_.height), "framerate=" + std::to_string(options_.fps) + "/1",
          "!", "queue", "max-size-buffers=1", "leaky=downstream", "!", "videoconvert", "!", "video/x-raw,format=NV12",
          "!", "vaapih264enc", bitrate, "keyframe-period=" + std::to_string(options_.fps), "!", "h264parse", "config-interval=-1",
          "!", "rtspclientsink", "location=" + options_.rtsp_url, "protocols=tcp",
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
    RCLCPP_INFO(get_logger(), "已启动 VAAPI H.264 管线：source=%s rtsp=%s vaapi_device=%s", source_label().c_str(),
                options_.rtsp_url.c_str(), options_.vaapi_device.c_str());
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

  void diagnose_input() {
    const int64_t now_ms = steady_millis();
    const uint64_t received = received_messages_.load();
    const uint64_t accepted = accepted_frames_.load();
    const int64_t last_message_ms = last_message_at_ms_.load();
    const size_t publishers = subscription_ ? subscription_->get_publisher_count() : 0U;
    const std::string source = source_label();
    if (received == 0) {
      input_stalled_.store(true);
      if (options_.input_kind == InputKind::kRos) {
        const char *reason = publishers == 0 ? "未发现 ROS 发布者；请检查检测/分割节点、ROS_DOMAIN_ID 与 source_topic"
                                              : "已发现 ROS 发布者但未收到消息；请检查 DDS 连通性和 QoS";
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
                             "视频输入等待首帧：source=%s wait_ms=%lld publishers=%zu ROS_DOMAIN_ID=%s；%s", source.c_str(),
                             static_cast<long long>(now_ms - started_at_ms_), publishers, ros_domain_id().c_str(), reason);
      } else {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
                             "视频输入等待首帧：source=%s wait_ms=%lld；请检查小车 ShmSDK mempool 与相机生产端。最近错误：%s", source.c_str(),
                             static_cast<long long>(now_ms - started_at_ms_), last_rejection().c_str());
      }
      return;
    }
    if (accepted == 0) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
                           "视频输入已收到 %llu 个%s图像但没有兼容帧：source=%s expected=%s %dx%d；最近错误：%s",
                           static_cast<unsigned long long>(received), input_kind_name(options_.input_kind), source.c_str(), options_.encoding.c_str(),
                           options_.width, options_.height, last_rejection().c_str());
      return;
    }
    if (now_ms - last_message_ms > 5000) {
      input_stalled_.store(true);
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
                           "视频输入已中断：source=%s last_frame_age_ms=%lld；请检查上游生产端。", source.c_str(),
                           static_cast<long long>(now_ms - last_message_ms));
    }
  }

  bool write_frame(const sensor_msgs::msg::Image &image, int &failure_errno) {
    failure_errno = 0;
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
      failure_errno = written < 0 ? errno : EPIPE;
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
      const auto now = std::chrono::steady_clock::now();
      if (now < next_frame_at) std::this_thread::sleep_until(next_frame_at);
      {
        std::lock_guard<std::mutex> guard(frame_mutex_);
        frame = std::move(latest_frame_);
      }
      if (!frame) continue;
      int failure_errno = 0;
      if (!write_frame(*frame, failure_errno)) {
        RCLCPP_ERROR(get_logger(), "GStreamer 输入管道已中断：errno=%d (%s)；丢弃当前帧并在下一帧前重启", failure_errno,
                     std::strerror(failure_errno));
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
  rclcpp::TimerBase::SharedPtr input_diagnostic_timer_;
  std::atomic<bool> running_{true};
  std::atomic<bool> input_stalled_{false};
  std::atomic<uint64_t> received_messages_{0};
  std::atomic<uint64_t> accepted_frames_{0};
  std::atomic<int64_t> last_message_at_ms_{0};
  const int64_t started_at_ms_{steady_millis()};
  mutable std::mutex diagnostic_mutex_;
  std::string last_rejection_;
  std::mutex frame_mutex_;
  std::condition_variable frame_ready_;
  sensor_msgs::msg::Image::ConstSharedPtr latest_frame_;
  std::thread shm_reader_;
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
