#include "pose_selection.hpp"
#include <tf2/buffer_core.h>
#include <iostream>
using geometry_msgs::msg::TransformStamped;
TransformStamped edge(const char* parent,const char* child,int sec,double x) {
  TransformStamped t;t.header.frame_id=parent;t.child_frame_id=child;t.header.stamp.sec=sec;
  t.transform.translation.x=x;t.transform.rotation.w=1;return t;
}
std::optional<TransformStamped> select(tf2::BufferCore& buffer) {
  return aletheia::select_display_pose([&](const std::string& target,const std::string& source)->std::optional<TransformStamped>{
    try{return buffer.lookupTransform(target,source,tf2::TimePointZero);}catch(const tf2::TransformException&){return std::nullopt;}
  },{"base_link"},"map","odom",200000000000LL,250000000LL);
}
int main(){
  int failures=0;
  auto check=[&](bool condition,const char* description){if(!condition){std::cerr<<description<<"\n";++failures;}};
  tf2::BufferCore future;
  auto future_edge=edge("map","base_link",200,3);future_edge.header.stamp.nanosec=100000000;
  future.setTransform(future_edge,"test",false);
  auto selected=select(future);
  check(selected && aletheia::pose_stamp_ns(selected->header.stamp)==200000000000LL,
        "bounded future transform must be displayed with timestamp clamped to now");
  future_edge.header.stamp.sec=201;future.setTransform(future_edge,"test",false);
  check(!select(future),"clearly future transform must be rejected");
  tf2::BufferCore branch;
  branch.setTransform(edge("map","odom",199,5),"test",false);
  branch.setTransform(edge("map","base_link",198,2),"test",false);
  branch.setTransform(edge("map","base_link",200,4),"test",false);
  selected=select(branch);
  check(selected && selected->transform.translation.x==4 && selected->header.stamp.sec==200,
        "stale indirect candidate must not hide fresh direct candidate");
  tf2::BufferCore static_body;
  static_body.setTransform(edge("map","odom",100,5),"test",false);
  static_body.setTransform(edge("odom","base_link",0,1),"test",true);
  check(!select(static_body),"static body must not refresh an expired dynamic map edge");
  static_body.setTransform(edge("map","odom",200,6),"test",false);
  selected=select(static_body);
  check(selected && selected->transform.translation.x==7 && selected->header.stamp.sec==200,
        "static body uses the fresh dynamic map measurement");
  tf2::BufferCore all_static;
  all_static.setTransform(edge("map","odom",0,5),"test",true);
  all_static.setTransform(edge("odom","base_link",0,1),"test",true);
  selected=select(all_static);
  check(selected && selected->transform.translation.x==6 && selected->header.stamp.sec==200,
        "all-static chain remains valid");
  if(failures)return 10;
  tf2::BufferCore buffer;
  buffer.setTransform(edge("map","odom",0,5),"test",true);
  buffer.setTransform(edge("odom","base_footprint",100,1),"test",false);
  buffer.setTransform(edge("odom","base_link",200,9),"test",false);
  auto lookup=[&](const std::string& target,const std::string& source)->std::optional<TransformStamped>{
    try{return buffer.lookupTransform(target,source,tf2::TimePointZero);}catch(const tf2::TransformException&){return std::nullopt;}
  };
  auto pose=aletheia::select_display_pose(lookup,{"base_footprint","base_link"},"map","odom",200000000000LL,250000000LL);
  if(!pose || pose->child_frame_id!="base_link" || pose->transform.translation.x!=14 || pose->header.stamp.sec!=200) return 1;
  if(aletheia::select_display_pose(lookup,{"base_footprint","base_link"},"map","odom",201000000000LL,250000000LL)) return 2;
  tf2::BufferCore low_rate;
  low_rate.setTransform(edge("map","odom",100,5),"test",false);
  low_rate.setTransform(edge("odom","base_link",200,9),"test",false);
  auto lookup2=[&](const std::string& target,const std::string& source)->std::optional<TransformStamped>{
    try{return low_rate.lookupTransform(target,source,tf2::TimePointZero);}catch(const tf2::TransformException&){return std::nullopt;}
  };
  pose=aletheia::select_display_pose(lookup2,{"base_link"},"map","odom",200000000000LL,250000000LL);
  if(!pose || pose->transform.translation.x!=14) return 3;
  tf2::BufferCore direct;direct.setTransform(edge("map","base_link",200,3),"test",false);
  auto lookup3=[&](const std::string& target,const std::string& source)->std::optional<TransformStamped>{
    try{return direct.lookupTransform(target,source,tf2::TimePointZero);}catch(const tf2::TransformException&){return std::nullopt;}
  };
  pose=aletheia::select_display_pose(lookup3,{"base_link"},"map","odom",200000000000LL,250000000LL);
  if(!pose || pose->transform.translation.x!=3) return 4;
  std::cout<<"pose selection: stale preferred frame, low-rate map edge, expiry and direct-frame fallback passed\n";
}
