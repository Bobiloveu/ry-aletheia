import 'package:aletheia_mobile/features/app_settings/domain/app_preferences.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('restores only supported local language and theme preferences', () {
    expect(AppLanguage.parse('english'), AppLanguage.english);
    expect(AppLanguage.parse('unknown'), AppLanguage.chinese);
    expect(
      AppThemePreference.parse('highContrastDark'),
      AppThemePreference.hmiDark,
    );
    expect(AppThemePreference.parse('daylight'), AppThemePreference.daylight);
    expect(AppThemePreference.parse('unexpected'), AppThemePreference.hmiDark);
  });
}
