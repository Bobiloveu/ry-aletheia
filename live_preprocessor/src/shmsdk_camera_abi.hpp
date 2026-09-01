#pragma once

// Minimal ShmSDK 2.0 camera ABI adapter.
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

// These structures intentionally mirror the public ShmSDK 2.0 headers
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
  bool get_last(Handle handle, CamImage &image) const { return get_last_cam_image_(handle, image); }

 private:
  using InitMem = bool (*)(const std::string &);
  using OpenMem = Handle (*)(const std::string &);
  using CloseMem = void (*)(const std::string &);
  using GetLastCamImage = bool (*)(Handle, CamImage &);

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
      throw std::runtime_error(std::string("无法加载 ShmSDK 2.0 libfastshm.so；请安装 shmsdk_2.0_amd64.deb：") +
                               (error ? error : "未知错误"));
    }
    try {
      // libfastshm.so exports C++ API symbols.  The spellings below are the
      // public ShmSDK 2.0 ABI installed on the vehicle, not private symbols.
      init_mem_ = symbol<InitMem>("_Z7InitMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      open_mem_ = symbol<OpenMem>("_Z7OpenMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      close_mem_ = symbol<CloseMem>("_Z8CloseMemRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
      get_last_cam_image_ = symbol<GetLastCamImage>("_Z15GetLastCamImageiR8CamImage");
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
  GetLastCamImage get_last_cam_image_{nullptr};
};

}  // namespace aletheia::shmsdk
