import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'app_shell.dart';
import 'motion/aletheia_motion.dart';
import '../debug_ui/debug_ui_gallery_screen.dart';
import '../features/robot_connection/presentation/robot_connection_screen.dart';
import '../features/reports/presentation/reports_screen.dart';
import '../features/live_observation/presentation/live_observation_screen.dart';
import '../features/test_cases/presentation/test_cases_screen.dart';
import '../features/test_runs/presentation/test_runs_screen.dart';
import '../features/tool_logs/presentation/tool_logs_screen.dart';
import '../features/tools/presentation/tools_screen.dart';
import '../features/runtime_settings/presentation/runtime_settings_screen.dart';
import '../features/scenario_setup/presentation/scenario_setup_screen.dart';
import '../features/system_maintenance/presentation/system_maintenance_screen.dart';
import '../features/app_settings/presentation/app_settings_screen.dart';
import '../features/app_settings/presentation/app_update_screen.dart';
import '../features/app_settings/presentation/feedback_screen.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    initialLocation: RobotConnectionScreen.routePath,
    routes: [
      if (kDebugMode)
        GoRoute(
          path: DebugUiGalleryScreen.routePath,
          pageBuilder: (context, state) => AletheiaMotion.rootPage(
            key: state.pageKey,
            child: DebugUiGalleryScreen(
              initialScreenId: state.uri.queryParameters['screen'],
            ),
          ),
        ),
      GoRoute(
        path: '/',
        redirect: (context, state) => RobotConnectionScreen.routePath,
      ),
      GoRoute(
        path: RobotConnectionScreen.legacyRoutePath,
        redirect: (context, state) => RobotConnectionScreen.routePath,
      ),
      GoRoute(
        path: TestCasesScreen.legacyRoutePath,
        redirect: (context, state) => TestCasesScreen.routePath,
      ),
      GoRoute(
        path: TestRunsScreen.legacyRoutePath,
        redirect: (context, state) => TestRunsScreen.routePath,
      ),
      GoRoute(
        path: '/tools/app-settings',
        redirect: (context, state) => AppSettingsScreen.routePath,
      ),
      ShellRoute(
        builder: (context, state, child) =>
            AletheiaAppShell(location: state.uri.path, child: child),
        routes: [
          GoRoute(
            path: RobotConnectionScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const RobotConnectionScreen(embedded: true),
            ),
          ),
          GoRoute(
            path: LiveObservationScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const LiveObservationScreen(),
            ),
          ),
          GoRoute(
            path: ToolsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const ToolsScreen(),
            ),
          ),
          GoRoute(
            path: TestCasesScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const TestCasesScreen(),
            ),
          ),
          GoRoute(
            path: TestRunsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const TestRunsScreen(),
            ),
          ),
          GoRoute(
            path: ToolLogsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ToolLogsScreen(),
            ),
          ),
          GoRoute(
            path: ReportsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ReportsScreen(),
            ),
          ),
          GoRoute(
            path: RuntimeSettingsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const RuntimeSettingsScreen(),
            ),
          ),
          GoRoute(
            path: ScenarioSetupScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const ScenarioSetupScreen(),
            ),
          ),
          GoRoute(
            path: SystemMaintenanceScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const SystemMaintenanceScreen(),
            ),
          ),
          GoRoute(
            path: AppSettingsScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.rootPage(
              key: state.pageKey,
              child: const AppSettingsScreen(embedded: true),
            ),
          ),
          GoRoute(
            path: AppFeedbackScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const AppFeedbackScreen(),
            ),
          ),
          GoRoute(
            path: AppUpdateScreen.routePath,
            pageBuilder: (context, state) => AletheiaMotion.detailPage(
              key: state.pageKey,
              child: const AppUpdateScreen(),
            ),
          ),
        ],
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});
