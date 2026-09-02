import 'dart:math' as math;

import 'package:aletheia_visualization/aletheia_visualization.dart';
import 'package:flutter/widgets.dart';

import '../domain/live_map.dart';

/// Converts Flutter's single map layout/gesture model into the complete
/// projection Unity must draw.  No Unity render-target dimension participates
/// in this calculation: card, fullscreen and rotation are all new revisions
/// of the same Flutter-owned model.
class UnityViewport {
  const UnityViewport._();

  static VizViewport fromFlutter({
    required LiveMapMetadata map,
    required VizCameraState camera,
    required Size size,
    required int revision,
  }) {
    assert(size.width > 0 && size.height > 0);
    final baseViewMetres = math.max(map.worldWidth, map.worldHeight) * 1.1;
    final pixelsPerMetre =
        camera.scale * math.max(1.0, size.width) / baseViewMetres;
    return VizViewport(
      width: size.width,
      height: size.height,
      pixelsPerMetre: pixelsPerMetre,
      centerX: map.originX + map.worldWidth / 2 + camera.offset.dx,
      centerY: map.originY + map.worldHeight / 2 + camera.offset.dy,
      revision: revision,
    );
  }
}
