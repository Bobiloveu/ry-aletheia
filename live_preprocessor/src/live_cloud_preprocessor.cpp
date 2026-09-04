#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <mutex>
#include <optional>
#include <random>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <unistd.h>
#include <vector>

#include <builtin_interfaces/msg/time.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <livox_ros_driver2/msg/custom_msg.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/msg/point_field.hpp>
#include <tf2/exceptions.h>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

namespace aletheia_live_preprocessor {

namespace {

constexpr uint8_t kTelemetryVersion = 1;
constexpr uint8_t kCloudFrame = 1;
constexpr uint8_t kPoseFrame = 2;
constexpr uint8_t kCostmapFrame = 3;
// Ethernet/Wi-Fi MTU 之下保留充足余量：UDP header 30 B + payload 1152 B。
constexpr size_t kUdpPayloadBytes = 1152;
constexpr size_t kUdpMaxChunks = 64;

uint64_t host_to_network_u64(uint64_t value) {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
  return (static_cast<uint64_t>(htonl(static_cast<uint32_t>(value & 0xffffffffULL))) << 32) |
         htonl(static_cast<uint32_t>(value >> 32));
#else
  return value;
#endif
}

void append_u16(std::vector<uint8_t>& target, uint16_t value) {
  const auto network = htons(value);
  const auto* bytes = reinterpret_cast<const uint8_t*>(&network);
  target.insert(target.end(), bytes, bytes + sizeof(network));
}

void append_u32(std::vector<uint8_t>& target, uint32_t value) {
  const auto network = htonl(value);
  const auto* bytes = reinterpret_cast<const uint8_t*>(&network);
  target.insert(target.end(), bytes, bytes + sizeof(network));
}

void append_u64(std::vector<uint8_t>& target, uint64_t value) {
  const auto network = host_to_network_u64(value);
  const auto* bytes = reinterpret_cast<const uint8_t*>(&network);
  target.insert(target.end(), bytes, bytes + sizeof(network));
}

void append_network_float(std::vector<uint8_t>& target, float value) {
  uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  append_u32(target, bits);
}

class UdpLatestSender final {
 public:
  struct Frame {
    uint64_t timestamp_ns;
    uint16_t record_count;
    std::vector<uint8_t> payload;
  };

  UdpLatestSender(uint8_t kind, const std::string& host, int port, rclcpp::Logger logger)
      : kind_(kind), logger_(logger) {
    socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_ < 0) {
      RCLCPP_ERROR(logger_, "Realtime telemetry UDP socket creation failed: %s", std::strerror(errno));
      return;
    }
    const int flags = ::fcntl(socket_, F_GETFL, 0);
    if (flags >= 0) ::fcntl(socket_, F_SETFL, flags | O_NONBLOCK);
    destination_.sin_family = AF_INET;
    destination_.sin_port = htons(static_cast<uint16_t>(std::clamp(port, 1, 65535)));
    if (::inet_pton(AF_INET, host.c_str(), &destination_.sin_addr) != 1) {
      RCLCPP_ERROR(logger_, "Realtime telemetry UDP address is invalid: %s", host.c_str());
      ::close(socket_);
      socket_ = -1;
      return;
    }
    std::random_device device;
    stream_id_ = static_cast<uint32_t>((static_cast<uint64_t>(device()) << 32) ^ device());
    if (stream_id_ == 0) stream_id_ = 1;
    worker_ = std::thread([this] { run(); });
  }

  UdpLatestSender(const UdpLatestSender&) = delete;
  UdpLatestSender& operator=(const UdpLatestSender&) = delete;

  ~UdpLatestSender() {
    {
      std::lock_guard<std::mutex> guard(mutex_);
      stopping_ = true;
      latest_.reset();
    }
    condition_.notify_one();
    if (worker_.joinable()) worker_.join();
    if (socket_ >= 0) ::close(socket_);
  }

  bool available() const { return socket_ >= 0; }

  // 只替换一个待发送 frame。这个方法不会触碰 socket，因此安全地处于 ROS callback 中。
  void publish(Frame frame) {
    if (socket_ < 0) return;
    {
      std::lock_guard<std::mutex> guard(mutex_);
      QueuedFrame queued;
      queued.timestamp_ns = frame.timestamp_ns;
      queued.record_count = frame.record_count;
      queued.payload = std::move(frame.payload);
      queued.sequence = ++sequence_;
      latest_ = std::move(queued);
    }
    condition_.notify_one();
  }

 private:
  struct QueuedFrame : Frame {
    uint32_t sequence{0};
  };

  void run() {
    std::unique_lock<std::mutex> lock(mutex_);
    while (true) {
      condition_.wait(lock, [this] { return stopping_ || latest_.has_value(); });
      if (stopping_) return;
      QueuedFrame frame = std::move(*latest_);
      latest_.reset();
      lock.unlock();
      send_frame(frame);
      lock.lock();
    }
  }

  bool superseded(uint32_t sequence) {
    std::lock_guard<std::mutex> guard(mutex_);
    return latest_.has_value() && latest_->sequence != sequence;
  }

