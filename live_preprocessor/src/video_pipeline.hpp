#pragma once
#include <string>
#include <vector>

#include "video_frames.hpp"

namespace aletheia::video {
struct PipelineConfig {
  std::string executable;
  std::string encoder;
  std::string rtsp_url;
  int width{}, height{}, fps{}, bitrate_kbps{};
  std::string nvenc_rate_control{"cbr"};
};
std::vector<std::string> pipeline_arguments(const PipelineConfig &config, const FrameLayout &source);
bool valid_target_budget(int width, int height, int fps);
}  // namespace aletheia::video
