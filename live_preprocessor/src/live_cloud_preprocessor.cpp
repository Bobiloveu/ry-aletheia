#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
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
        output_topic_(declare_parameter<std::string>("output_topic", "/aletheia/live_points")),
        pose_topic_(declare_parameter<std::string>("pose_topic", "/aletheia/live_pose")),
        map_frame_(declare_parameter<std::string>("map_frame", "map")),
        base_frame_(declare_parameter<std::string>("base_frame", "base_footprint")),
        max_points_(static_cast<int>(std::clamp<int64_t>(declare_parameter<int>("max_points", 5000), 500, 12000))),
        rate_hz_(std::clamp(declare_parameter<double>("rate_hz", 10.0), 1.0, 20.0)),
        pose_rate_hz_(std::clamp(declare_parameter<double>("pose_rate_hz", 45.0), 10.0, 60.0)),
        max_input_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_input_age_ms", 180)), 50, 5000)),
        max_pose_age_ms_(std::clamp(static_cast<int>(declare_parameter<int>("max_pose_age_ms", 120)), 50, 5000)),
        max_range_m_(std::clamp(declare_parameter<double>("max_range_m", 25.0), 1.0, 80.0)),
        tf_buffer_(get_clock()),
        tf_listener_(tf_buffer_) {
    for (const std::string& frame : {base_frame_, std::string("base_link"), std::string("base_footprint_link")}) {
      if (!frame.empty() && base_frame_set_.insert(frame).second) base_frames_.push_back(frame);
    }
    // depth=1 是关键安全边界：后端和浏览器都只处理最新扫描，不累积历史延迟。
    auto qos = rclcpp::SensorDataQoS().keep_last(1);
    subscription_ = create_subscription<sensor_msgs::msg::PointCloud2>(
        input_topic_, qos, [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr message) {
          std::lock_guard<std::mutex> guard(input_mutex_);
          latest_input_ = std::move(message);
          ++input_sequence_;
        });
    // 部分小车没有启用 livox_to_pointcloud2，只有原生 CustomMsg 在发布。
    // 在此处一次性限点转换，避免再增加一个面向自动驾驶的转换节点。
    livox_subscription_ = create_subscription<livox_ros_driver2::msg::CustomMsg>(
        livox_input_topic_, qos, [this](livox_ros_driver2::msg::CustomMsg::ConstSharedPtr message) {
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
          std::lock_guard<std::mutex> guard(input_mutex_);
          latest_input_ = std::move(cloud); ++input_sequence_;
        });
    publisher_ = create_publisher<sensor_msgs::msg::PointCloud2>(output_topic_, qos);
    pose_publisher_ = create_publisher<geometry_msgs::msg::PoseStamped>(pose_topic_, qos);
    timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / rate_hz_), [this] { publish_latest(); });
    pose_timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / pose_rate_hz_), [this] { publish_pose(); });
    RCLCPP_INFO(get_logger(), "RY Aletheia live stream: PointCloud2=%s, Livox=%s -> %s (%.1f Hz), pose %s -> %s (%.1f Hz)", input_topic_.c_str(), livox_input_topic_.c_str(), output_topic_.c_str(), rate_hz_, base_frame_.c_str(), pose_topic_.c_str(), pose_rate_hz_);
  }

 private:
  struct Offsets { uint32_t x; uint32_t y; uint32_t z; };

  static std::optional<Offsets> offsets_of(const sensor_msgs::msg::PointCloud2& cloud) {
    std::optional<uint32_t> x, y, z;
    for (const auto& field : cloud.fields) {
      // 本节点刻意仅接受标准 float32 x/y/z，避免推测自定义字段的编码。
      if (field.datatype != sensor_msgs::msg::PointField::FLOAT32 || field.count != 1) continue;
      if (field.name == "x") x = field.offset;
      else if (field.name == "y") y = field.offset;
      else if (field.name == "z") z = field.offset;
    }
    if (!x || !y || !z) return std::nullopt;
    return Offsets{*x, *y, *z};
  }

  static float read_float(const uint8_t* source, bool big_endian) {
    float value;
    if (!big_endian) { std::memcpy(&value, source, sizeof(value)); return value; }
    uint8_t bytes[sizeof(float)];
    for (size_t index = 0; index < sizeof(float); ++index) bytes[index] = source[sizeof(float) - 1 - index];
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
    if (is_stale(transform->header.stamp, max_pose_age_ms_)) return;
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
    {
      std::lock_guard<std::mutex> guard(input_mutex_);
      input = latest_input_;
      sequence = input_sequence_;
    }
    if (!input || sequence == published_sequence_ || input->point_step == 0) return;
    if (is_stale(input->header.stamp, max_input_age_ms_)) {
      // 标记为已消费，避免下一个定时器继续检查同一份过期扫描。
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
    geometry_msgs::msg::TransformStamped transform;
    try {
      transform = tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, input->header.stamp, tf2::durationFromSec(0.02));
    } catch (const tf2::TransformException& error) {
      try {
        // Livox 原生消息与定位 TF 的时间基有时并不完全对齐。这里仅用于只读
        // 实时画面：精确查询失败时采用最新有效变换，避免把整帧点云长期丢弃。
        transform = tf_buffer_.lookupTransform(map_frame_, input->header.frame_id, tf2::TimePointZero);
        RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Using latest %s <- %s transform after stamped lookup failed: %s", map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
      } catch (const tf2::TransformException&) {
        RCLCPP_DEBUG_THROTTLE(get_logger(), *get_clock(), 2000, "Waiting for %s <- %s transform: %s", map_frame_.c_str(), input->header.frame_id.c_str(), error.what());
        return;
      }
    }
    const auto& q = transform.transform.rotation;
    const double xx = q.x * q.x, yy = q.y * q.y, zz = q.z * q.z;
    const double xy = q.x * q.y, xz = q.x * q.z, yz = q.y * q.z, wx = q.w * q.x, wy = q.w * q.y, wz = q.w * q.z;
    const size_t input_count = input->data.size() / input->point_step;
    const size_t stride = std::max<size_t>(1, (input_count + static_cast<size_t>(max_points_) - 1) / static_cast<size_t>(max_points_));
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
      const float tx = static_cast<float>((1 - 2 * (yy + zz)) * x + 2 * (xy - wz) * y + 2 * (xz + wy) * z + transform.transform.translation.x);
      const float ty = static_cast<float>(2 * (xy + wz) * x + (1 - 2 * (xx + zz)) * y + 2 * (yz - wx) * z + transform.transform.translation.y);
      const float tz = static_cast<float>(2 * (xz - wy) * x + 2 * (yz + wx) * y + (1 - 2 * (xx + yy)) * z + transform.transform.translation.z);
      append_float(output.data, tx); append_float(output.data, ty); append_float(output.data, tz);
    }
    output.width = output.data.size() / output.point_step;
    output.row_step = output.width * output.point_step;
    publisher_->publish(output);
    published_sequence_ = sequence;
  }

  std::string input_topic_, livox_input_topic_, output_topic_, pose_topic_, map_frame_, base_frame_;
  int max_points_;
  double rate_hz_, pose_rate_hz_, max_range_m_;
  int max_input_age_ms_, max_pose_age_ms_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
  rclcpp::Subscription<livox_ros_driver2::msg::CustomMsg>::SharedPtr livox_subscription_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr publisher_;
  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr pose_publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::TimerBase::SharedPtr pose_timer_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  std::vector<std::string> base_frames_;
  std::unordered_set<std::string> base_frame_set_;
  std::mutex input_mutex_;
  sensor_msgs::msg::PointCloud2::ConstSharedPtr latest_input_;
  uint64_t input_sequence_{0}, published_sequence_{0};
};

}  // namespace aletheia_live_preprocessor

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<aletheia_live_preprocessor::LiveCloudPreprocessor>());
  rclcpp::shutdown();
  return 0;
}