  void send_frame(const QueuedFrame& frame) {
    if (frame.payload.empty() && frame.record_count != 0) return;
    const size_t chunks = std::max<size_t>(1, (frame.payload.size() + kUdpPayloadBytes - 1) / kUdpPayloadBytes);
    // 接收端只允许固定上限的分片数；当前 3000 个二维点最多 21 片。这里显式
    // 保持两端契约，避免未来有人扩大 payload 后让网关静默拒绝整帧。
    if (chunks > kUdpMaxChunks) return;
    std::vector<uint8_t> datagram;
    datagram.reserve(30 + kUdpPayloadBytes);
    for (size_t index = 0; index < chunks; ++index) {
      // 发送中若已有新扫描，立即中断旧帧，接收端自然只会看到新 frame。
      if (superseded(frame.sequence)) return;
      const size_t offset = index * kUdpPayloadBytes;
      const size_t bytes = std::min(kUdpPayloadBytes, frame.payload.size() - offset);
      // 每帧分片复用同一个缓冲，避免 10 Hz 点云路径每片 malloc/free。
      datagram.clear();
      datagram.insert(datagram.end(), {'R', 'A', 'L', 'T'});
      datagram.push_back(kTelemetryVersion);
      datagram.push_back(kind_);
      append_u32(datagram, stream_id_);
      append_u32(datagram, frame.sequence);
      append_u64(datagram, frame.timestamp_ns);
      append_u16(datagram, static_cast<uint16_t>(index));
      append_u16(datagram, static_cast<uint16_t>(chunks));
      append_u16(datagram, frame.record_count);
      append_u16(datagram, static_cast<uint16_t>(bytes));
      datagram.insert(datagram.end(), frame.payload.begin() + static_cast<std::ptrdiff_t>(offset),
                      frame.payload.begin() + static_cast<std::ptrdiff_t>(offset + bytes));
      const auto sent = ::sendto(socket_, datagram.data(), datagram.size(), MSG_DONTWAIT,
                                 reinterpret_cast<const sockaddr*>(&destination_), sizeof(destination_));
      if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        RCLCPP_WARN(logger_, "Realtime telemetry UDP send failed: %s", std::strerror(errno));
        return;
      }
      // EAGAIN 也不等待，不重试：下一 frame 会覆盖旧 frame，符合 latest-wins。
      if (sent < 0) return;
    }
  }

  uint8_t kind_;
  rclcpp::Logger logger_;
  int socket_{-1};
  sockaddr_in destination_{};
  uint32_t stream_id_{0};
  uint32_t sequence_{0};
  std::mutex mutex_;
  std::condition_variable condition_;
  std::optional<QueuedFrame> latest_;
  bool stopping_{false};
  std::thread worker_;
};

}  // namespace

