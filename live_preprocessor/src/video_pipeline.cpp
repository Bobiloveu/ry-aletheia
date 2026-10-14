#include "video_pipeline.hpp"

#include <stdexcept>

namespace aletheia::video {

bool valid_target_budget(int width, int height, int fps) {
  return width > 0 && height > 0 && width <= static_cast<int>(kMaxDimension) && height <= static_cast<int>(kMaxDimension) &&
         width % 2 == 0 && height % 2 == 0 && static_cast<size_t>(width) * height <= kMaxPixels && fps > 0 && fps <= 120;
}

std::vector<std::string> pipeline_arguments(const PipelineConfig &config, const FrameLayout &source) {
  if (config.encoder != "vaapih264enc" && config.encoder != "nvh264enc") throw std::invalid_argument("不支持的视频硬件编码器");
  std::vector<std::string> arguments = {
      config.executable,
      "-q",
      "fdsrc",
      "fd=0",
      "do-timestamp=true",
      "blocksize=" + std::to_string(static_cast<size_t>(source.stride) * source.height),
      "!",
      "rawvideoparse",
      "format=" + source.format,
      "width=" + std::to_string(source.width),
      "height=" + std::to_string(source.height),
      "framerate=" + std::to_string(config.fps) + "/1",
      // Packed RGB widths need not be divisible by four. Explicit strides also
      // preserve legitimate source padding rather than repacking every frame.
      "plane-strides=<" + std::to_string(source.stride) + ">",
      "plane-offsets=<0>",
      "!",
  };
  if (config.encoder == "nvh264enc") {
    // A non-live fdsrc can preroll with PTS=NONE: NVENC then sends an
    // unshifted segment before its next frame establishes the min-PTS offset.
    // Wait for the live clock, then discard that initial complete DISCONT
    // frame. Keep these identities separate: dropping precedes syncing in a
    // single identity. Retain wall-clock timestamps across input gaps.
    arguments.insert(arguments.end(), {"identity", "sync=true", "signal-handoffs=false", "!",
                                       "identity", "drop-buffer-flags=discont", "signal-handoffs=false", "!"});
  }
  arguments.insert(arguments.end(), {
      "queue",
      "max-size-buffers=1",
      "max-size-bytes=0",
      "max-size-time=0",
      "leaky=downstream",
      "!",
      "videoconvert",
      "!",
      "videoscale",
      "!",
      "video/x-raw,format=NV12,width=" + std::to_string(config.width) + ",height=" + std::to_string(config.height) +
          ",pixel-aspect-ratio=1/1",
      "!",
      config.encoder,
      "bitrate=" + std::to_string(config.bitrate_kbps),
  });
  if (config.encoder == "vaapih264enc") {
    arguments.push_back("keyframe-period=" + std::to_string(config.fps));
  } else {
    arguments.insert(arguments.end(), {"preset=low-latency-hq", "rc-mode=cbr", "bframes=0", "zerolatency=true",
                                       "gop-size=" + std::to_string(config.fps), "!", "video/x-h264,profile=constrained-baseline"});
  }
  arguments.insert(arguments.end(),
                   {"!", "h264parse", "config-interval=-1", "!", "rtspclientsink", "location=" + config.rtsp_url, "protocols=tcp"});
  return arguments;
}

}  // namespace aletheia::video
