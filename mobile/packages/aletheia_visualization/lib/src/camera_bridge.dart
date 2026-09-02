import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';
import 'package:flutter/widgets.dart';

import 'visualization_controller.dart' show VizViewport;

typedef _CameraStageNative = Int64 Function(Pointer<_NativeCamera>);
typedef _CameraStageDart = int Function(Pointer<_NativeCamera>);

/// Process-local, latest-wins camera staging for an embedded Unity surface.
///
/// Touch input can arrive at 120 Hz. Routing every pan sample through a
/// MethodChannel then `UnitySendMessage` queues JSON parsing on UIKit and the
/// Unity main thread, so this tiny scalar bridge deliberately mirrors the
/// point-cloud bridge instead. Flutter writes the newest intent; Unity reads
/// at most one value per rendered frame.
class CameraBridge {
  CameraBridge._(this._stage, this._camera);

  final _CameraStageDart _stage;
  final Pointer<_NativeCamera> _camera;

  static CameraBridge? _instance;
  static bool _triedLoad = false;

  static CameraBridge? instanceOrNull() {
    if (_instance != null) return _instance;
    if (_triedLoad) return null;
    _triedLoad = true;
    final library = _openLibraryOrNull();
    if (library == null) return null;
    try {
      final stage = library
          .lookup<NativeFunction<_CameraStageNative>>('av_camera_stage')
          .asFunction<_CameraStageDart>();
      return _instance = CameraBridge._(stage, calloc<_NativeCamera>());
    } on ArgumentError {
      return null;
    }
  }

  static DynamicLibrary? _openLibraryOrNull() {
    try {
      if (Platform.isIOS || Platform.isMacOS) {
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

  /// Stages one complete camera intent. Invalid values are rejected before
  /// crossing the FFI boundary so a transient bad layout can never poison the
  /// Unity transform.
  bool stage({
    required int owner,
    required double scale,
    required Offset offset,
    required double orbitYaw,
    required double orbitPitch,
    required double distance,
    required Offset target,
    required VizViewport viewport,
  }) {
    if (owner < 0 ||
        !scale.isFinite ||
        scale <= 0 ||
        !offset.dx.isFinite ||
        !offset.dy.isFinite ||
        !orbitYaw.isFinite ||
        !orbitPitch.isFinite ||
        !distance.isFinite ||
        !target.dx.isFinite ||
        !target.dy.isFinite ||
        !viewport.isValid) {
      return false;
    }
    _camera.ref
      ..owner = owner
      ..scale = scale
      ..ox = offset.dx
      ..oy = offset.dy
      ..yaw = orbitYaw
      ..pitch = orbitPitch
      ..distance = distance
      ..tx = target.dx
      ..ty = target.dy
      ..viewportWidth = viewport.width
      ..viewportHeight = viewport.height
      ..pixelsPerMetre = viewport.pixelsPerMetre
      ..centerX = viewport.centerX
      ..centerY = viewport.centerY
      ..viewportRevision = viewport.revision;
    return _stage(_camera) > 0;
  }
}

final class _NativeCamera extends Struct {
  @Float()
  external double scale;
  @Float()
  external double ox;
  @Float()
  external double oy;
  @Float()
  external double yaw;
  @Float()
  external double pitch;
  @Float()
  external double distance;
  @Float()
  external double tx;
  @Float()
  external double ty;
  @Int64()
  external int owner;
  @Float()
  external double viewportWidth;
  @Float()
  external double viewportHeight;
  @Float()
  external double pixelsPerMetre;
  @Float()
  external double centerX;
  @Float()
  external double centerY;
  @Int64()
  external int viewportRevision;
}
