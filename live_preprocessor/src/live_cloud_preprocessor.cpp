#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_set>
#include <vector>

#include <builtin_interfaces/msg/time.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <livox_ros_driver2/msg/custom_msg.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/msg/point_field.hpp>
#include <tf2/exceptions.h>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

namespace aletheia_live_preprocessor {

class LiveCloudPreprocessor final : public rclcpp::Node {
 public:
  LiveCloudPreprocessor()
      // 不能与控制台主进程共用完全相同的 ROS 节点名，否则 ROS2 会把两个
      // 独立进程视为同名节点并造成参数/服务发现不确定。名称仍明确归属工具。
      : Node("ry_aletheia_live"),
        input_topic_(declare_parameter<std::string>("input_topic", "/livox/points")),
        livox_input_topic_(declare_parameter<std::string>("livox_input_topic", "/livox/lidar")),
        // 下划线命名空间是 ROS 2 的 hidden 约定：这两条仅供 Aletheia 实时
        // 观测使用，不应在 RViz 的常规话题选择器中被当作业务传感器话题展示。
        output_topic_(declare_parameter<std::string>("output_topic", "/_aletheia/live_points")),
        pose_topic_(declare_parameter<std::string>("pose_topic", "/_aletheia/live_pose")),
        cloud_enabled_(declare_parameter<bool>("enable_cloud", true)),
        pose_enabled_(declare_parameter<bool>("enable_pose", true)),
        map_frame_(declare_parameter<std::string>("map_frame", "map")),
        base_frame_(declare_parameter<std::string>("base_frame", "base_footprint")),
        max_points_(static_cast<int>(std::clamp<int64_t>(declare_parameter<int>("max_points", 5000), 500, 12000))),
        rate_hz_(std::clamp(declare_parameter<double>("rate_hz", 10.0), 1.0, 20.0)),
        pose_rate_hz_(std::clamp(declare_parameter<double>("pose_rate_hz", 60.0), 10.0, 60.0)),
        // 这是“节点内最新槽”的最大停留时间，不用传感器 header 判断。部分 Livox
        // 驱动会在当前时刻发布带有数百毫秒旧 stamp 的扫描，header 仍要留给 TF。
        max_input_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_input_age_ms", 140)), 50, 5000)),
        // map->odom 的低频边在部分定位栈中会短暂超过一个 120 ms 周期。
        // 250 ms 仍只接受当前位姿，却避免轻量位姿流因一次 TF 抖动断续。
        max_pose_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_pose_age_ms", 250)), 50, 5000)),
        max_range_m_(std::clamp(declare_parameter<double>("max_range_m", 25.0), 1.0, 80.0)),
        tf_buffer_(get_clock()),
        tf_listener_(tf_buffer_) {
    for (const std::string& frame : {base_frame_, std::string("base_link"), std::string("base_footprint_link")}) {
      if (!frame.empty() && base_frame_set_.insert(frame).second) base_frames_.push_back(frame);
    }
    // 雷达驱动通常是 best-effort；输入只保留最新一帧，不能在节点内积压。
    auto sensor_input_qos = rclcpp::SensorDataQoS().keep_last(1);
    // Foxglove Bridge 对显式订阅的 PointCloud2 默认请求 reliable。输出也使用
    // reliable + depth=1，既保证 DDS 能匹配，又绝不缓存历史扫描造成显示滞后。
    auto cloud_output_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile();
    // 位姿仅数十字节，使用可靠 depth=1 传输。它与高频 best-effort 点云分离后，
    // 即使点云在 Wi-Fi 或 DDS 层被丢弃，车体位置仍必须优先抵达 Bridge。
    auto pose_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile();
    if (cloud_enabled_) {
      subscription_ = create_subscription<sensor_msgs::msg::PointCloud2>(
          input_topic_, sensor_input_qos, [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr message) {
            {
              std::lock_guard<std::mutex> guard(input_mutex_);
              latest_input_ = std::move(message);
              ++input_sequence_;
              last_standard_input_at_ = std::chrono::steady_clock::now();
              latest_input_received_at_ = last_standard_input_at_;
            }
            // 独立点云进程在扫描抵达时立刻处理，避免定时轮询额外等待一帧。
            publish_latest();
          });
    // 部分小车没有启用 livox_to_pointcloud2，只有原生 CustomMsg 在发布。
    // 在此处一次性限点转换，避免再增加一个面向自动驾驶的转换节点。
      livox_subscription_ = create_subscription<livox_ros_driver2::msg::CustomMsg>(
        livox_input_topic_, sensor_input_qos, [this](livox_ros_driver2::msg::CustomMsg::ConstSharedPtr message) {
          // 部分车同时发布 PointCloud2 与同一雷达的原生 CustomMsg。若两者都
          // 处理，网页会在两组近乎同时的扫描之间跳变；标准流存在时只使用它，
          // 原生流仅作为转换节点未运行时的自动回退。
          {
            std::lock_guard<std::mutex> guard(input_mutex_);
            if (last_standard_input_at_ != std::chrono::steady_clock::time_point{} &&
                std::chrono::steady_clock::now() - last_standard_input_at_ < std::chrono::milliseconds(500)) return;
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
            if (last_standard_input_at_ != std::chrono::steady_clock::time_point{} &&
                std::chrono::steady_clock::now() - last_standard_input_at_ < std::chrono::milliseconds(500)) return;
            latest_input_ = std::move(cloud);
            ++input_sequence_;
            latest_input_received_at_ = std::chrono::steady_clock::now();
          }
          publish_latest();
          });
      publisher_ = create_publisher<sensor_msgs::msg::PointCloud2>(output_topic_, cloud_output_qos);
    }
    if (pose_enabled_) {
      pose_publisher_ = create_publisher<geometry_msgs::msg::PoseStamped>(pose_topic_, pose_qos);
      pose_timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / pose_rate_hz_), [this] { publish_pose(); });
    }
    RCLCPP_INFO(get_logger(), "RY Aletheia live stream: cloud=%s, pose=%s", cloud_enabled_ ? "enabled" : "disabled", pose_enabled_ ? "enabled" : "disabled");
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
      // Livox PointCloud2 的 timestamp 是每点绝对纳秒时间（float64）。它是
      // 快速转向时去畸变所需的时间基；不存在时保留整帧兼容投影。
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

