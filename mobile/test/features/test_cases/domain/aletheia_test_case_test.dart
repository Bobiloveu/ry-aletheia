import 'package:aletheia_mobile/features/test_cases/domain/aletheia_test_case.dart';
import 'package:test/test.dart';

void main() {
  test('decodes aliases, location parameters and management metadata', () {
    final testCase = AletheiaTestCase.fromJson({
      'id': '社区_1_2_3_4.json',
      'filename': '社区_1_2_3_4.json',
      'name': '社区 · 1栋2单元 · 3层4室',
      'alias': '电梯回环',
      'parameters': {
        'community': '社区',
        'building': 1,
        'unit': 2,
        'floor': 3,
        'door': 4,
      },
      'management': {
        'lifecycle': 'released',
        'version': '1.2.0',
        'summary': '验证电梯回环。',
        'tags': ['电梯', '回环'],
      },
    });

    expect(testCase.displayName, '电梯回环');
    expect(testCase.parameters.locationLabel, '社区 · 1栋 · 2单元 · 3层 · 4室');
    expect(testCase.management.tags, ['电梯', '回环']);
  });
}
