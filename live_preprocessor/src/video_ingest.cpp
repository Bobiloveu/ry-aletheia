#include <fcntl.h>
#include <spawn.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "shmsdk_camera_abi.hpp"
#include "video_frames.hpp"
#include "video_io.hpp"
#include "video_pipeline.hpp"

extern char **environ;

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
  std::string encoder{"vaapih264enc"};
  std::string nvenc_rate_control{"cbr"};
  std::string rtsp_url;
  int width{};
  int height{};
  int fps{};
  int bitrate_kbps{};
};

// This pointer keeps ROS or SDK bytes alive through preparation and pipe write.
struct QueuedFrame {
  aletheia::video::FrameView view;
  std::shared_ptr<const void> owner;
};

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

const char *input_kind_name(InputKind value) { return value == InputKind::kShmSdk ? "ShmSDK" : "ROS"; }

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
    if (key == "--node-name")
      options.node_name = value;
    else if (key == "--input-kind") {
      const std::string kind(value);
      if (kind == "ros")
        options.input_kind = InputKind::kRos;
      else if (kind == "shmsdk")
        options.input_kind = InputKind::kShmSdk;
      else
        throw std::runtime_error("input-kind 当前仅支持 ros 或 shmsdk");
    } else if (key == "--topic")
      options.topic = value;
    else if (key == "--shm-channel")
      options.shm_channel = value;
    else if (key == "--encoding")
      options.encoding = value;
    else if (key == "--gst-launch")
      options.gst_launch = value;
    else if (key == "--vaapi-device")
      options.vaapi_device = value;
    else if (key == "--encoder")
      options.encoder = value;
    else if (key == "--nvenc-rate-control")
      options.nvenc_rate_control = value;
    else if (key == "--rtsp-url")
      options.rtsp_url = value;
    else if (key == "--width")
      options.width = parse_positive(value, "width");
    else if (key == "--height")
      options.height = parse_positive(value, "height");
    else if (key == "--fps")
      options.fps = parse_positive(value, "fps");
    else if (key == "--bitrate-kbps")
      options.bitrate_kbps = parse_positive(value, "bitrate-kbps");
    else
      throw std::runtime_error("未知视频输入参数：" + key);
  }
  const bool has_valid_source =
      options.input_kind == InputKind::kRos ? !options.topic.empty() : is_shmsdk_camera_channel(options.shm_channel);
  if (!is_ros_name(options.node_name) || !has_valid_source || (options.encoding != "rgb8" && options.encoding != "bgr8") ||
      options.gst_launch.empty() || options.vaapi_device.empty() || options.rtsp_url.empty() || !options.bitrate_kbps ||
      !aletheia::video::valid_target_budget(options.width, options.height, options.fps) ||
      (options.encoder != "vaapih264enc" && options.encoder != "nvh264enc") ||
      (options.nvenc_rate_control != "cbr" && options.nvenc_rate_control != "vbr")) {
    throw std::runtime_error(
        "必须提供安全的 node-name、输入源、encoding(rgb8/bgr8)、gst-launch、vaapi-device、rtsp-url、width、height、fps 和 bitrate-kbps；"
        "shmsdk 输入仅允许 CamFront/CamBack/CamLeft/CamRight");
  }
  return options;
}

class VideoIngest final : public rclcpp::Node {
 public:
  explicit VideoIngest(Options options) : Node(options.node_name), options_(std::move(options)) {
    std::signal(SIGPIPE, SIG_IGN);
    input_diagnostic_timer_ = create_wall_timer(std::chrono::seconds(5), [this] { diagnose_input(); });
    if (options_.input_kind == InputKind::kRos) {
      const auto qos = rclcpp::SensorDataQoS().keep_last(1);
      subscription_ = create_subscription<sensor_msgs::msg::Image>(
          options_.topic, qos, [this](sensor_msgs::msg::Image::ConstSharedPtr image) { accept_ros_image(std::move(image)); });
      RCLCPP_INFO(get_logger(),
                  "视频输入已订阅：topic=%s target=%s %dx%d fps=%d bitrate_kbps=%d ROS_DOMAIN_ID=%s QoS=SensorData/keep_last(1)",
                  options_.topic.c_str(), options_.encoding.c_str(), options_.width, options_.height, options_.fps, options_.bitrate_kbps,
                  ros_domain_id().c_str());
    } else {
      RCLCPP_INFO(get_logger(), "视频输入已连接到 ShmSDK：channel=%s target=%s %dx%d fps=%d；读取 GetCamImage(GET_LAST) 最新实时帧",
                  options_.shm_channel.c_str(), options_.encoding.c_str(), options_.width, options_.height, options_.fps);
      shm_reader_ = std::thread([this] { read_shmsdk_frames(); });
    }
    worker_ = std::thread([this] { write_latest_frames(); });
  }

