#include "video_frames.hpp"

#include <jpeglib.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

#include "video_pipeline.hpp"

using namespace aletheia::video;
#define REQUIRE(expr)                             \
  do {                                            \
    if (!(expr)) throw std::runtime_error(#expr); \
  } while (false)

std::vector<uint8_t> jpeg_fixture(unsigned width = 8, unsigned height = 6) {
  jpeg_compress_struct compressor{};
  jpeg_error_mgr error{};
  compressor.err = jpeg_std_error(&error);
  jpeg_create_compress(&compressor);
  unsigned char *buffer = nullptr;
  unsigned long length = 0;
  jpeg_mem_dest(&compressor, &buffer, &length);
  compressor.image_width = width;
  compressor.image_height = height;
  compressor.input_components = 3;
  compressor.in_color_space = JCS_RGB;
  jpeg_set_defaults(&compressor);
  jpeg_set_quality(&compressor, 95, TRUE);
  jpeg_start_compress(&compressor, TRUE);
  std::vector<uint8_t> row(width * 3);
  for (unsigned x = 0; x < width; ++x) {
    row[x * 3] = 235;
    row[x * 3 + 1] = 30;
    row[x * 3 + 2] = 12;
  }
  while (compressor.next_scanline < height) {
    JSAMPROW pointer = row.data();
    jpeg_write_scanlines(&compressor, &pointer, 1);
  }
  jpeg_finish_compress(&compressor);
  std::vector<uint8_t> result(buffer, buffer + length);
  free(buffer);
  jpeg_destroy_compress(&compressor);
  return result;
}

void raw_formats_preserve_bytes_and_padding() {
  const std::vector<std::pair<std::string, std::string>> formats = {
      {"rgb8", "rgb"},   {"RGB24", "rgb"},  {"bgr8", "bgr"},  {"bgr24", "bgr"}, {"mono8", "gray8"},
      {"rgba8", "rgba"}, {"bgra8", "bgra"}, {"yuyv", "yuy2"}, {"uyvy", "uyvy"},
  };
  std::vector<uint8_t> bytes(64, 0x37);
  for (const auto &entry : formats) {
    const unsigned bpp = entry.second == "gray8"                              ? 1
                         : (entry.second == "rgba" || entry.second == "bgra") ? 4
                         : (entry.second == "yuy2" || entry.second == "uyvy") ? 2
                                                                              : 3;
    const unsigned stride = 4 * bpp + 3;
    FrameView view{4, 2, stride, entry.first, bytes.data(), stride * 2};
    PreparedFrame frame;
    std::string error;
    REQUIRE(prepare_frame(view, frame, error));
    REQUIRE(frame.layout.format == entry.second);
    REQUIRE(frame.layout.width == 4 && frame.layout.height == 2 && frame.layout.stride == stride);
    REQUIRE(frame.data() == bytes.data());
    REQUIRE(frame.size() == stride * 2);
    REQUIRE(frame.decoded.empty());
  }
  // Tight 854-wide RGB is not GstVideo's default 4-byte-aligned stride.
  bytes.resize(854 * 2 * 3);
  PreparedFrame frame;
  std::string error;
  REQUIRE(prepare_frame({854, 2, 2562, "rgb24", bytes.data(), bytes.size()}, frame, error));
  REQUIRE(frame.layout.stride == 2562 && frame.data() == bytes.data());
}

void jpeg_content_overrides_metadata_and_is_bounded() {
  auto bytes = jpeg_fixture();
  for (const std::string encoding : {"jpeg", "JPG", "mjpeg", "rgb8", "", "wrong"}) {
    PreparedFrame frame;
    std::string error;
    REQUIRE(prepare_frame({640, 480, 0, encoding, bytes.data(), bytes.size()}, frame, error));
    REQUIRE(frame.layout.width == 8 && frame.layout.height == 6 && frame.layout.stride == 24);
    REQUIRE(frame.layout.format == "rgb" && frame.size() == 144);
    REQUIRE(frame.data()[0] > 200 && frame.data()[1] < 55 && frame.data()[2] < 35);
  }
  PreparedFrame frame;
  std::string error;
  auto truncated = bytes;
  truncated.resize(truncated.size() / 2);
  REQUIRE(!prepare_frame({8, 6, 24, "jpeg", truncated.data(), truncated.size()}, frame, error));
  auto too_wide = jpeg_fixture(8193, 1);
  REQUIRE(!prepare_frame({1, 1, 3, "jpeg", too_wide.data(), too_wide.size()}, frame, error));
}

void malformed_raw_is_rejected() {
  std::vector<uint8_t> bytes(48);
  PreparedFrame frame;
  std::string error;
  for (const FrameView view :
       {FrameView{0, 2, 12, "rgb8", bytes.data(), 24}, FrameView{4, 2, 11, "rgb8", bytes.data(), 22},
        FrameView{4, 2, 12, "rgb8", bytes.data(), 23}, FrameView{4, 2, 12, "rgb8", bytes.data(), 25},
        FrameView{3, 2, 6, "yuyv", bytes.data(), 12}, FrameView{4, 2, 12, "nv12", bytes.data(), 24},
        FrameView{0xffffffffU, 0xffffffffU, 12, "rgb8", bytes.data(), 24}, FrameView{4, 2, 12, "rgb8", nullptr, 24}}) {
    REQUIRE(!prepare_frame(view, frame, error));
    REQUIRE(!error.empty());
  }
}

void jpeg_signature_does_not_hide_valid_raw_pixels() {
  std::vector<uint8_t> bytes(24, 0x11);
  bytes[0] = 0xff;
  bytes[1] = 0xd8;
  bytes[2] = 0xff;
  PreparedFrame frame;
  std::string error;
  REQUIRE(prepare_frame({4, 2, 12, "rgb8", bytes.data(), bytes.size()}, frame, error));
  REQUIRE(frame.data() == bytes.data() && frame.decoded.empty());
  REQUIRE(error.empty());
  REQUIRE(!prepare_frame({4, 2, 12, "jpeg", bytes.data(), bytes.size()}, frame, error));

  // A valid JPEG header followed by damaged scan data must still be rejected,
  // even when misleading raw metadata happens to describe the byte length.
  auto truncated = jpeg_fixture();
  truncated.resize(truncated.size() - 2);
  REQUIRE(!prepare_frame({static_cast<uint32_t>(truncated.size()), 1, static_cast<uint32_t>(truncated.size()),
                          "mono8", truncated.data(), truncated.size()}, frame, error));
}

bool contains(const std::vector<std::string> &args, const std::string &needle) {
  return std::find(args.begin(), args.end(), needle) != args.end();
}

void pipeline_preserves_source_stride_and_target_budget() {
  REQUIRE(valid_target_budget(640, 480, 120));
  REQUIRE(!valid_target_budget(640, 480, 121));
  REQUIRE(!valid_target_budget(641, 480, 15));
  REQUIRE(!valid_target_budget(8192, 8192, 15));
  REQUIRE(valid_target_budget(4096, 4096, 15));
  PipelineConfig config{"/private/gst-launch", "vaapih264enc", "rtsp://127.0.0.1:8554/front", 640, 480, 15, 1200};
  FrameLayout layout{854, 480, 2562, "rgb"};
  auto args = pipeline_arguments(config, layout);
  REQUIRE(contains(args, "plane-strides=<2562>"));
  REQUIRE(contains(args, "width=854"));
  REQUIRE(contains(args, "video/x-raw,format=NV12,width=640,height=480,pixel-aspect-ratio=1/1"));
  REQUIRE(contains(args, "videoscale"));
  REQUIRE(contains(args, "max-size-buffers=1"));
  REQUIRE(contains(args, "vaapih264enc") && contains(args, "keyframe-period=15"));
  REQUIRE(contains(args, "bitrate=1200"));
  REQUIRE(contains(args, "framerate=15/1"));
  config.encoder = "nvh264enc";
  args = pipeline_arguments(config, layout);
  REQUIRE(contains(args, "nvh264enc") && !contains(args, "vaapih264enc"));
  REQUIRE(contains(args, "bframes=0") && contains(args, "zerolatency=true") && contains(args, "gop-size=15"));
  REQUIRE(contains(args, "video/x-h264,profile=constrained-baseline"));
  config.encoder = "unexpected";
  bool threw = false;
  try {
    pipeline_arguments(config, layout);
  } catch (const std::invalid_argument &) {
    threw = true;
  }
  REQUIRE(threw);
}

void nvenc_vbr_candidate_keeps_budget_and_low_latency() {
  PipelineConfig config{"/private/gst-launch", "nvh264enc", "rtsp://127.0.0.1:8554/front", 640, 480, 15, 1200};
  const FrameLayout layout{640, 480, 1920, "rgb"};
  REQUIRE(contains(pipeline_arguments(config, layout), "rc-mode=cbr"));
  config.nvenc_rate_control = "vbr";
  auto args = pipeline_arguments(config, layout);
  REQUIRE(contains(args, "rc-mode=vbr") && !contains(args, "rc-mode=cbr"));
  REQUIRE(contains(args, "bitrate=1200") && contains(args, "max-bitrate=1200"));
  REQUIRE(contains(args, "const-quality=23"));
  REQUIRE(contains(args, "framerate=15/1") && contains(args, "gop-size=15"));
  REQUIRE(contains(args, "bframes=0") && contains(args, "zerolatency=true"));
  REQUIRE(contains(args, "video/x-h264,profile=constrained-baseline"));
  REQUIRE(contains(args, "drop-buffer-flags=discont") && contains(args, "sync=true"));
  REQUIRE(std::count(args.begin(), args.end(), "queue") == 1);
  config.fps = 10; config.bitrate_kbps = 800;
  args = pipeline_arguments(config, layout);
  REQUIRE(contains(args, "max-bitrate=800") && contains(args, "framerate=10/1"));
  config.encoder = "vaapih264enc";
  args = pipeline_arguments(config, layout);
  REQUIRE(contains(args, "keyframe-period=10"));
  REQUIRE(!contains(args, "const-quality=23") && !contains(args, "rc-mode=vbr"));
  config.encoder = "nvh264enc"; config.nvenc_rate_control = "invalid";
  bool threw = false;
  try { pipeline_arguments(config, layout); } catch (const std::invalid_argument &) { threw = true; }
  REQUIRE(threw);
}

void latest_slot_decodes_only_at_output_budget() {
  LatestFrameSlot<std::shared_ptr<std::vector<uint8_t>>> slot;
  FrameBudget budget(15);
  auto jpeg = std::make_shared<std::vector<uint8_t>>(jpeg_fixture());
  PreparedFrame prepared;
  std::string error;
  int decoded = 0;
  const uint8_t *first_buffer = nullptr;
  for (int tick = 0; tick < 30; ++tick) {
    slot.publish(jpeg);
    const int64_t now = tick * 1'000'000LL / 30;
    if (budget.due(now)) {
      auto frame = slot.take();
      REQUIRE(frame != nullptr);
      REQUIRE(prepare_frame({8, 6, 24, "jpeg", frame->data(), frame->size()}, prepared, error));
      if (!first_buffer) first_buffer = prepared.data();
      REQUIRE(first_buffer == prepared.data());  // decoded allocation reused
      ++decoded;
      budget.consume(now);
    }
  }
  REQUIRE(decoded == 15);
  REQUIRE(slot.take() == jpeg);
  REQUIRE(slot.take() == nullptr);
  LatestFrameSlot<std::shared_ptr<int>> numbers;
  numbers.publish(std::make_shared<int>(1));
  numbers.publish(std::make_shared<int>(2));
  REQUIRE(*numbers.take() == 2);
  REQUIRE(numbers.take() == nullptr);
}

void nvenc_waits_for_live_clock_before_dropping_preroll_frame() {
  PipelineConfig config{"/private/gst-launch", "nvh264enc", "rtsp://127.0.0.1:8554/detection", 640, 480, 10, 800};
  const auto args = pipeline_arguments(config, {640, 480, 1920, "bgr"});
  REQUIRE(contains(args, "do-timestamp=true"));
  const std::vector<std::string> startup_barrier = {
      "identity", "sync=true", "signal-handoffs=false", "!",
      "identity", "drop-buffer-flags=discont", "signal-handoffs=false", "!", "queue"};
  REQUIRE(std::search(args.begin(), args.end(), startup_barrier.begin(), startup_barrier.end()) != args.end());
  REQUIRE(contains(args, "rawvideoparse") && contains(args, "framerate=10/1"));
  REQUIRE(contains(args, "plane-strides=<1920>") && contains(args, "bitrate=800"));
  REQUIRE(std::count(args.begin(), args.end(), "queue") == 1);
  REQUIRE(contains(args, "leaky=downstream"));
  config.encoder = "vaapih264enc";
  const auto vaapi = pipeline_arguments(config, {640, 480, 1920, "bgr"});
  REQUIRE(contains(vaapi, "do-timestamp=true"));
  REQUIRE(!contains(vaapi, "identity"));
}

int main() {
  try {
    raw_formats_preserve_bytes_and_padding();
    jpeg_content_overrides_metadata_and_is_bounded();
    malformed_raw_is_rejected();
    jpeg_signature_does_not_hide_valid_raw_pixels();
    pipeline_preserves_source_stride_and_target_budget();
    nvenc_waits_for_live_clock_before_dropping_preroll_frame();
    latest_slot_decodes_only_at_output_budget();
    nvenc_vbr_candidate_keeps_budget_and_low_latency();
    std::cout << "video frame/pipeline tests passed\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
