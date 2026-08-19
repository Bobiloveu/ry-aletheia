# Aletheia 实时点云预处理节点

该节点只在实时观测开启时使用：以深度 1 接收 `/livox/points` 最新帧，最多按 10 Hz 将标准 `float32 x/y/z` 点云转换到 `map` 坐标并均匀抽样为不超过 5000 点的 `/aletheia/live_points`。

它不使用 PCL、不缓存历史帧、不修改机器人导航数据。TF 不可用时会丢弃该帧而不是发布猜测坐标。

构建前需要小车 ROS2 环境具备 `ament_cmake`、`rclcpp`、`sensor_msgs`、`tf2_ros` 的 C++ 开发头文件：

```bash
source /opt/ry/install/setup.bash
colcon build --packages-select aletheia_live_preprocessor
```

运行示例：

```bash
ros2 run aletheia_live_preprocessor aletheia_live_cloud --ros-args \
  -p input_topic:=/livox/points -p output_topic:=/aletheia/live_points \
  -p rate_hz:=10.0 -p max_points:=5000
```
