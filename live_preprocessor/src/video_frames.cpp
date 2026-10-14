#include "video_frames.hpp"

#include <jpeglib.h>

#include <algorithm>
#include <cctype>
#include <csetjmp>
#include <cstdio>
#include <limits>

namespace aletheia::video {
namespace {

struct JpegError {
  jpeg_error_mgr base{};
  jmp_buf jump;
  char message[JMSG_LENGTH_MAX]{};
};

void jpeg_fail(j_common_ptr info) {
  auto *error = reinterpret_cast<JpegError *>(info->err);
  (*info->err->format_message)(info, error->message);
  longjmp(error->jump, 1);
}

void jpeg_warning(j_common_ptr info, int level) {
  // Truncated JPEGs otherwise succeed by inserting an artificial EOI marker.
  if (level < 0) jpeg_fail(info);
}

bool valid_dimensions(uint32_t width, uint32_t height) {
  return width > 0 && height > 0 && width <= kMaxDimension && height <= kMaxDimension && static_cast<size_t>(width) * height <= kMaxPixels;
}

bool decode_jpeg(const FrameView &source, PreparedFrame &output, std::string &error, bool *identified = nullptr) {
  // Heap state survives libjpeg's longjmp; no C++ object is constructed across
  // that jump. The caller's output vector is cleaned normally on error.
  auto decompress = std::make_unique<jpeg_decompress_struct>();
  auto handler = std::make_unique<JpegError>();
  decompress->err = jpeg_std_error(&handler->base);
  handler->base.error_exit = jpeg_fail;
  handler->base.emit_message = jpeg_warning;
  if (identified) *identified = false;
  if (setjmp(handler->jump)) {
    jpeg_destroy_decompress(decompress.get());
    output.decoded.clear();
    error = std::string("JPEG 解码失败：") + handler->message;
    return false;
  }
  jpeg_create_decompress(decompress.get());
  jpeg_mem_src(decompress.get(), source.bytes, static_cast<unsigned long>(source.byte_count));
  jpeg_read_header(decompress.get(), TRUE);
  if (identified) *identified = true;
  // Check header BEFORE jpeg_start_decompress can allocate large work buffers.
  if (!valid_dimensions(decompress->image_width, decompress->image_height)) {
    jpeg_destroy_decompress(decompress.get());
    error = "JPEG 实际尺寸超过视频输入上限";
    return false;
  }
  decompress->out_color_space = JCS_RGB;
  jpeg_start_decompress(decompress.get());
  if (decompress->output_components != 3) {
    jpeg_destroy_decompress(decompress.get());
    error = "JPEG 无法解码为 RGB";
    return false;
  }
  output.layout = {decompress->output_width, decompress->output_height, decompress->output_width * 3, "rgb"};
  output.decoded.resize(static_cast<size_t>(output.layout.stride) * output.layout.height);
  while (decompress->output_scanline < decompress->output_height) {
    JSAMPROW row = output.decoded.data() + static_cast<size_t>(decompress->output_scanline) * output.layout.stride;
    jpeg_read_scanlines(decompress.get(), &row, 1);
  }
  jpeg_finish_decompress(decompress.get());
  jpeg_destroy_decompress(decompress.get());
  return true;
}

}  // namespace

bool prepare_frame(const FrameView &source, PreparedFrame &output, std::string &error) {
  output.borrowed = nullptr;
  output.byte_count = 0;
  output.decoded.clear();
  error.clear();
  if (!source.bytes || source.byte_count == 0 || source.byte_count > kMaxFrameBytes) {
    error = "图像数据为空或超过视频输入上限";
    return false;
  }
  std::string encoding(source.encoding);
  std::transform(encoding.begin(), encoding.end(), encoding.begin(), [](unsigned char byte) { return std::tolower(byte); });
  const bool jpeg_content = source.byte_count >= 3 && source.bytes[0] == 0xff && source.bytes[1] == 0xd8 && source.bytes[2] == 0xff;
  if (encoding == "jpeg" || encoding == "jpg" || encoding == "mjpeg" || encoding == "mjpg") {
    return decode_jpeg(source, output, error);
  }
  if (jpeg_content) {
    bool identified = false;
    if (decode_jpeg(source, output, error, &identified)) return true;
    // Raw pixel values can start FF D8 FF. Override raw metadata only after
    // libjpeg identifies a real header; damaged JPEG scans remain errors.
    if (identified) return false;
    error.clear();
  }
  if (!valid_dimensions(source.width, source.height)) {
    error = "原始图像尺寸无效或超过视频输入上限";
    return false;
  }
  uint32_t bpp = 0;
  std::string format;
  if (encoding == "rgb8" || encoding == "rgb24") {
    format = "rgb";
    bpp = 3;
  } else if (encoding == "bgr8" || encoding == "bgr24") {
    format = "bgr";
    bpp = 3;
  } else if (encoding == "mono8" || encoding == "8uc1") {
    format = "gray8";
    bpp = 1;
  } else if (encoding == "rgba8" || encoding == "rgba") {
    format = "rgba";
    bpp = 4;
  } else if (encoding == "bgra8" || encoding == "bgra") {
    format = "bgra";
    bpp = 4;
  } else if (encoding == "yuyv" || encoding == "yuy2" || encoding == "yuyv422" || encoding == "yuv422_yuy2") {
    format = "yuy2";
    bpp = 2;
  } else if (encoding == "uyvy" || encoding == "uyvy422" || encoding == "yuv422") {
    format = "uyvy";
    bpp = 2;
  } else {
    error = "相机编码不支持：" + encoding;
    return false;
  }
  if (bpp == 2 && source.width % 2) {
    error = "YUV422 图像宽度必须是偶数";
    return false;
  }
  const uint32_t minimum_stride = source.width * bpp;
  const uint32_t stride = source.stride ? source.stride : minimum_stride;
  const size_t expected = static_cast<size_t>(stride) * source.height;
  if (stride < minimum_stride || expected > kMaxFrameBytes || expected != source.byte_count) {
    error = "原始图像 stride 或数据长度不匹配";
    return false;
  }
  output.layout = {source.width, source.height, stride, std::move(format)};
  output.borrowed = source.bytes;
  output.byte_count = source.byte_count;
  return true;
}

}  // namespace aletheia::video
