import 'package:aletheia_mobile/features/scenario_setup/domain/scenario_setup.dart';
import 'package:test/test.dart';

void main() {
  test('decodes a server-validated scenario source preview', () {
    final preview = ScenarioFilePreview.fromJson({
      'path': '/opt/ry/launch/robot.launch.py',
      'content': 'launch_description = []\n',
      'size': 24,
      'sha256': 'e3b0c44298fc1c149afbf4c8996fb924',
    });

    expect(preview.path, '/opt/ry/launch/robot.launch.py');
    expect(preview.content, contains('launch_description'));
    expect(preview.size, 24);
    expect(preview.sha256, startsWith('e3b0c442'));
  });
}
