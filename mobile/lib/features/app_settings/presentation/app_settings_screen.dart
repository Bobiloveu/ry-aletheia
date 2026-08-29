import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../application/app_preferences_controller.dart';
import '../domain/app_preferences.dart';
import 'app_update_screen.dart';
import 'feedback_screen.dart';

/// Handset-only settings. Robot runtime configuration intentionally remains
/// under Tools > Runtime settings and is not mixed into this screen.
class AppSettingsScreen extends ConsumerWidget {
  const AppSettingsScreen({this.embedded = false, super.key});

  static const routePath = '/settings';

  /// True when this page is hosted by the primary app shell, whose app bar
  /// already supplies the page title. Keeping this explicit avoids a second
  /// title while retaining a usable standalone widget for tests and previews.
  final bool embedded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final preferences = ref.watch(appPreferencesControllerProvider);
    final english = preferences.language == AppLanguage.english;
    final copy = _SettingsCopy(english: english);

    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 680),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (!embedded) ...[
                  Text(
                    copy.title,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 6),
                ],
                Text(
                  copy.subtitle,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                _SettingsSection(
                  label: copy.appearance,
                  children: [
                    _SettingsRow(
                      icon: Icons.language_rounded,
                      title: copy.language,
                      value: _languageLabel(preferences.language, english),
                      onTap: () => _chooseLanguage(context, ref, copy),
                    ),
                    const Divider(height: 1),
                    _SettingsRow(
                      icon: Icons.contrast_rounded,
                      title: copy.theme,
                      value: _themeLabel(preferences.theme, english),
                      onTap: () => _chooseTheme(context, ref, copy),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                _SettingsSection(
                  label: copy.about,
                  children: [
                    _SettingsRow(
                      icon: Icons.info_outline_rounded,
                      title: copy.version,
                      value:
                          '${copy.appName} ${AppUpdateScreen.buildName} '
                          '(${AppUpdateScreen.buildNumber})',
                      onTap: null,
                    ),
                    const Divider(height: 1),
                    _SettingsRow(
                      icon: Icons.system_update_alt_rounded,
                      title: copy.checkUpdates,
                      value: copy.checkUpdatesDetail,
                      onTap: () => context.go(AppUpdateScreen.routePath),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                _SettingsSection(
                  label: copy.help,
                  children: [
                    _SettingsRow(
                      icon: Icons.bug_report_outlined,
                      title: copy.feedback,
                      value: copy.feedbackDetail,
                      onTap: () => context.go(AppFeedbackScreen.routePath),
                    ),
                  ],
                ),
                SizedBox(height: 18),
                Text(
                  copy.note,
                  style: TextStyle(
                    color: AletheiaTheme.textTertiary,
                    fontSize: 12,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _chooseLanguage(
    BuildContext context,
    WidgetRef ref,
    _SettingsCopy copy,
  ) async {
    final value = await showModalBottomSheet<AppLanguage>(
      context: context,
      showDragHandle: true,
      builder: (context) => _ChoiceSheet<AppLanguage>(
        title: copy.language,
        options: [
          _ChoiceOption(AppLanguage.chinese, '简体中文', 'Chinese (Simplified)'),
          _ChoiceOption(AppLanguage.english, 'English', 'English'),
        ],
        selected: ref.read(appPreferencesControllerProvider).language,
      ),
    );
    if (value != null) {
      await ref
          .read(appPreferencesControllerProvider.notifier)
          .setLanguage(value);
    }
  }

  Future<void> _chooseTheme(
    BuildContext context,
    WidgetRef ref,
    _SettingsCopy copy,
  ) async {
    final value = await showModalBottomSheet<AppThemePreference>(
      context: context,
      showDragHandle: true,
      builder: (context) => _ChoiceSheet<AppThemePreference>(
        title: copy.theme,
        options: [
          _ChoiceOption(
            AppThemePreference.hmiDark,
            copy.hmiDark,
            copy.hmiDarkDetail,
          ),
          _ChoiceOption(
            AppThemePreference.daylight,
            copy.daylight,
            copy.daylightDetail,
          ),
          _ChoiceOption(
            AppThemePreference.highContrastDark,
            copy.highContrast,
            copy.highContrastDetail,
          ),
        ],
        selected: ref.read(appPreferencesControllerProvider).theme,
      ),
    );
    if (value != null) {
      await ref.read(appPreferencesControllerProvider.notifier).setTheme(value);
    }
  }

  static String _languageLabel(AppLanguage value, bool english) =>
      switch (value) {
        AppLanguage.chinese => english ? 'Chinese (Simplified)' : '简体中文',
        AppLanguage.english => 'English',
      };

  static String _themeLabel(AppThemePreference value, bool english) =>
      switch (value) {
        AppThemePreference.hmiDark => english ? 'HMI dark' : 'HMI 深色',
        AppThemePreference.daylight => english ? 'Daylight' : '日间模式',
        AppThemePreference.highContrastDark =>
          english ? 'High contrast dark' : '高对比深色',
      };
}

class _SettingsSection extends StatelessWidget {
  const _SettingsSection({required this.label, required this.children});
  final String label;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(
        padding: EdgeInsets.only(left: 4, bottom: 8),
        child: Text(
          label.toUpperCase(),
          style: TextStyle(
            color: AletheiaTheme.textTertiary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: .5,
          ),
        ),
      ),
      DecoratedBox(
        decoration: BoxDecoration(
          color: AletheiaTheme.surface,
          border: Border.all(color: AletheiaTheme.border),
          borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        ),
        child: Column(children: children),
      ),
    ],
  );
}

class _SettingsRow extends StatelessWidget {
  const _SettingsRow({
    required this.icon,
    required this.title,
    required this.value,
    required this.onTap,
  });
  final IconData icon;
  final String title;
  final String value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: 64),
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Icon(icon, color: AletheiaTheme.cyan, size: 21),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleMedium),
                    SizedBox(height: 3),
                    Text(value, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
              if (onTap != null)
                Icon(
                  Icons.chevron_right_rounded,
                  color: AletheiaTheme.textTertiary,
                ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _ChoiceSheet<T> extends StatelessWidget {
  const _ChoiceSheet({
    required this.title,
    required this.options,
    required this.selected,
  });
  final String title;
  final List<_ChoiceOption<T>> options;
  final T selected;

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 14),
          RadioGroup<T>(
            groupValue: selected,
            onChanged: (value) => Navigator.pop(context, value),
            child: Column(
              children: [
                for (final option in options) ...[
                  RadioListTile<T>(
                    value: option.value,
                    contentPadding: EdgeInsets.zero,
                    title: Text(option.title),
                    subtitle: Text(option.detail),
                  ),
                  if (option != options.last) const Divider(height: 1),
                ],
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _ChoiceOption<T> {
  const _ChoiceOption(this.value, this.title, this.detail);
  final T value;
  final String title;
  final String detail;
}

class _SettingsCopy {
  const _SettingsCopy({required this.english});
  final bool english;

  String get title => english ? 'App settings' : '应用设置';
  String get subtitle => english
      ? 'Preferences on this device. Robot runtime settings stay separate.'
      : '仅影响本机使用体验，不会改动机器人运行配置。';
  String get appearance => english ? 'Appearance' : '外观';
  String get language => english ? 'Language' : '语言';
  String get theme => english ? 'Theme' : '主题';
  String get about => english ? 'About' : '关于';
  String get appName => 'Aletheia';
  String get version => english ? 'Version' : '版本信息';
  String get checkUpdates => english ? 'Check for updates' : '检查更新';
  String get checkUpdatesDetail => english
      ? 'Check whether a newer app release is available.'
      : '检查是否有可用的新版 App。';
  String get help => english ? 'Help' : '帮助与反馈';
  String get feedback => english ? 'Report a problem' : '问题反馈';
  String get feedbackDetail => english
      ? 'Describe a problem or suggestion, then choose what to attach.'
      : '填写问题或建议，并选择要附加的截图和 App 诊断摘要。';
  String get hmiDark => english ? 'HMI dark' : 'HMI 深色';
  String get hmiDarkDetail =>
      english ? 'The standard operational display.' : '标准的专业 HMI 显示。';
  String get daylight => english ? 'Daylight' : '日间模式';
  String get daylightDetail => english
      ? 'A low-glare light palette for bright work areas.'
      : '适合明亮现场的低反光浅色配色。';
  String get highContrast => english ? 'High contrast dark' : '高对比深色';
  String get highContrastDetail => english
      ? 'Stronger text and control contrast for bright environments.'
      : '提升文字与控件对比度，适合明亮现场环境。';
  String get note => english
      ? 'Language coverage is being expanded screen by screen. Live robot data and safety boundaries are unchanged.'
      : '英文文案将逐页完善；实时机器人数据与安全边界不受这些本机偏好影响。';
}
