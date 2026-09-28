#pragma once

// Minimal ShmSDK 2.8 camera ABI adapter.
//
// ShmSDK is installed and owned by the robot image stack.  The Aletheia
// sidecar deliberately opens only the documented camera channels and never
// starts or manages mempool.  Loading the shared library at runtime keeps the
// desktop build independent of the robot-only SDK while producing a precise
// diagnostic when the SDK is absent or incompatible on a vehicle.

#include <dlfcn.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace aletheia::shmsdk {

using Handle = int;

// ShmSDK 2.8's public retrieval mode and value parameter.  This definition is
// copied from the SDK's installed `shmdef.h` so the dynamically loaded public
// `GetCamImage` function receives its documented C++ ABI exactly.
enum getType {
  GET_AUTO = 0,
  GET_LAST,
  GET_CACHE,
  GET_MATCH,
};

struct getParm {
  getType iType{GET_AUTO};
  int64_t stamp_ms{};
  int64_t range_ms{};

  getParm(getType iGet = GET_AUTO, int64_t stamp = 0, int64_t range = 0)
      : iType(iGet), stamp_ms(stamp), range_ms(range) {}
};

// These structures intentionally mirror the public ShmSDK 2.8 headers
// (workdef.h).  They are used only as the documented C++ function ABI for the
// four camera channels below.
struct Header {
  uint32_t seq{};
  int64_t stamp{};
  std::string frame_id;
};

struct CamImage {
  Header header;
  int64_t timeStamp{};
  uint32_t height{};
  uint32_t width{};
  std::string encoding;
  uint8_t is_bigendian{};
  uint32_t step{};
  std::vector<uint8_t> data;
};

class CameraApi final {
 public:
  CameraApi() { load(); }
  CameraApi(const CameraApi &) = delete;
  CameraApi &operator=(const CameraApi &) = delete;

  ~CameraApi() {
    if (library_ != nullptr) dlclose(library_);
  }

  bool initialize() const {
    // This only attaches the caller to the already-running shared-memory
    // service.  It never configures or launches mempool.
    return init_mem_({});
  }

  Handle open(const std::string &channel) const { return open_mem_(channel); }
  void close(const std::string &channel) const { close_mem_(channel); }
  bool get_last(Handle handle, CamImage &image) const { return get_cam_image_(handle, image, getParm(GET_LAST, 0, 0)); }

 private:
  using InitMem = bool (*)(const std::string &);
  using OpenMem = Handle (*)(const std::string &);
  using CloseMem = void (*)(const std::string &);
  using GetCamImage = bool (*)(Handle, CamImage &, getParm);

  template <typename Function>
  Function symbol(const char *name) {
    dlerror();
    void *address = dlsym(library_, name);
    const char *error = dlerror();
    if (error != nullptr || address == nullptr) {
      throw std::runtime_error(std::string("ShmSDK 缺少必需接口 ") + name + "：" + (error ? error : "未知错误"));
    }
    return reinterpret_cast<Function>(address);
  }

  void load() {
    constexpr const char *kPreferredLibrary = "/usr/local/lib/libfastshm.so";
    library_ = dlopen(kPreferredLibrary, RTLD_NOW | RTLD_LOCAL);
    if (library_ == nullptr) library_ = dlopen("libfastshm.so", RTLD_NOW | RTLD_LOCAL);
    if (library_ == nullptr) {
      const char *error = dlerror();
      throw std::runtime_error(std::string("无法加载 ShmSDK 2.8 libfastshm.so；请安装 ry-shmsdk_2.8_amd64.deb：") +
                               (error ? error : "未知错误"));
    }
    try {
      // libfastshm.so exports C++ API symbols. The spellings below are the
      // public ShmSDK 2.8 ABI installed on the vehicle, not private symbols.
      init_mem_ = symbol<InitMem>("_Z7InitMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      open_mem_ = symbol<OpenMem>("_Z7OpenMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      close_mem_ = symbol<CloseMem>("_Z8CloseMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      get_cam_image_ = symbol<GetCamImage>("_Z11GetCamImageiR8CamImage7getParm");
    } catch (...) {
      dlclose(library_);
      library_ = nullptr;
      throw;
    }
  }

  void *library_{nullptr};
  InitMem init_mem_{nullptr};
  OpenMem open_mem_{nullptr};
  CloseMem close_mem_{nullptr};
  GetCamImage get_cam_image_{nullptr};
};

}  // namespace aletheia::shmsdk
