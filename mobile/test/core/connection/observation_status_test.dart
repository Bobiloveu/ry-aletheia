import 'package:aletheia_mobile/core/connection/observation_status.dart';
import 'package:test/test.dart';

void main() {
  test('decodes the observation fields exposed by the robot console', () {
    final status = ObservationStatus.fromJson({
      'enabled': true,
      'telemetry': {'online': true, 'detail': 'Binary WebSocket'},
      'preprocessor': {'available': true, 'managed': true},
      'active_map_id': '0123456789abcdef',
      'idle_stop_seconds': 45,
    });

    expect(status.enabledInConfiguration, isTrue);
    expect(status.telemetryOnline, isTrue);
    expect(status.preprocessorManaged, isTrue);
    expect(status.activeMapId, '0123456789abcdef');
    expect(status.idleStopSeconds, 45);
  });
}
