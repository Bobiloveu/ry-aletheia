import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:test/test.dart';

void main() {
  group('RobotEndpoint', () {
    test('normalizes an IPv4 address onto the fixed console port', () {
      final endpoint = RobotEndpoint.parse('192.168.1.20');

      expect(endpoint.displayAddress, '192.168.1.20:8087');
      expect(
        endpoint.apiUri('api/observation').toString(),
        'http://192.168.1.20:8087/api/observation',
      );
      expect(
        endpoint
            .apiUri('api/tool-logs', queryParameters: {'scope': 'errors'})
            .toString(),
        'http://192.168.1.20:8087/api/tool-logs?scope=errors',
      );
    });

    test('accepts HTTP URL and bracketed IPv6', () {
      expect(
        RobotEndpoint.parse('http://robot.local:8087/').displayAddress,
        'robot.local:8087',
      );
      expect(
        RobotEndpoint.parse('[fe80::42]').apiUri('api/observation').toString(),
        'http://[fe80::42]:8087/api/observation',
      );
    });

    test('rejects paths, non-HTTP schemes and a different console port', () {
      expect(
        () => RobotEndpoint.parse('https://robot.local'),
        throwsFormatException,
      );
      expect(
        () => RobotEndpoint.parse('robot.local:9999'),
        throwsFormatException,
      );
      expect(
        () => RobotEndpoint.parse('robot.local/api/observation'),
        throwsFormatException,
      );
    });
  });
}