class LiveCloudPreprocessor final : public rclcpp::Node {
 public:
  LiveCloudPreprocessor()
      // 不能与控制台主进程共用完全相同的 ROS 节点名，否则 ROS2 会把两个
      // 独立进程视为同名节点并造成参数/服务发现不确定。名称仍明确归属工具。
      : Node("ry_aletheia_live"),
        // 默认复用导航正在消费的标准障碍物点云；可通过 input_topic 参数替换。
        input_topic_(declare_parameter<std::string>("input_topic", "/collision_voxel_layer/points")),
        livox_input_topic_(declare_parameter<std::string>("livox_input_topic", "/livox/lidar")),
        cloud_enabled_(declare_parameter<bool>("enable_cloud", true)),
        pose_enabled_(declare_parameter<bool>("enable_pose", true)),
        costmap_enabled_(declare_parameter<bool>("enable_costmap", false)),
        costmap_input_topic_(declare_parameter<std::string>("costmap_input_topic", "/local_costmap/costmap")),
        // collision_voxel_layer 已经是导航链路生成的稀疏障碍物点云。保留其
        // 密度，不能再按网页传输上限做第二次均匀抽样；改用其它主输入时可显式
        // 关闭该选项。Livox 回退仍保留 max_points_ 上限，防止原始激光流膨胀。
        preserve_primary_density_(declare_parameter<bool>(
            "preserve_primary_density", input_topic_ == "/collision_voxel_layer/points")),
        map_frame_(declare_parameter<std::string>("map_frame", "map")),
        base_frame_(declare_parameter<std::string>("base_frame", "base_footprint")),
        udp_host_(declare_parameter<std::string>("telemetry_udp_host", "127.0.0.1")),
        udp_port_(static_cast<int>(std::clamp<int64_t>(declare_parameter<int>("telemetry_udp_port", 8769), 1, 65535))),
        // 网关与浏览器协议的硬上限同为 3000。主输入在此范围内仍原样保留；
        // 若上游配置异常放大，必须在 C++ 侧安全抽样，绝不能发送一整帧随后被
        // 网关静默拒绝的点云。
        max_points_(static_cast<int>(std::clamp<int64_t>(declare_parameter<int>("max_points", 3000), 500, 3000))),
        rate_hz_(std::clamp(declare_parameter<double>("rate_hz", 10.0), 1.0, 20.0)),
        pose_rate_hz_(std::clamp(declare_parameter<double>("pose_rate_hz", 60.0), 10.0, 60.0)),
        // 这是“节点内最新槽”的最大停留时间，不用传感器 header 判断。部分传感器
        // 会在当前时刻发布带有较旧 stamp 的扫描，header 仍要留给 TF。
        max_input_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_input_age_ms", 140)), 50, 5000)),
        // map->odom 的低频边在部分定位栈中会短暂超过一个 120 ms 周期。
        // 250 ms 仍只接受当前位姿，却避免轻量位姿流因一次 TF 抖动断续。
        max_pose_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_pose_age_ms", 250)), 50, 5000)),
        max_costmap_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_costmap_age_ms", 5000)), 500, 30000)),
        max_range_m_(std::clamp(declare_parameter<double>("max_range_m", 25.0), 1.0, 80.0)),
        tf_buffer_(get_clock()),
        tf_listener_(tf_buffer_) {
    for (const std::string& frame : {base_frame_, std::string("base_link"), std::string("base_footprint_link")}) {
      if (!frame.empty() && base_frame_set_.insert(frame).second) base_frames_.push_back(frame);
    }
    // 传感器点云通常是 best-effort；输入只保留最新一帧，不能在节点内积压。
    auto sensor_input_qos = rclcpp::SensorDataQoS().keep_last(1);
    auto costmap_input_qos = rclcpp::QoS(1).reliable().transient_local();
    // C++ 预处理只经回环 UDP 向专用遥测网关交付紧凑数据，不再发布 hidden ROS
    // 话题，也不引入通用 ROS-Web 桥。
    if (cloud_enabled_) cloud_sender_ = std::make_unique<UdpLatestSender>(kCloudFrame, udp_host_, udp_port_, get_logger());
    if (pose_enabled_) pose_sender_ = std::make_unique<UdpLatestSender>(kPoseFrame, udp_host_, udp_port_, get_logger());
    if (costmap_enabled_) costmap_sender_ = std::make_unique<UdpLatestSender>(kCostmapFrame, udp_host_, udp_port_, get_logger());
    if (cloud_enabled_) {
      subscription_ = create_subscription<sensor_msgs::msg::PointCloud2>(
          input_topic_, sensor_input_qos, [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr message) {
            {
              std::lock_guard<std::mutex> guard(input_mutex_);
              latest_input_ = std::move(message);
              ++input_sequence_;
              last_primary_input_at_ = std::chrono::steady_clock::now();
              latest_input_received_at_ = last_primary_input_at_;
            }
            maybe_publish_latest();
          });
    // 主点云短暂不可用时，部分小车仍可从原生 Livox CustomMsg 回退。
    // 在此处一次性限点转换，避免再增加一个面向自动驾驶的转换节点。
      livox_subscription_ = create_subscription<livox_ros_driver2::msg::CustomMsg>(
        livox_input_topic_, sensor_input_qos, [this](livox_ros_driver2::msg::CustomMsg::ConstSharedPtr message) {
          // 主 PointCloud2 与原生 CustomMsg 不能同时处理，否则网页会在两组
          // 近乎同时的扫描之间跳变；原生流仅作为主输入缺失时的自动回退。
          {
            std::lock_guard<std::mutex> guard(input_mutex_);
            if (last_primary_input_at_ != std::chrono::steady_clock::time_point{} &&
                std::chrono::steady_clock::now() - last_primary_input_at_ < std::chrono::milliseconds(500)) return;
          }
          auto cloud = std::make_shared<sensor_msgs::msg::PointCloud2>();
          cloud->header = message->header;
          cloud->height = 1; cloud->is_bigendian = false; cloud->is_dense = false; cloud->point_step = 12;
          cloud->fields.resize(3);
          for (size_t index = 0; index < cloud->fields.size(); ++index) {
            auto& field = cloud->fields[index]; field.name = index == 0 ? "x" : (index == 1 ? "y" : "z");
            field.offset = static_cast<uint32_t>(index * 4); field.datatype = sensor_msgs::msg::PointField::FLOAT32; field.count = 1;
          }
          const size_t count = message->points.size();
          const size_t stride = std::max<size_t>(1, (count + static_cast<size_t>(max_points_) - 1) / static_cast<size_t>(max_points_));
          cloud->data.reserve(std::min(count / stride + 1, static_cast<size_t>(max_points_)) * cloud->point_step);
          for (size_t index = 0; index < count; index += stride) {
            const auto& point = message->points[index];
            if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) continue;
            append_float(cloud->data, point.x); append_float(cloud->data, point.y); append_float(cloud->data, point.z);
          }
          cloud->width = cloud->data.size() / cloud->point_step; cloud->row_step = cloud->width * cloud->point_step;
          {
            std::lock_guard<std::mutex> guard(input_mutex_);
            if (last_primary_input_at_ != std::chrono::steady_clock::time_point{} &&
                std::chrono::steady_clock::now() - last_primary_input_at_ < std::chrono::milliseconds(500)) return;
            latest_input_ = std::move(cloud);
            ++input_sequence_;
            latest_input_received_at_ = std::chrono::steady_clock::now();
          }
          maybe_publish_latest();
          });
    }
    if (pose_enabled_) {
      pose_timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / pose_rate_hz_), [this] { publish_pose(); });
    }
    if (costmap_enabled_) {
      costmap_subscription_ = create_subscription<nav_msgs::msg::OccupancyGrid>(
          costmap_input_topic_, costmap_input_qos,
          [this](nav_msgs::msg::OccupancyGrid::ConstSharedPtr message) { on_costmap(std::move(message)); });
      costmap_worker_ = std::thread([this] { costmap_worker_loop(); });
    }
    RCLCPP_INFO(get_logger(), "RY Aletheia telemetry preprocessors: cloud=%s, pose=%s, costmap=%s, udp=%s:%d",
                cloud_enabled_ ? "enabled" : "disabled", pose_enabled_ ? "enabled" : "disabled",
                costmap_enabled_ ? "enabled" : "disabled", udp_host_.c_str(), udp_port_);
  }

  ~LiveCloudPreprocessor() override {
    {
      std::lock_guard<std::mutex> guard(costmap_mutex_);
      costmap_stopping_ = true;
    }
    costmap_condition_.notify_one();
    if (costmap_worker_.joinable()) costmap_worker_.join();
  }

 private:
  struct Offsets {
    uint32_t x;
    uint32_t y;
    uint32_t z;
    std::optional<uint32_t> timestamp;
  };

  static std::optional<Offsets> offsets_of(const sensor_msgs::msg::PointCloud2& cloud) {
    std::optional<uint32_t> x, y, z, timestamp;
    for (const auto& field : cloud.fields) {
      if (field.count != 1) continue;
      // 标准 PointCloud2 若携带每点绝对纳秒 timestamp（float64），可作为快速
      // 转向时去畸变的时间基；不存在时保留整帧兼容投影。
      if (field.name == "timestamp" && field.datatype == sensor_msgs::msg::PointField::FLOAT64) timestamp = field.offset;
      // 本节点刻意仅接受标准 float32 x/y/z，避免推测自定义字段的编码。
      else if (field.datatype == sensor_msgs::msg::PointField::FLOAT32 && field.name == "x") x = field.offset;
      else if (field.datatype == sensor_msgs::msg::PointField::FLOAT32 && field.name == "y") y = field.offset;
      else if (field.datatype == sensor_msgs::msg::PointField::FLOAT32 && field.name == "z") z = field.offset;
    }
    if (!x || !y || !z) return std::nullopt;
    return Offsets{*x, *y, *z, timestamp};
  }

  static float read_float(const uint8_t* source, bool big_endian) {
    float value;
    if (!big_endian) { std::memcpy(&value, source, sizeof(value)); return value; }
    uint8_t bytes[sizeof(float)];
    for (size_t index = 0; index < sizeof(float); ++index) bytes[index] = source[sizeof(float) - 1 - index];
    std::memcpy(&value, bytes, sizeof(value));
    return value;
  }

  static double read_double(const uint8_t* source, bool big_endian) {
    double value;
    if (!big_endian) { std::memcpy(&value, source, sizeof(value)); return value; }
    uint8_t bytes[sizeof(double)];
    for (size_t index = 0; index < sizeof(double); ++index) bytes[index] = source[sizeof(double) - 1 - index];
    std::memcpy(&value, bytes, sizeof(value));
    return value;
  }

  static void append_float(std::vector<uint8_t>& target, float value) {
    const auto* raw = reinterpret_cast<const uint8_t*>(&value);
    target.insert(target.end(), raw, raw + sizeof(float));
  }

  bool is_stale(const builtin_interfaces::msg::Time& stamp, int maximum_age_ms) {
    // 未标记时间的少数旧驱动不能据此做可靠判定，保留兼容路径。正常 ROS 时间
    // 则在进入任何坐标变换前丢弃过期帧，绝不让旧扫描占用 CPU 或网页带宽。
    if (stamp.sec == 0 && stamp.nanosec == 0) return false;
    const auto age = get_clock()->now() - rclcpp::Time(stamp, get_clock()->get_clock_type());
    return age.nanoseconds() > static_cast<int64_t>(maximum_age_ms) * 1000000LL;
  }

  static bool is_identity_costmap_transform(const geometry_msgs::msg::TransformStamped& transform) {
    // 这个降级只用于现场已确认 map 与 odom 严格重合、但动态 TF 时间戳短暂
    // 断续的场景。必须比较完整的 3D 位移和四元数，不能只看平面 yaw，更不能
    // 因“看起来接近”就把一个实际发生定位漂移的 map<-odom 当作单位变换。
    constexpr double kTranslationEpsilon = 1e-4;
    constexpr double kQuaternionEpsilon = 1e-4;
    const auto& translation = transform.transform.translation;
    const auto& rotation = transform.transform.rotation;
    return std::isfinite(translation.x) && std::isfinite(translation.y) && std::isfinite(translation.z) &&
           std::isfinite(rotation.x) && std::isfinite(rotation.y) && std::isfinite(rotation.z) &&
           std::isfinite(rotation.w) &&
           std::abs(translation.x) <= kTranslationEpsilon && std::abs(translation.y) <= kTranslationEpsilon &&
           std::abs(translation.z) <= kTranslationEpsilon && std::abs(rotation.x) <= kQuaternionEpsilon &&
           std::abs(rotation.y) <= kQuaternionEpsilon && std::abs(rotation.z) <= kQuaternionEpsilon &&
           std::abs(std::abs(rotation.w) - 1.0) <= kQuaternionEpsilon;
  }

  enum class CostmapPublishResult { kPublishedOrDiscarded, kRetryWhenTfChanges };

  void on_costmap(nav_msgs::msg::OccupancyGrid::ConstSharedPtr message) {
    // 此 callback 是 ROS executor 热路径：它只验证固定边界并覆盖一个最新槽。
    // TF、字节序编码和 UDP send 都只能在 costmap worker 中执行。
    if (!message || message->header.frame_id.empty() || !std::isfinite(message->info.resolution) ||
        message->info.resolution <= 0.0F) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "Skip local costmap without a source frame or positive finite resolution");
      return;
    }
    const uint64_t cell_count = static_cast<uint64_t>(message->info.width) * message->info.height;
    if (message->info.width == 0 || message->info.height == 0 || cell_count > UINT16_MAX ||
        message->data.size() != cell_count) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "Skip local costmap with invalid dimensions/data length: %ux%u cells=%zu",
                           message->info.width, message->info.height, message->data.size());
      return;
    }
    {
      std::lock_guard<std::mutex> guard(costmap_mutex_);
      latest_costmap_ = std::move(message);
      ++costmap_sequence_;
      latest_costmap_received_at_ = std::chrono::steady_clock::now();
    }
    costmap_condition_.notify_one();
  }

  void costmap_worker_loop() {
    uint64_t last_attempted_sequence = 0;
    bool retry_current = false;
    while (true) {
      {
        std::unique_lock<std::mutex> lock(costmap_mutex_);
        if (retry_current) {
          // TF 尚未可用时只以低频重试同一最新输入；新 frame 会立刻唤醒，绝不积压。
          costmap_condition_.wait_for(lock, std::chrono::milliseconds(200), [this, last_attempted_sequence] {
            return costmap_stopping_ || costmap_sequence_ != last_attempted_sequence;
          });
        } else {
          costmap_condition_.wait(lock, [this, last_attempted_sequence] {
            return costmap_stopping_ || costmap_sequence_ != last_attempted_sequence;
          });
        }
        if (costmap_stopping_) return;
        last_attempted_sequence = costmap_sequence_;
      }
      retry_current = publish_costmap() == CostmapPublishResult::kRetryWhenTfChanges;
    }
  }

  CostmapPublishResult publish_costmap() {
    if (!costmap_sender_ || !costmap_sender_->available()) return CostmapPublishResult::kPublishedOrDiscarded;
    nav_msgs::msg::OccupancyGrid::ConstSharedPtr input;
    uint64_t sequence = 0;
    std::chrono::steady_clock::time_point received_at;
    {
      std::lock_guard<std::mutex> guard(costmap_mutex_);
      input = latest_costmap_;
      sequence = costmap_sequence_;
      received_at = latest_costmap_received_at_;
    }
    if (!input || received_at == std::chrono::steady_clock::time_point{} ||
        std::chrono::steady_clock::now() - received_at > std::chrono::milliseconds(max_costmap_age_ms_)) {
      return CostmapPublishResult::kPublishedOrDiscarded;
    }
    // TRANSIENT_LOCAL 会在本节点晚启动时立即交付最后一张栅格。该回调接收时间
    // 虽然是新的，但 header 可能已早于本节点 TF buffer 数分钟；不能以“刚收到”
    // 为由用无效的历史坐标继续重试，更不能退回到最新 TF 伪造位置。
    if (is_stale(input->header.stamp, max_costmap_age_ms_)) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "Skip stale local costmap source stamp; waiting for a newer /local_costmap/costmap frame");
      return CostmapPublishResult::kPublishedOrDiscarded;
    }

    geometry_msgs::msg::TransformStamped map_from_source;
    try {
      // local_costmap 当前发布 odom；必须按此栅格消息的 stamp 获取 map<-odom，
      // 不能把启动阶段偶然出现的 identity TF 当作长期坐标约束。
      map_from_source = tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, input->header.stamp,
                                                    tf2::durationFromSec(0.02));
    } catch (const tf2::TransformException& error) {
      const bool source_is_odom = input->header.frame_id == "odom" || input->header.frame_id == "/odom";
      if (source_is_odom) {
        try {
          // 只在精确时间查询失败后做一个受限的诊断兼容：若当前最新 map<-odom
          // 经完整数值检查确为单位变换，fresh odom 栅格的坐标仍可无损映射到 map。
          // 非单位变换、其它 source frame 或任何查询失败均不能走这条路径。
          const auto latest_map_from_odom = tf_buffer_.lookupTransform(
              map_frame_, input->header.frame_id, tf2::TimePointZero, tf2::durationFromSec(0.02));
          if (is_identity_costmap_transform(latest_map_from_odom)) {
            map_from_source = latest_map_from_odom;
            RCLCPP_WARN_THROTTLE(
                get_logger(), *get_clock(), 5000,
                "Stamped %s <- odom TF unavailable; using verified identity fallback for fresh local costmap: %s",
                map_frame_.c_str(), error.what());
          } else {
            RCLCPP_WARN_THROTTLE(
                get_logger(), *get_clock(), 2000,
                "Stamped %s <- odom TF unavailable and latest transform is not identity; local costmap frame skipped: %s",
                map_frame_.c_str(), error.what());
            return CostmapPublishResult::kRetryWhenTfChanges;
          }
        } catch (const tf2::TransformException&) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                               "Waiting for stamped %s <- %s TF; local costmap frame skipped: %s",
                               map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
          return CostmapPublishResult::kRetryWhenTfChanges;
        }
      } else {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                             "Waiting for stamped %s <- %s TF; local costmap frame skipped: %s",
                             map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
        return CostmapPublishResult::kRetryWhenTfChanges;
      }
    }

    const auto& source_rotation = map_from_source.transform.rotation;
    const auto& grid_rotation = input->info.origin.orientation;
    const double source_yaw = std::atan2(
        2.0 * (source_rotation.w * source_rotation.z + source_rotation.x * source_rotation.y),
        1.0 - 2.0 * (source_rotation.y * source_rotation.y + source_rotation.z * source_rotation.z));
    const double grid_yaw = std::atan2(
        2.0 * (grid_rotation.w * grid_rotation.z + grid_rotation.x * grid_rotation.y),
        1.0 - 2.0 * (grid_rotation.y * grid_rotation.y + grid_rotation.z * grid_rotation.z));
    const double origin_x = map_from_source.transform.translation.x + std::cos(source_yaw) * input->info.origin.position.x -
                            std::sin(source_yaw) * input->info.origin.position.y;
    const double origin_y = map_from_source.transform.translation.y + std::sin(source_yaw) * input->info.origin.position.x +
                            std::cos(source_yaw) * input->info.origin.position.y;
    const double origin_yaw = std::atan2(std::sin(source_yaw + grid_yaw), std::cos(source_yaw + grid_yaw));
    if (!std::isfinite(origin_x) || !std::isfinite(origin_y) || !std::isfinite(origin_yaw)) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Skip local costmap with non-finite map origin");
      return CostmapPublishResult::kPublishedOrDiscarded;
    }

    std::vector<uint8_t> payload;
    payload.reserve(20 + input->data.size());
    append_network_float(payload, static_cast<float>(origin_x));
    append_network_float(payload, static_cast<float>(origin_y));
    append_network_float(payload, static_cast<float>(origin_yaw));
    append_network_float(payload, input->info.resolution);
    append_u16(payload, static_cast<uint16_t>(input->info.width));
    append_u16(payload, static_cast<uint16_t>(input->info.height));
    payload.insert(payload.end(), input->data.begin(), input->data.end());
    {
      std::lock_guard<std::mutex> guard(costmap_mutex_);
      // Worker 编码期间有新帧到达时，旧图直接废弃；下一轮只处理更新数据。
      if (sequence != costmap_sequence_) return CostmapPublishResult::kPublishedOrDiscarded;
    }
    const int64_t stamp_ns = static_cast<int64_t>(input->header.stamp.sec) * 1'000'000'000LL +
                             static_cast<int64_t>(input->header.stamp.nanosec);
    costmap_sender_->publish({
        static_cast<uint64_t>(std::max<int64_t>(0, stamp_ns)),
        static_cast<uint16_t>(input->data.size()),
        std::move(payload),
    });
    RCLCPP_INFO_THROTTLE(get_logger(), *get_clock(), 5000,
                         "Local costmap telemetry: source=%s %ux%u resolution=%.3fm",
                         input->header.frame_id.c_str(), input->info.width, input->info.height, input->info.resolution);
    return CostmapPublishResult::kPublishedOrDiscarded;
  }

  void publish_pose() {
    if (!pose_sender_ || !pose_sender_->available()) return;
    std::optional<geometry_msgs::msg::TransformStamped> transform;
    for (const auto& frame : base_frames_) {
      try {
        // 仅用于显示：使用最新可用变换，避免等待历史时间戳导致车体落后真实运动。
        transform = tf_buffer_.lookupTransform(map_frame_, frame, tf2::TimePointZero);
        break;
      } catch (const tf2::TransformException&) { }
    }
    if (!transform) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                           "Waiting for latest %s <- base_footprint/base_link TF; pose telemetry has no frame to send",
                           map_frame_.c_str());
      return;
    }
    // map->odom 往往低频，而 base->odom 高频；合成 lookup 的 header stamp 可能
    // 继承低频边而看似“过期”。这里已经请求 TimePointZero 的最新可用位姿，不能
    // 因该合成时间戳再次丢弃整条车体流，否则浏览器只能退回批量 /tf。
    if (is_stale(transform->header.stamp, max_pose_age_ms_)) {
      RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Latest %s <- base transform stamp exceeds %d ms; publishing latest pose for display", map_frame_.c_str(), max_pose_age_ms_);
    }
    // 浏览器仅需要 map 平面位姿。四元数不再经 ROS CDR 转发，改为三个
    // network-order float32：x、y、yaw；实际网络发送由 UdpLatestSender 线程完成。
    const auto& rotation = transform->transform.rotation;
    const double yaw = std::atan2(2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
                                  1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z));
    std::vector<uint8_t> payload;
    payload.reserve(12);
    append_network_float(payload, static_cast<float>(transform->transform.translation.x));
    append_network_float(payload, static_cast<float>(transform->transform.translation.y));
    append_network_float(payload, static_cast<float>(yaw));
    const auto now_ns = static_cast<uint64_t>(std::max<int64_t>(0, get_clock()->now().nanoseconds()));
    pose_sender_->publish({now_ns, 1, std::move(payload)});
  }

  void maybe_publish_latest() {
    if (!cloud_sender_ || !cloud_sender_->available()) return;
    const auto now = std::chrono::steady_clock::now();
    const auto period = std::chrono::duration<double>(1.0 / rate_hz_);
    // 上游 collision voxel 层在自动驾驶时可能高于 10 Hz。实际限频必须在 C++
    // 生效，不能仅靠浏览器丢帧；被跳过的数据已在输入 latest slot 中自然覆盖。
    if (last_cloud_publish_at_ != std::chrono::steady_clock::time_point{} && now - last_cloud_publish_at_ < period) return;
    last_cloud_publish_at_ = now;
    publish_latest();
  }

  void publish_latest() {
    sensor_msgs::msg::PointCloud2::ConstSharedPtr input;
    uint64_t sequence = 0;
    std::chrono::steady_clock::time_point received_at;
    {
      std::lock_guard<std::mutex> guard(input_mutex_);
      input = latest_input_;
      sequence = input_sequence_;
      received_at = latest_input_received_at_;
    }
    if (!input || sequence == published_sequence_ || input->point_step == 0) return;
    if (received_at == std::chrono::steady_clock::time_point{} ||
        std::chrono::steady_clock::now() - received_at > std::chrono::milliseconds(max_input_age_ms_)) {
      // 只拒绝在本节点内等待过久的扫描，绝不能把传感器 header 的时间基误当作
      // 网络接收时间；该 header 仍用于下方精确 TF/逐点去畸变。
      published_sequence_ = sequence;
      return;
    }
    if (input->height != 1) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Skip organized PointCloud2: this bounded live renderer accepts height=1 scans only");
      published_sequence_ = sequence;
      return;
    }
    const auto fields = offsets_of(*input);
    if (!fields || fields->x + 4 > input->point_step || fields->y + 4 > input->point_step || fields->z + 4 > input->point_step) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Skip PointCloud2: standard float32 x/y/z fields are required");
      published_sequence_ = sequence;
      return;
    }
    const size_t input_count = input->data.size() / input->point_step;
    // 主 collision 层已经是上游为导航裁剪后的可视障碍物集合。这里仅作坐标
    // 投影与距离过滤；在协议上限以内不再抽样，只有超出预算才安全均匀取样。
    const size_t point_budget = static_cast<size_t>(max_points_);
    // collision_voxel_layer 正常情况下已远低于预算，因此保留全部有效点；只有
    // 配置异常或源膨胀超过协议硬上限时才均匀抽样，避免网关拒绝整帧。
    const size_t stride = preserve_primary_density_ && input_count <= point_budget
      ? 1
      : std::max<size_t>(1, (input_count + point_budget - 1) / point_budget);
    constexpr int64_t kDeskewBucketNs = 5'000'000LL;
    const int64_t header_ns = static_cast<int64_t>(input->header.stamp.sec) * 1'000'000'000LL + input->header.stamp.nanosec;
    bool deskew = fields->timestamp && *fields->timestamp + sizeof(double) <= input->point_step && input_count > 0;
    int64_t scan_start_ns = header_ns;
    if (deskew) {
      const double first_timestamp = read_double(input->data.data() + *fields->timestamp, input->is_bigendian);
      // 已在实车验证 timestamp 是绝对纳秒。异常/未知格式不能贸然按点投影。
      if (!std::isfinite(first_timestamp) || first_timestamp < 1e15 || std::llabs(static_cast<int64_t>(first_timestamp) - header_ns) > 500'000'000LL) deskew = false;
      else scan_start_ns = static_cast<int64_t>(first_timestamp);
    }
    geometry_msgs::msg::TransformStamped transform;
    std::unordered_map<int64_t, geometry_msgs::msg::TransformStamped> deskew_transforms;
    if (deskew) {
      // 5 ms 时间桶最多约 20 次 TF 查询/扫描；每桶内的 3000 点直接复用矩阵。
      // 历史覆盖缺一个桶时降级为整帧变换，不能因增强型去畸变把整条实时点云
      // 置空。整帧变换仍优先使用扫描 header 时刻，最后才使用最新 TF。
      for (size_t index = 0; index < input_count; index += stride) {
        const uint8_t* base = input->data.data() + index * input->point_step;
        const double point_timestamp = read_double(base + *fields->timestamp, input->is_bigendian);
        if (!std::isfinite(point_timestamp)) { deskew = false; break; }
        const int64_t bucket = std::max<int64_t>(0, (static_cast<int64_t>(point_timestamp) - scan_start_ns) / kDeskewBucketNs);
        if (deskew_transforms.find(bucket) != deskew_transforms.end()) continue;
        try {
          const int64_t bucket_time = scan_start_ns + bucket * kDeskewBucketNs + kDeskewBucketNs / 2;
          deskew_transforms.emplace(bucket, tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, rclcpp::Time(bucket_time, get_clock()->get_clock_type()), tf2::durationFromSec(0.002)));
        } catch (const tf2::TransformException&) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "Deskew fallback: incomplete TF coverage for %s; using one scan transform", input->header.frame_id.c_str());
          deskew = false;
          deskew_transforms.clear();
          break;
        }
      }
    }
    if (!deskew) {
      try {
        transform = tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, input->header.stamp, tf2::durationFromSec(0.02));
      } catch (const tf2::TransformException& error) {
        try {
          // 无逐点时间的兼容输入才允许回退最新变换；Livox 标准流会走上面的
          // 历史 TF 去畸变路径，不能因快速转向而产生整帧扇形畸变。
          transform = tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, tf2::TimePointZero);
          RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Using latest %s <- %s transform after stamped lookup failed: %s", map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
        } catch (const tf2::TransformException&) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                               "Waiting for %s <- %s transform; cloud telemetry frame skipped: %s",
                               map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
          return;
        }
      }
    }
    // 地图渲染只使用 x/y。丢弃 z 后每帧仅约 24 KiB（3000 点），并避免产生一份
    // PointCloud2 再让其它 ROS 节点复制和序列化。
    std::vector<uint8_t> payload;
    payload.reserve(std::min(input_count / stride, static_cast<size_t>(max_points_)) * 8);
    const double max_squared = max_range_m_ * max_range_m_;
    for (size_t index = 0; index < input_count; index += stride) {
      const uint8_t* base = input->data.data() + index * input->point_step;
      const float x = read_float(base + fields->x, input->is_bigendian);
      const float y = read_float(base + fields->y, input->is_bigendian);
      const float z = read_float(base + fields->z, input->is_bigendian);
      if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || x*x + y*y + z*z > max_squared) continue;
      const geometry_msgs::msg::Transform& active_transform = deskew
        ? deskew_transforms.at(std::max<int64_t>(0, (static_cast<int64_t>(read_double(base + *fields->timestamp, input->is_bigendian)) - scan_start_ns) / kDeskewBucketNs)).transform
        : transform.transform;
      const auto& q = active_transform.rotation;
      const double xx = q.x * q.x, yy = q.y * q.y, zz = q.z * q.z;
      const double xy = q.x * q.y, xz = q.x * q.z, yz = q.y * q.z, wx = q.w * q.x, wy = q.w * q.y, wz = q.w * q.z;
      const float tx = static_cast<float>((1 - 2 * (yy + zz)) * x + 2 * (xy - wz) * y + 2 * (xz + wy) * z + active_transform.translation.x);
      const float ty = static_cast<float>(2 * (xy + wz) * x + (1 - 2 * (xx + zz)) * y + 2 * (yz - wx) * z + active_transform.translation.y);
      append_network_float(payload, tx);
      append_network_float(payload, ty);
    }
    const auto point_count = static_cast<uint16_t>(payload.size() / 8);
    RCLCPP_INFO_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "Cloud telemetry: source=%s input=%zu sent=%u mode=%s range=%.1fm",
        input_topic_.c_str(), input_count, point_count,
        preserve_primary_density_ ? "preserve-upstream-density" : "bounded-uniform-sample",
        max_range_m_);
    const auto timestamp_ns = header_ns > 0 ? static_cast<uint64_t>(header_ns)
                                            : static_cast<uint64_t>(std::max<int64_t>(0, get_clock()->now().nanoseconds()));
    cloud_sender_->publish({timestamp_ns, point_count, std::move(payload)});
    published_sequence_ = sequence;
  }

  std::string input_topic_, livox_input_topic_, costmap_input_topic_, map_frame_, base_frame_, udp_host_;
  bool cloud_enabled_, pose_enabled_, costmap_enabled_, preserve_primary_density_;
  int max_points_;
  int udp_port_;
  double rate_hz_, pose_rate_hz_, max_range_m_;
  int max_input_age_ms_, max_pose_age_ms_, max_costmap_age_ms_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
  rclcpp::Subscription<livox_ros_driver2::msg::CustomMsg>::SharedPtr livox_subscription_;
  rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr costmap_subscription_;
  rclcpp::TimerBase::SharedPtr pose_timer_;
  std::unique_ptr<UdpLatestSender> cloud_sender_;
  std::unique_ptr<UdpLatestSender> pose_sender_;
  std::unique_ptr<UdpLatestSender> costmap_sender_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  std::vector<std::string> base_frames_;
  std::unordered_set<std::string> base_frame_set_;
  std::mutex input_mutex_;
  sensor_msgs::msg::PointCloud2::ConstSharedPtr latest_input_;
  std::chrono::steady_clock::time_point last_primary_input_at_;
  std::chrono::steady_clock::time_point latest_input_received_at_;
  std::chrono::steady_clock::time_point last_cloud_publish_at_;
  uint64_t input_sequence_{0}, published_sequence_{0};
  std::mutex costmap_mutex_;
  std::condition_variable costmap_condition_;
  nav_msgs::msg::OccupancyGrid::ConstSharedPtr latest_costmap_;
  std::chrono::steady_clock::time_point latest_costmap_received_at_;
  uint64_t costmap_sequence_{0};
  bool costmap_stopping_{false};
  std::thread costmap_worker_;
};

}  // namespace aletheia_live_preprocessor

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<aletheia_live_preprocessor::LiveCloudPreprocessor>());
  rclcpp::shutdown();
  return 0;
}
