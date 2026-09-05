import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../../reports/presentation/reports_screen.dart';
import '../../tool_logs/presentation/tool_logs_screen.dart';
import '../../manual_control/presentation/manual_control_screen.dart';
import '../../test_runs/presentation/test_runs_screen.dart';
import '../../runtime_settings/presentation/runtime_settings_screen.dart';
import '../../scenario_setup/presentation/scenario_setup_screen.dart';
import '../../system_maintenance/presentation/system_maintenance_screen.dart';

/// Entry point for low-frequency capabilities that act on the selected robot.
///
/// A test case is a test-system object, so it deliberately lives below this
/// workspace rather than competing with the robot and observation tabs.
class ToolsScreen extends ConsumerWidget {
  const ToolsScreen({super.key});

  static const routePath = '/tools';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    final destination = connected
        ? TestRunsScreen.routePath
        : RobotConnectionScreen.routePath;

    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _PageLabel(icon: Icons.handyman_outlined, text: '工具'),
                const SizedBox(height: 10),
                Text(
                  '机器人工作台',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    letterSpacing: -.4,
                  ),
                ),
                SizedBox(height: 7),
                Text(
                  '为当前机器人提供测试、诊断与报告能力。',
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 20),
                _ToolEntry(
                  icon: Icons.gamepad_outlined,
                  title: '手动控制',
                  detail: connected
                      ? '在车端确认安全状态后，用摇杆执行受控的前进、后退与转向。'
                      : '连接机器人后可查看车端控制状态。',
                  actionLabel: connected ? '打开控制' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? ManualControlScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.fact_check_outlined,
                  title: '自动化测试',
                  detail: connected
                      ? '选择测试内容，创建测试计划，并跟踪当前进度。'
                      : '连接机器人后即可创建或查看测试计划。',
                  actionLabel: connected ? '打开测试' : '连接机器人',
                  onTap: () => context.go(destination),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.receipt_long_outlined,
                  title: '诊断日志',
                  detail: connected
                      ? '查看机器人运行日志，可按全部或错误筛选。'
                      : '连接机器人后即可查看诊断日志。',
                  actionLabel: connected ? '查看日志' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? ToolLogsScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.description_outlined,
                  title: '测试报告',
                  detail: connected
                      ? '查看已生成的测试报告，并在浏览器中打开。'
                      : '连接机器人后即可查看测试报告。',
                  actionLabel: connected ? '查看报告' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? ReportsScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.tune_outlined,
                  title: '运行配置',
                  detail: connected
                      ? '管理测试预检顺序、受控运行参数和观测车型。'
                      : '连接机器人后即可查看受控运行配置。',
                  actionLabel: connected ? '打开配置' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? RuntimeSettingsScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.auto_awesome_motion_outlined,
                  title: '场景前置配置',
                  detail: connected
                      ? '预览、保存并受控应用测试前的启动参数方案。'
                      : '连接机器人后即可管理测试场景方案。',
                  actionLabel: connected ? '管理方案' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? ScenarioSetupScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 12),
                _ToolEntry(
                  icon: Icons.build_outlined,
                  title: '控制台服务',
                  detail: connected
                      ? '安全停止当前控制台服务。该操作需要再次确认。'
                      : '连接机器人后即可管理控制台服务。',
                  actionLabel: connected ? '查看服务' : '连接机器人',
                  onTap: () => context.go(
                    connected
                        ? SystemMaintenanceScreen.routePath
                        : RobotConnectionScreen.routePath,
                  ),
                ),
                const SizedBox(height: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ToolEntry extends StatelessWidget {
  const _ToolEntry({
    required this.icon,
    required this.title,
    required this.detail,
    required this.actionLabel,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String detail;
  final String actionLabel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AletheiaTheme.surface,
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      child: InkWell(
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        onTap: onTap,
        child: Container(
          constraints: BoxConstraints(minHeight: 128),
          padding: EdgeInsets.all(18),
          decoration: BoxDecoration(
            border: Border.all(color: AletheiaTheme.border),
            borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: AletheiaTheme.cyan.withValues(alpha: .12),
                  borderRadius: BorderRadius.circular(
                    AletheiaTheme.controlRadius,
                  ),
                ),
                child: Icon(icon, color: AletheiaTheme.cyan),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    SizedBox(height: 6),
                    Text(
                      detail,
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        height: 1.4,
                      ),
                    ),
                    SizedBox(height: 14),
                    Text(
                      actionLabel,
                      style: TextStyle(
                        color: AletheiaTheme.cyan,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              SizedBox(width: 8),
              Padding(
                padding: EdgeInsets.only(top: 10),
                child: Icon(
                  Icons.arrow_forward_ios_rounded,
                  color: AletheiaTheme.textTertiary,
                  size: 16,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PageLabel extends StatelessWidget {
  const _PageLabel({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: AletheiaTheme.cyan, size: 17),
        SizedBox(width: 8),
        Text(
          text,
          style: TextStyle(
            color: AletheiaTheme.textSecondary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}
