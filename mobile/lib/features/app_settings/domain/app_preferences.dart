import 'package:flutter/material.dart';

/// Preferences that are owned by this handset, never by the robot console.
///
/// They deliberately stay separate from `/api/settings`: changing language or
/// display contrast must not alter the selected robot's runtime configuration.
enum AppLanguage {
  chinese(Locale('zh', 'CN')),
  english(Locale('en'));

  const AppLanguage(this.locale);

  final Locale locale;

  String get storageValue => name;

  static AppLanguage parse(String? raw) => AppLanguage.values.firstWhere(
    (value) => value.storageValue == raw,
    orElse: () => AppLanguage.chinese,
  );
}

/// Visual preferences belong to the handset. Daylight uses a separately
/// reviewed palette for bright work areas; it does not alter data or status
/// semantics on the robot HMI.
enum AppThemePreference {
  hmiDark,
  daylight,
  highContrastDark;

  String get storageValue => name;

  static AppThemePreference parse(String? raw) =>
      AppThemePreference.values.firstWhere(
        (value) => value.storageValue == raw,
        orElse: () => AppThemePreference.hmiDark,
      );
}

class AppPreferences {
  const AppPreferences({
    this.language = AppLanguage.chinese,
    this.theme = AppThemePreference.hmiDark,
  });

  final AppLanguage language;
  final AppThemePreference theme;

  AppPreferences copyWith({AppLanguage? language, AppThemePreference? theme}) =>
      AppPreferences(
        language: language ?? this.language,
        theme: theme ?? this.theme,
      );
}
