import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/system_maintenance_controller.dart';

/// Deliberately isolated from normal tools: this surface can restart or stop
/// the console, but never controls the robot base, navigation or ROS graph.
class SystemMaintenanceScreen extends ConsumerWidget {
  const SystemMaintenanceScreen({super.key});
  static const routePath = '/tools/maintenance';
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) {
      return Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.lan_outlined, color: AletheiaTheme.textTertiary),
              SizedBox(height: 12),
              Text(
                '先连接机器人后再进行控制台维护。',
                style: TextStyle(color: AletheiaTheme.textSecondary),
              ),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: () => context.go(RobotConnectionScreen.routePath),
                child: const Text('前往机器人'),
              ),
            ],
          ),
        ),
      );
    }
    return SafeArea(top: false, child: const _MaintenanceBody());
  }
}

class _MaintenanceBody extends ConsumerStatefulWidget {
  const _MaintenanceBody();
  @override
  ConsumerState<_MaintenanceBody> createState() => _MaintenanceBodyState();
}

class _MaintenanceBodyState extends ConsumerState<_MaintenanceBody> {
  bool _busy = false;
  Future<void> _shutdown() async {
    if (_busy) return;
    final allowed = await _confirm(
      '停止 Aletheia 控制台？',
      '这会安全停止当前 Aletheia 控制台。它不会向底盘或导航发送指令，但 App 将断开连接，需在机器人端重新启动控制台。',
      '停止控制台',
      danger: true,
    );
    if (!allowed) return;
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    setState(() => _busy = true);
    try {
      await ref.read(systemMaintenanceRepositoryProvider).shutdown(endpoint);
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('控制台正在安全停止。')));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('无法停止控制台：$error')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm(
    String title,
    String detail,
    String confirm, {
    bool danger = false,
  }) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(detail, style: const TextStyle(height: 1.4)),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: Text('取消'),
            ),
            FilledButton(
              style: danger
                  ? FilledButton.styleFrom(
                      backgroundColor: AletheiaTheme.danger,
                    )
                  : null,
              onPressed: () => Navigator.pop(context, true),
              child: Text(confirm),
            ),
          ],
        ),
      ) ??
      false;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
    children: [
      Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.build_outlined,
                    size: 17,
                    color: AletheiaTheme.cyan,
                  ),
                  SizedBox(width: 8),
                  Text(
                    '工具 / 控制台服务',
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                '控制台服务',
                style: Theme.of(context).textTheme.headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -.4),
              ),
              SizedBox(height: 7),
              Text(
                '管理当前 Aletheia 控制台服务。高影响操作必须明确确认。',
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 20),
              _Panel(
                title: '安全停止',
                detail: '仅停止 Aletheia 控制台服务，不会控制机器人本体。通常仅在现场维护人员明确要求时使用。',
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AletheiaTheme.danger,
                  ),
                  onPressed: _busy ? null : _shutdown,
                  icon: const Icon(Icons.power_settings_new_outlined),
                  label: const Text('停止控制台'),
                ),
              ),
            ],
          ),
        ),
      ),
    ],
  );
}

class _Panel extends StatelessWidget {
  const _Panel({
    required this.title,
    required this.detail,
    required this.child,
  });
  final String title;
  final String detail;
  final Widget child;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surface,
      border: Border.all(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    ),
    child: Padding(
      padding: const EdgeInsets.all(16),
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
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    ),
  );
}
