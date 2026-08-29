import 'package:shared_preferences/shared_preferences.dart';

import '../domain/app_preferences.dart';

class AppPreferencesStore {
  static const _languageKey = 'app_language';
  static const _themeKey = 'app_theme';

  Future<AppPreferences> read() async {
    final preferences = await SharedPreferences.getInstance();
    return AppPreferences(
      language: AppLanguage.parse(preferences.getString(_languageKey)),
      theme: AppThemePreference.parse(preferences.getString(_themeKey)),
    );
  }

  Future<void> write(AppPreferences value) async {
    final preferences = await SharedPreferences.getInstance();
    await Future.wait([
      preferences.setString(_languageKey, value.language.storageValue),
      preferences.setString(_themeKey, value.theme.storageValue),
    ]);
  }
}
