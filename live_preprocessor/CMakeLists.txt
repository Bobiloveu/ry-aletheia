cmake_minimum_required(VERSION 3.16)
project(aletheia_live_preprocessor)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(livox_ros_driver2 REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(JPEG REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(aletheia_live_cloud src/live_cloud_preprocessor.cpp)
target_compile_features(aletheia_live_cloud PUBLIC cxx_std_17)
ament_target_dependencies(aletheia_live_cloud
  geometry_msgs livox_ros_driver2 nav_msgs rclcpp sensor_msgs tf2 tf2_ros)

# 不链接系统 GStreamer：该 sidecar 仅通过受控私有 runtime 的 gst-launch
# 子进程写入原始帧，因此完整 DEB 不依赖目标车的开发包或媒体运行时。
add_executable(aletheia_video_ingest src/video_ingest.cpp)
target_compile_features(aletheia_video_ingest PUBLIC cxx_std_17)
ament_target_dependencies(aletheia_video_ingest rclcpp sensor_msgs)
target_link_libraries(aletheia_video_ingest JPEG::JPEG ${CMAKE_DL_LIBS})

install(TARGETS aletheia_live_cloud aletheia_video_ingest DESTINATION lib/${PROJECT_NAME})
ament_package()
