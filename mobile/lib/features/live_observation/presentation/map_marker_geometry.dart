import 'dart:math' as math;

/// Physical geometry for the map vehicle marker.
///
/// Every value is derived from [width] and [length]. There are intentionally
/// no pixel floors: the map transform is the only authority on the marker's
/// final display size, so zooming changes the whole design uniformly.
class VehicleMarkerGeometry {
  const VehicleMarkerGeometry._({
    required this.bodyCornerRadius,
    required this.edge,
    required this.innerCornerRadius,
    required this.panelCornerRadius,
    required this.panelStrokeWidth,
    required this.dialRadius,
    required this.dialRingStrokeWidth,
    required this.lightWidth,
    required this.sensorRadius,
  });

  factory VehicleMarkerGeometry.fromSize({
    required double width,
    required double length,
  }) {
    final bodyCornerRadius = math.min(width, length) * .19;
    final edge = width * .055;
    return VehicleMarkerGeometry._(
      bodyCornerRadius: bodyCornerRadius,
      edge: edge,
      innerCornerRadius: math.min(width, length) * .135,
      panelCornerRadius: width * .14,
      panelStrokeWidth: width * .028,
      dialRadius: math.min(width * .22, length * .155),
      dialRingStrokeWidth: width * .048,
      lightWidth: width * .085,
      sensorRadius: width * .035,
    );
  }

  final double bodyCornerRadius;
  final double edge;
  final double innerCornerRadius;
  final double panelCornerRadius;
  final double panelStrokeWidth;
  final double dialRadius;
  final double dialRingStrokeWidth;
  final double lightWidth;
  final double sensorRadius;
}