  ~VideoIngest() override {
    {
      std::lock_guard<std::mutex> guard(frame_mutex_);
      running_ = false;
    }
    frame_ready_.notify_all();
    if (worker_.joinable()) worker_.join();
    stop_pipeline();
    // The vendor OpenMem can wait ~10s. Reap our media child before waiting
    // for that SDK call, so controlled shutdown cannot orphan the encoder.
    if (shm_reader_.joinable()) shm_reader_.join();
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
    auto frame = std::make_shared<QueuedFrame>();
    frame->view = {image->width, image->height, image->step, image->encoding, image->data.data(), image->data.size()};
    frame->owner = std::move(image);
    publish_latest(std::move(frame));
  }

  void read_shmsdk_frames() {
    while (running_) {
      try {
        aletheia::shmsdk::CameraApi api;
        if (!api.initialize()) throw std::runtime_error("ShmSDK InitMem 返回失败；请确认小车 mempool 已运行");
        aletheia::shmsdk::Handle handle = -1;
        int64_t next_open_attempt_ms = 0;
        int64_t last_source_frame_ms = steady_millis();
        auto input = std::make_shared<aletheia::shmsdk::CamImage>();
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
          if (!api.get_last(handle, *input)) {
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
                        message_count == 1 ? "已收到首个" : "已恢复接收", options_.shm_channel.c_str(), input->encoding.c_str(),
                        input->width, input->height, input->step, input->data.size());
          }
          auto frame = std::make_shared<QueuedFrame>();
          frame->view = {input->width, input->height, input->step, input->encoding, input->data.data(), input->data.size()};
          frame->owner = std::move(input);
          publish_latest(std::move(frame));
          input = std::make_shared<aletheia::shmsdk::CamImage>();
        }
        if (handle >= 0) api.close(options_.shm_channel);
        return;
      } catch (const std::exception &error) {
        set_rejection(error.what());
        RCLCPP_ERROR(get_logger(), "ShmSDK 视频输入不可用：channel=%s；%s；2 秒后重试", options_.shm_channel.c_str(), error.what());
        std::unique_lock<std::mutex> lock(frame_mutex_);
        frame_ready_.wait_for(lock, std::chrono::seconds(2), [this] { return !running_; });
      }
    }
  }

  void publish_latest(std::shared_ptr<QueuedFrame> frame) {
    {
      // Pair condition notification with this mutex to prevent a lost wakeup.
      std::lock_guard<std::mutex> guard(frame_mutex_);
      latest_frame_.publish(std::move(frame));
    }
    frame_ready_.notify_one();
  }

  void start_pipeline(const aletheia::video::FrameLayout &layout) {
    RCLCPP_INFO(get_logger(), "启动硬件编码：encoder=%s rate_control=%s target=%dx%d fps=%d bitrate_kbps=%d const_quality=%s",
                options_.encoder.c_str(), options_.encoder == "nvh264enc" ? options_.nvenc_rate_control.c_str() : "cqp",
                options_.width, options_.height, options_.fps, options_.bitrate_kbps,
                options_.encoder == "nvh264enc" && options_.nvenc_rate_control == "vbr" ? "23" : "preset");
    stop_pipeline();
    auto arguments = aletheia::video::pipeline_arguments(
        {options_.gst_launch, options_.encoder, options_.rtsp_url, options_.width, options_.height, options_.fps,
         options_.bitrate_kbps, options_.nvenc_rate_control},
        layout);
    std::vector<char *> argv;
    argv.reserve(arguments.size() + 1);
    for (auto &argument : arguments) argv.push_back(argument.data());
    argv.push_back(nullptr);
    int pipe_fds[2]{};
    if (pipe2(pipe_fds, O_CLOEXEC) != 0) throw std::runtime_error("无法创建 GStreamer 输入管道：" + std::string(std::strerror(errno)));
    if (fcntl(pipe_fds[1], F_SETFL, O_NONBLOCK) != 0) {
      const int failure = errno;
      close(pipe_fds[0]);
      close(pipe_fds[1]);
      throw std::runtime_error("无法设置视频管道期限：" + std::string(std::strerror(failure)));
    }
    posix_spawn_file_actions_t actions;
    int failure = posix_spawn_file_actions_init(&actions);
    if (failure != 0) {
      close(pipe_fds[0]);
      close(pipe_fds[1]);
      throw std::runtime_error("无法初始化视频子进程：" + std::string(std::strerror(failure)));
    }
    failure = posix_spawn_file_actions_adddup2(&actions, pipe_fds[0], STDIN_FILENO);
    if (failure == 0 && pipe_fds[0] != STDIN_FILENO) failure = posix_spawn_file_actions_addclose(&actions, pipe_fds[0]);
    if (failure == 0) failure = posix_spawn_file_actions_addclose(&actions, pipe_fds[1]);
    pid_t child = -1;
    if (failure == 0) failure = posix_spawn(&child, argv.front(), &actions, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    close(pipe_fds[0]);
    if (failure != 0) {
      close(pipe_fds[1]);
      throw std::runtime_error("无法启动私有 GStreamer：" + std::string(std::strerror(failure)));
    }
    pipe_write_fd_ = pipe_fds[1];
    pipeline_pid_ = child;
    pipeline_layout_ = layout;
    pipeline_timing_.started(steady_millis());
    RCLCPP_INFO(get_logger(), "已创建编码子进程，等待初始化与媒体发布：encoder=%s source=%s input=%s %ux%u stride=%u target=%dx%d rtsp=%s vaapi_device=%s startup_window_ms=10000 pid=%ld",
                options_.encoder.c_str(), source_label().c_str(), layout.format.c_str(), layout.width, layout.height, layout.stride,
                options_.width, options_.height, options_.rtsp_url.c_str(), options_.vaapi_device.c_str(),static_cast<long>(child));
  }

  void stop_pipeline() {
    if (pipe_write_fd_ >= 0) {
      close(pipe_write_fd_);
      pipe_write_fd_ = -1;
    }
    if (pipeline_pid_ > 0) {
      if (!aletheia::video::stop_child(pipeline_pid_)) {
        RCLCPP_ERROR(get_logger(), "GStreamer 在 TERM/KILL 期限后仍未退出：pid=%d", pipeline_pid_);
      }
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
                             "视频输入等待首帧：source=%s wait_ms=%lld；请检查小车 ShmSDK mempool 与相机生产端。最近错误：%s",
                             source.c_str(), static_cast<long long>(now_ms - started_at_ms_), last_rejection().c_str());
      }
      return;
    }
    if (accepted > 0 && now_ms - last_message_ms > 5000) {
      input_stalled_.store(true);
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000, "视频输入已中断：source=%s last_frame_age_ms=%lld；请检查上游生产端。",
                           source.c_str(), static_cast<long long>(now_ms - last_message_ms));
      return;
    }
    if (accepted == 0 || now_ms - last_accepted_at_ms_.load() > 5000) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
                           "视频尚未形成持续输出：已收到 %llu 个%s图像；source=%s target=%s %dx%d；最近错误：%s",
                           static_cast<unsigned long long>(received), input_kind_name(options_.input_kind), source.c_str(),
                           options_.encoding.c_str(), options_.width, options_.height, last_rejection().c_str());
      return;
    }
  }

  void write_latest_frames() {
    aletheia::video::FrameBudget budget(options_.fps);
    aletheia::video::PreparedFrame prepared;
    int64_t next_pipeline_attempt_ms = 0;
    while (running_) {
      std::shared_ptr<QueuedFrame> frame;
      {
        std::unique_lock<std::mutex> lock(frame_mutex_);
        frame_ready_.wait(lock, [this] { return !running_ || latest_frame_.has_frame(); });
        if (!running_) return;
        const auto deadline = std::chrono::steady_clock::time_point(std::chrono::microseconds(budget.next_us()));
        frame_ready_.wait_until(lock, deadline, [this] { return !running_; });
        if (!running_) return;
        frame = latest_frame_.take();
      }
      if (!frame) continue;
      const auto now = std::chrono::steady_clock::now();
      const auto now_us = std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch()).count();
      budget.consume(now_us);
      // The latest slot and output FPS budget are applied before JPEG decode.
      // Frames that get replaced never allocate a decoded RGB buffer.
      if (pipe_write_fd_ < 0 && steady_millis() < next_pipeline_attempt_ms) continue;
      try {
        std::string error;
        if (!aletheia::video::prepare_frame(frame->view, prepared, error)) {
          set_rejection(std::move(error));
          continue;
        }
        const bool pipeline_starting = pipe_write_fd_ < 0 || pipeline_layout_ != prepared.layout;
        if (pipeline_starting) start_pipeline(prepared.layout);
        int failure_errno = 0;
        // fdsrc may read a first frame before CUDA/RTSP initialization ends.
        // Keep one total startup window, not a fresh allowance for every frame.
        const int write_timeout_ms = pipeline_timing_.write_timeout_ms(steady_millis());
        if (!aletheia::video::write_pipe(pipe_write_fd_, prepared.data(), prepared.size(), running_, failure_errno,
                                         write_timeout_ms)) {
          if (!running_) return;
          set_rejection("GStreamer 输入管道超时或中断：" + std::string(std::strerror(failure_errno)));
          const int retry_ms = pipeline_timing_.failed(steady_millis());
          RCLCPP_ERROR(get_logger(), "GStreamer 本地写管道失败：encoder=%s pid=%ld errno=%d (%s) write_timeout_ms=%d retry_ms=%d；丢弃当前帧，请结合 GStreamer 错误检查初始化或下游背压",
                       options_.encoder.c_str(),static_cast<long>(pipeline_pid_),failure_errno,
                       std::strerror(failure_errno),write_timeout_ms,retry_ms);
          // Even a partial frame is discarded with its parser, never combined
          // with bytes from the next image.
          stop_pipeline();
          next_pipeline_attempt_ms = steady_millis() + retry_ms;
          continue;
        }
        last_accepted_at_ms_.store(steady_millis());
        pipeline_timing_.written(steady_millis());
        set_rejection({});
        if (accepted_frames_.fetch_add(1) == 0) {
          RCLCPP_INFO(get_logger(), "首帧已完整提交编码子进程，实际发布状态由 MediaMTX 确认：source=%s input=%s %ux%u target=%dx%d FPS=%d encoder=%s", source_label().c_str(),
                      prepared.layout.format.c_str(), prepared.layout.width, prepared.layout.height, options_.width, options_.height,
                      options_.fps, options_.encoder.c_str());
        }
      } catch (const std::exception &error) {
        set_rejection(error.what());
        const int retry_ms = pipeline_timing_.failed(steady_millis());
        RCLCPP_ERROR(get_logger(), "视频帧处理失败：%s；%d 毫秒后重试该路管线", error.what(),retry_ms);
        stop_pipeline();
        next_pipeline_attempt_ms = steady_millis() + retry_ms;
      }
    }
  }

  Options options_;
  aletheia::video::PipelineTiming pipeline_timing_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr subscription_;
  rclcpp::TimerBase::SharedPtr input_diagnostic_timer_;
  std::atomic<bool> running_{true};
  std::atomic<bool> input_stalled_{false};
  std::atomic<uint64_t> received_messages_{0};
  std::atomic<uint64_t> accepted_frames_{0};
  std::atomic<int64_t> last_message_at_ms_{0};
  std::atomic<int64_t> last_accepted_at_ms_{0};
  const int64_t started_at_ms_{steady_millis()};
  mutable std::mutex diagnostic_mutex_;
  std::string last_rejection_;
  std::mutex frame_mutex_;
  std::condition_variable frame_ready_;
  aletheia::video::LatestFrameSlot<std::shared_ptr<QueuedFrame>> latest_frame_;
  aletheia::video::FrameLayout pipeline_layout_;
  std::thread shm_reader_;
  std::thread worker_;
  int pipe_write_fd_{-1};
  pid_t pipeline_pid_{-1};
};

}  // namespace

int main(int argc, char **argv) {
  const pid_t runtime_parent = getppid();
  try {
    const Options options = parse_options(argc, argv);
    if (!aletheia::video::bind_parent_lifetime(runtime_parent))
      throw std::runtime_error("无法绑定视频运行时父进程生命周期：" + std::string(std::strerror(errno)));
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<VideoIngest>(options));
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "aletheia_video_ingest: " << error.what() << std::endl;
    return 2;
  }
}
