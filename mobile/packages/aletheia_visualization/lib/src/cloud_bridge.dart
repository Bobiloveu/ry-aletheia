import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

/// Point layout of a staged cloud frame. Mirrors `av_cloud_layout` in
/// `aletheia_viz_bridge.h`.
enum CloudLayout {
  xy(2),
  xyz(3);

  const CloudLayout(this.floatsPerPoint);
  final int floatsPerPoint;
}

typedef _StageNative = Int64 Function(Pointer<Float>, Int32, Int32);
typedef _StageDart = int Function(Pointer<Float>, int, int);
typedef _AgeNative = Int64 Function();
typedef _AgeDart = int Function();
typedef _ResetNative = Void Function();
typedef _ResetDart = void Function();

/// Thin FFI wrapper over the native `aletheia_viz_bridge` staging buffer.
///
/// This is the *only* path point-cloud data takes to Unity. It hands the
/// native side a pointer into a reused scratch buffer, filled from the packed
/// `Float32List` already produced by `CloudFrameDecoder` with a single bulk
/// copy and no per-point work. The native buffer keeps exactly one pending
/// frame (latest-wins); Unity copies it out on its render thread.
class CloudBridge {
  CloudBridge._(this._stage, this._age, this._reset, this._scratch);

  final _StageDart _stage;
  final _AgeDart _age;
  final _ResetDart _reset;

  /// Reused native scratch buffer, sized once for the 3D stress ceiling
  /// (`AV_MAX_FLOATS`) so the hot path never allocates.
  final Pointer<Float> _scratch;

  static const int _maxFloats = 262144 * 3;

  static CloudBridge? _instance;
  static bool _triedLoad = false;

  /// Returns the process-wide bridge, loading the native library on first use.
  /// Returns `null` when the native library is absent (a unit-test host, or a
  /// build made before the Unity module was wired in) — callers degrade.
  static CloudBridge? instanceOrNull() {
    if (_instance != null) return _instance;
    if (_triedLoad) return null;
    _triedLoad = true;
    final lib = _openLibraryOrNull();
    if (lib == null) return null;
    try {
      final stage = lib
          .lookup<NativeFunction<_StageNative>>('av_cloud_stage')
          .asFunction<_StageDart>();
      final age = lib
          .lookup<NativeFunction<_AgeNative>>('av_cloud_age_ms')
          .asFunction<_AgeDart>();
      final reset = lib
          .lookup<NativeFunction<_ResetNative>>('av_bridge_reset')
          .asFunction<_ResetDart>();
      final scratch = calloc<Float>(_maxFloats);
      return _instance = CloudBridge._(stage, age, reset, scratch);
    } on ArgumentError {
      return null;
    }
  }

  static DynamicLibrary? _openLibraryOrNull() {
    try {
      if (Platform.isIOS || Platform.isMacOS) {
        // iOS app executables do not expose a reliable dynamic lookup table
        // to sibling frameworks in release builds. The single bridge instead
        // lives in this already-loaded CocoaPods framework; Unity uses this
        // same @rpath image, so Flutter and Unity share one staging buffer.
        if (Platform.isIOS) {
          final runnerApp = File(Platform.resolvedExecutable).parent.path;
          return DynamicLibrary.open(
            '$runnerApp/Frameworks/aletheia_visualization.framework/'
            'aletheia_visualization',
          );
        }
        return DynamicLibrary.process();
      }
      if (Platform.isAndroid) {
        return DynamicLibrary.open('libaletheia_viz_bridge.so');
      }
    } on Object {
      return null;
    }
    return null;
  }

  /// Stages one decoded cloud frame. [packed] is the `Float32List` straight
  /// from `CloudFrameDecoder.decode` — not transformed here. Returns the
  /// assigned sequence number, or `-1` if rejected.
  int stage(Float32List packed, {CloudLayout layout = CloudLayout.xy}) {
    // AV_MAX_FLOATS is the storage capacity, not a permission to exceed the
    // documented AV_MAX_POINTS ceiling for XY frames.  Without this guard an
    // XY frame could contain 393,216 points, while Unity's GPU buffer has
    // room for 262,144.  That mismatch reaches GraphicsBuffer.SetData during
    // a live scan and can terminate the embedded renderer.
    if (packed.isEmpty ||
        packed.length > _maxFloats ||
        packed.length % layout.floatsPerPoint != 0 ||
        packed.length ~/ layout.floatsPerPoint > 262144) {
      return -1;
    }
    _scratch.asTypedList(packed.length).setAll(0, packed);
    return _stage(_scratch, packed.length, layout.floatsPerPoint);
  }

  /// Age in ms of the last staged frame, or `-1` if none.
  int ageMs() => _age();

  /// Clears native state so a re-created Unity instance never sees a stale
  /// frame. Call on engine unload.
  void reset() => _reset();
}
