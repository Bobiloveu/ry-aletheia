# Aletheia 实时点云预处理节点

该节点只在实时观测开启时使用：以深度 1、best-effort 接收导航实际使用的 `/collision_voxel_layer/points` 最新帧，最多按 10 Hz 将标准 `float32 x/y/z` 点云投影到 `map` 坐标并均匀抽样为不超过 3000 点。主话题连续 500ms 未到达时，才回退读取 `/livox/lidar` 的原生 `livox_ros_driver2/CustomMsg`；两路不会混合。

预处理结果不会再发布 ROS hidden topic。点云、位姿和局部代价地图各自隔离运行：点云与位姿写入独立最新数据槽，局部代价地图的 ROS callback 只覆盖最新 `OccupancyGrid` 槽；其 TF 投影、二进制编码和 UDP 提交均在专用 worker 中完成。三者都由后台线程经回环 UDP 发送给 Aletheia 专用遥测网关；网关只组装最新完整帧并通过独立 Binary WebSocket 交给浏览器。此链路没有 ACK、重传、历史队列或通用 ROS-Web Bridge，网络抖动时会直接恢复到最新数据。

局部代价地图默认只供 PC 实时观测：它可靠、TRANSIENT_LOCAL 地订阅 `/local_costmap/costmap`，接受最多 65,535 个 cell。每一帧必须在默认 5 秒时效内，并按 `header.stamp` 查询 `map ← header.frame_id` 后将 `info.origin` 合成为 map 坐标系中的栅格原点；工具晚启动时收到的旧锁存图会明确丢弃，不能因“刚收到”而使用最新 TF 猜测其位置。唯一受限例外是新鲜的 `odom` 栅格在精确时间查询失败时：仅当最新 `map ← odom` 经完整 3D 位移和四元数校验后仍为单位变换，才允许无损使用该单位变换；非单位、其它 source frame 或查询失败一律跳过，不能假定 `odom == map`。发送载荷为 20-byte map-origin metadata 与原始 cell，单个 UDP payload 最多 1152 Byte；低频 costmap 源不会被预处理器人为放大为高频发布。

它不使用 PCL、不缓存历史帧、不修改机器人导航数据。TF 不可用时会丢弃该帧而不是发布猜测坐标。

构建前需要小车 ROS2 环境具备 `ament_cmake`、`rclcpp`、`sensor_msgs`、`tf2_ros` 的 C++ 开发头文件：

```bash
source /opt/ry/install/setup.bash
colcon build --packages-select aletheia_live_preprocessor
```

运行示例：

```bash
ros2 run aletheia_live_preprocessor aletheia_live_cloud --ros-args \
  -p input_topic:=/collision_voxel_layer/points \
  -p rate_hz:=10.0 -p max_points:=3000 -p telemetry_udp_port:=8769
```
