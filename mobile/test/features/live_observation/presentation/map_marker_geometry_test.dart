import 'package:aletheia_mobile/features/live_observation/presentation/map_marker_geometry.dart';
import 'package:test/test.dart';

void main() {
  test('scales every vehicle marker detail with the physical footprint', () {
    final overview = VehicleMarkerGeometry.fromSize(width: 10, length: 15);
    final closeUp = VehicleMarkerGeometry.fromSize(width: 40, length: 60);

    expect(closeUp.bodyCornerRadius, overview.bodyCornerRadius * 4);
    expect(closeUp.edge, overview.edge * 4);
    expect(closeUp.innerCornerRadius, overview.innerCornerRadius * 4);
    expect(closeUp.panelCornerRadius, overview.panelCornerRadius * 4);
    expect(closeUp.panelStrokeWidth, overview.panelStrokeWidth * 4);
    expect(closeUp.dialRadius, overview.dialRadius * 4);
    expect(closeUp.dialRingStrokeWidth, overview.dialRingStrokeWidth * 4);
    expect(closeUp.lightWidth, overview.lightWidth * 4);
    expect(closeUp.sensorRadius, overview.sensorRadius * 4);
  });
}