  void publish_pose() {
    std::optional<geometry_msgs::msg::TransformStamped> transform;
    for (const auto& frame : base_frames_) {
      try {
        // 仅用于显示：使用最新可用变换，避免等待历史时间戳导致车体落后真实运动。
        transform = tf_buffer_.lookupTransform(map_frame_, frame, tf2::TimePointZero);
        break;
      } catch (const tf2::TransformException&) { }
    }
    if (!transform) return;
    // map->odom 往往低频，而 base->odom 高频；合成 lookup 的 header stamp 可能
    // 继承低频边而看似“过期”。这里已经请求 TimePointZero 的最新可用位姿，不能
    // 因该合成时间戳再次丢弃整条车体流，否则浏览器只能退回批量 /tf。
    if (is_stale(transform->header.stamp, max_pose_age_ms_)) {
      RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Latest %s <- base transform stamp exceeds %d ms; publishing latest pose for display", map_frame_.c_str(), max_pose_age_ms_);
    }
    geometry_msgs::msg::PoseStamped output;
    output.header = transform->header;
    output.header.frame_id = map_frame_;
    output.pose.position.x = transform->transform.translation.x;
    output.pose.position.y = transform->transform.translation.y;
    output.pose.position.z = transform->transform.translation.z;
    output.pose.orientation = transform->transform.rotation;
    pose_publisher_->publish(output);
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
    const size_t stride = std::max<size_t>(1, (input_count + static_cast<size_t>(max_points_) - 1) / static_cast<size_t>(max_points_));
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
          RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Waiting for %s <- %s transform: %s", map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
          return;
        }
      }
    }
    sensor_msgs::msg::PointCloud2 output;
    output.header.stamp = input->header.stamp;
    output.header.frame_id = map_frame_;
    output.height = 1;
    output.is_bigendian = false;
    output.is_dense = false;
    output.point_step = 12;
    output.fields.resize(3);
    for (size_t index = 0; index < output.fields.size(); ++index) {
      auto& field = output.fields[index];
      field.name = index == 0 ? "x" : (index == 1 ? "y" : "z");
      field.offset = static_cast<uint32_t>(index * 4);
      field.datatype = sensor_msgs::msg::PointField::FLOAT32;
      field.count = 1;
    }
    output.data.reserve(std::min(input_count / stride, static_cast<size_t>(max_points_)) * output.point_step);
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
      const float tz = static_cast<float>(2 * (xz - wy) * x + 2 * (yz + wx) * y + (1 - 2 * (xx + yy)) * z + active_transform.translation.z);
      append_float(output.data, tx); append_float(output.data, ty); append_float(output.data, tz);
    }
    output.width = output.data.size() / output.point_step;
    output.row_step = output.width * output.point_step;
    publisher_->publish(output);
    published_sequence_ = sequence;
  }

  std::string input_topic_, livox_input_topic_, output_topic_, pose_topic_, map_frame_, base_frame_;
  bool cloud_enabled_, pose_enabled_;
  int max_points_;
  double rate_hz_, pose_rate_hz_, max_range_m_;
  int max_input_age_ms_, max_pose_age_ms_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
  rclcpp::Subscription<livox_ros_driver2::msg::CustomMsg>::SharedPtr livox_subscription_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr publisher_;
  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr pose_publisher_;
  rclcpp::TimerBase::SharedPtr pose_timer_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  std::vector<std::string> base_frames_;
  std::unordered_set<std::string> base_frame_set_;
  std::mutex input_mutex_;
  sensor_msgs::msg::PointCloud2::ConstSharedPtr latest_input_;
  std::chrono::steady_clock::time_point last_standard_input_at_;
  std::chrono::steady_clock::time_point latest_input_received_at_;
  uint64_t input_sequence_{0}, published_sequence_{0};
};

}  // namespace aletheia_live_preprocessor

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<aletheia_live_preprocessor::LiveCloudPreprocessor>());
  rclcpp::shutdown();
  return 0;
}
