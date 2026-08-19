cmake_minimum_required(VERSION 3.16)
project(aletheia_live_preprocessor)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(livox_ros_driver2 REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(aletheia_live_cloud src/live_cloud_preprocessor.cpp)
target_compile_features(aletheia_live_cloud PUBLIC cxx_std_17)
ament_target_dependencies(aletheia_live_cloud
  geometry_msgs livox_ros_driver2 rclcpp sensor_msgs tf2 tf2_ros)

install(TARGETS aletheia_live_cloud DESTINATION lib/${PROJECT_NAME})
ament_package()
