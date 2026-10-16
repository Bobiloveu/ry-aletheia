#pragma once
#include <cmath>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <tf2/LinearMath/Transform.h>

namespace aletheia {
inline int64_t pose_stamp_ns(const builtin_interfaces::msg::Time& stamp) {
  return static_cast<int64_t>(stamp.sec) * 1000000000LL + stamp.nanosec;
}
inline bool valid_pose_transform(const geometry_msgs::msg::TransformStamped& value) {
  const auto& t=value.transform.translation;const auto& q=value.transform.rotation;
  const double norm=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
  return std::isfinite(t.x) && std::isfinite(t.y) && std::isfinite(t.z) &&
         std::isfinite(norm) && norm>1e-12;
}
inline tf2::Transform pose_transform(const geometry_msgs::msg::TransformStamped& value) {
  const auto& t=value.transform.translation;const auto& q=value.transform.rotation;
  tf2::Quaternion rotation(q.x,q.y,q.z,q.w);rotation.normalize();
  return tf2::Transform(rotation,tf2::Vector3(t.x,t.y,t.z));
}
// Lookup is read-only and returns nullopt for an unavailable edge. Choosing
// a fresh base edge must not depend on the slow map->odom common timestamp.
template<class Lookup>
std::optional<geometry_msgs::msg::TransformStamped> select_display_pose(
    Lookup lookup,const std::vector<std::string>& frames,const std::string& map,
    const std::string& odom,int64_t now_ns,int64_t max_age_ns) {
  const auto map_from_odom=lookup(map,odom);
  const auto fresh=[&](int64_t stamp) {
    return stamp==0 || (stamp<=now_ns ? now_ns-stamp<=max_age_ns : stamp-now_ns<=max_age_ns);
  };
  const auto measured=[&](geometry_msgs::msg::TransformStamped candidate,int64_t stamp) {
    // Static chains have no measurement time. Future-dated TF tolerance is
    // accepted within the age window but must not create a future wire clock.
    const auto output_stamp=stamp==0 || stamp>now_ns ? now_ns : stamp;
    candidate.header.stamp.sec=static_cast<int32_t>(output_stamp/1000000000LL);
    candidate.header.stamp.nanosec=static_cast<uint32_t>(output_stamp%1000000000LL);
    return candidate;
  };
  for(const auto& frame:frames) {
    const auto odom_from_base=lookup(odom,frame);
    if(map_from_odom && odom_from_base && valid_pose_transform(*map_from_odom) && valid_pose_transform(*odom_from_base)) {
      const auto body_stamp=pose_stamp_ns(odom_from_base->header.stamp);
      const auto map_stamp=pose_stamp_ns(map_from_odom->header.stamp);
      const auto stamp=body_stamp!=0 ? body_stamp : map_stamp;
      if(fresh(stamp) && (map_stamp<=now_ns || fresh(map_stamp))) {
        auto candidate=*odom_from_base;
        const auto transform=pose_transform(*map_from_odom)*pose_transform(*odom_from_base);
        auto& t=candidate.transform.translation;auto& q=candidate.transform.rotation;
        t.x=transform.getOrigin().x();t.y=transform.getOrigin().y();t.z=transform.getOrigin().z();
        q.x=transform.getRotation().x();q.y=transform.getRotation().y();q.z=transform.getRotation().z();q.w=transform.getRotation().w();
        candidate.header.frame_id=map;
        if(valid_pose_transform(candidate))return measured(candidate,stamp);
      }
    }
    // A lookup through odom can succeed at an old common timestamp while a
    // direct map->base edge has a fresh sample. Do not hide that fallback.
    auto direct=lookup(map,frame);
    if(direct && valid_pose_transform(*direct) && fresh(pose_stamp_ns(direct->header.stamp)))
      return measured(*direct,pose_stamp_ns(direct->header.stamp));
  }
  return std::nullopt;
}
}  // namespace aletheia
