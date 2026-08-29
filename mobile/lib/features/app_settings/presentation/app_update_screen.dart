import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../application/app_preferences_controller.dart';
import '../domain/app_preferences.dart';

/// App-local update entry point.
///
/// It deliberately has no connection to the robot's offline upgrade files or
/// runtime services. A reviewed app-distribution client can replace the local
/// development result later without changing the Settings navigation.
class AppUpdateScreen extends ConsumerStatefulWidget {
  const AppUpdateScreen({this.initialHasChecked = false, super.key});

  static const routePath = '/settings/update';
  static const buildName = String.fromEnvironment(
    'FLUTTER_BUILD_NAME',
    defaultValue: '1.0.0',
  );
  static const buildNumber = String.fromEnvironment(
    'FLUTTER_BUILD_NUMBER',
    defaultValue: '1',
  );

  /// Used only by the Debug UI Gallery to render the post-check state.
  final bool initialHasChecked;

  @override
  ConsumerState<AppUpdateScreen> createState() => _AppUpdateScreenState();
}

class _AppUpdateScreenState extends ConsumerState<AppUpdateScreen> {
  late bool _hasChecked;

  @override
  void initState() {
    super.initState();
    _hasChecked = widget.initialHasChecked;
  }

  @override
  Widget build(BuildContext context) {
    final english =
        ref.watch(appPreferencesControllerProvider).language ==
        AppLanguage.english;
    final copy = _UpdateCopy(english: english);

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
                Text(
                  copy.title,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                SizedBox(height: 6),
                Text(
                  copy.subtitle,
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    height: 1.45,
                  ),
                ),
                SizedBox(height: 24),
                _UpdateSection(
                  label: copy.currentVersionLabel,
                  child: Row(
                    children: [
                      Icon(
                        Icons.verified_outlined,
                        color: AletheiaTheme.cyan,
                        size: 22,
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Aletheia ${AppUpdateScreen.buildName} '
                              '(${AppUpdateScreen.buildNumber})',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 3),
                            Text(
                              copy.currentVersionDetail,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                _UpdateSection(
                  label: copy.checkLabel,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _hasChecked ? copy.developmentResult : copy.checkHint,
                        style: TextStyle(
                          color: AletheiaTheme.textSecondary,
                          height: 1.45,
                        ),
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: () => setState(() => _hasChecked = true),
                          icon: const Icon(Icons.system_update_alt_rounded),
                          label: Text(copy.checkAction),
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(height: 18),
                Text(
                  copy.safetyNote,
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
}

class _UpdateSection extends StatelessWidget {
  const _UpdateSection({required this.label, required this.child});

  final String label;
  final Widget child;

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
        child: Padding(padding: const EdgeInsets.all(16), child: child),
      ),
    ],
  );
}

class _UpdateCopy {
  const _UpdateCopy({required this.english});

  final bool english;

  String get title => english ? 'Check for updates' : '检查更新';
  String get subtitle => english
      ? 'Check the app release separately from the robot runtime.'
      : '检查 App 是否有可用版本；不会影响机器人运行配置。';
  String get currentVersionLabel => english ? 'Current version' : '当前版本';
  String get currentVersionDetail =>
      english ? 'Installed on this device' : '已安装在当前设备上';
  String get checkLabel => english ? 'Availability' : '可用更新';
  String get checkHint => english
      ? 'This development build can validate the update flow locally.'
      : '当前开发版本可先验证更新检查流程。';
  String get checkAction => english ? 'Check now' : '立即检查';
  String get developmentResult => english
      ? 'No update service is connected in this development build.'
      : '当前开发版本尚未接入在线更新服务。';
  String get safetyNote => english
      ? 'Future app updates use a reviewed distribution channel. They never use the robot offline-upgrade directory or change robot settings.'
      : '后续 App 更新将使用经审核的发布渠道，不会使用机器人离线升级目录，也不会改动机器人配置。';
}
