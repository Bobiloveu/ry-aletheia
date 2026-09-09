import 'dart:typed_data';

import 'costmap_frame.dart';

/// Converts the raw OccupancyGrid bytes into the bounded RGBA texture used by
/// both map renderers. ROS rows begin at the map's bottom edge; image rows
/// begin at the top, so this performs the required vertical flip once.
Uint8List costmapRgbaBytes(CostmapFrame frame) {
  final rgba = Uint8List(frame.width * frame.height * 4);
  for (var sourceY = 0; sourceY < frame.height; sourceY++) {
    final textureY = frame.height - sourceY - 1;
    for (var x = 0; x < frame.width; x++) {
      final sourceIndex = sourceY * frame.width + x;
      _writeCostmapColor(
        rgba,
        (textureY * frame.width + x) * 4,
        frame.cells[sourceIndex],
      );
    }
  }
  return rgba;
}

void _writeCostmapColor(Uint8List rgba, int offset, int cell) {
  if (cell == 0 || cell == 255) {
    return;
  }
  final (red, green, blue, alpha) = switch (cell) {
    >= 254 => (220, 38, 38, 192),
    253 => (249, 115, 22, 176),
    <= 126 => _interpolateCostmapColor(
      cell / 126,
      redStart: 56,
      greenStart: 189,
      blueStart: 248,
      alphaStart: 56,
      redEnd: 250,
      greenEnd: 204,
      blueEnd: 21,
      alphaEnd: 128,
    ),
    _ => _interpolateCostmapColor(
      (cell - 126) / 126,
      redStart: 250,
      greenStart: 204,
      blueStart: 21,
      alphaStart: 128,
      redEnd: 249,
      greenEnd: 115,
      blueEnd: 22,
      alphaEnd: 160,
    ),
  };
  rgba[offset] = red;
  rgba[offset + 1] = green;
  rgba[offset + 2] = blue;
  rgba[offset + 3] = alpha;
}

(int, int, int, int) _interpolateCostmapColor(
  double amount, {
  required int redStart,
  required int greenStart,
  required int blueStart,
  required int alphaStart,
  required int redEnd,
  required int greenEnd,
  required int blueEnd,
  required int alphaEnd,
}) => (
  (redStart + (redEnd - redStart) * amount).round(),
  (greenStart + (greenEnd - greenStart) * amount).round(),
  (blueStart + (blueEnd - blueStart) * amount).round(),
  (alphaStart + (alphaEnd - alphaStart) * amount).round(),
);
