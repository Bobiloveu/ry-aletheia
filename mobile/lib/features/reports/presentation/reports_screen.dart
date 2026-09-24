import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/motion/aletheia_interaction.dart';
import '../../../app/motion/aletheia_motion.dart';
import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/reports_controller.dart';
import '../domain/aletheia_report.dart';

class ReportsScreen extends ConsumerWidget {
  const ReportsScreen({super.key});

  static const routePath = '/tools/reports';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (state) => state.isConnected ? state.endpoint : null,
      ),
    );
    if (endpoint == null) return const _ConnectionRequired();

    final reports = ref.watch(reportsProvider);
    return SafeArea(
      top: false,
      child: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(reportsProvider);
          await ref.read(reportsProvider.future);
        },
        child: reports.when(
          loading: () => const _LoadingList(),
          error: (error, _) => _ErrorList(
            message: error.toString(),
            onRetry: () => ref.invalidate(reportsProvider),
          ),
          data: (items) => _ReportsList(reports: items, endpoint: endpoint),
        ),
      ),
    );
  }
}

class _ReportsList extends StatelessWidget {
  const _ReportsList({required this.reports, required this.endpoint});

  final List<AletheiaReport> reports;
  final RobotEndpoint endpoint;

  @override
  Widget build(BuildContext context) => ListView(
    physics: const AlwaysScrollableScrollPhysics(),
    padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
    children: [
      Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const _PageLabel(
                icon: Icons.assignment_turned_in_outlined,
                text: '工具 / 测试报告',
              ),
              const SizedBox(height: 10),
              Text('测试报告', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 7),
              Text(
                '在 App 内查看本次测试的结论、指标与任务明细。',
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 18),
              Text(
                '${reports.length} 份报告',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              const SizedBox(height: 10),
              if (reports.isEmpty)
                const _EmptyReports()
              else
                ...reports.map(
                  (report) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _ReportCard(report: report, endpoint: endpoint),
                  ),
                ),
            ],
          ),
        ),
      ),
    ],
  );
}

class _ReportCard extends StatelessWidget {
  const _ReportCard({required this.report, required this.endpoint});

  final AletheiaReport report;
  final RobotEndpoint endpoint;

  @override
  Widget build(BuildContext context) {
    final native = report.nativeReport;
    final content = native == null
        ? _LegacyReportContent(report: report)
        : _NativeReportContent(report: report, native: native);
    return AletheiaPressFeedback(
      enabled: native != null,
      child: Material(
        color: AletheiaTheme.surface,
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        child: InkWell(
          key: native == null
              ? null
              : ValueKey('native-report-${native.reportId}'),
          borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
          onTap: native == null
              ? null
              : () => context.push(
                  '${ReportsScreen.routePath}/${native.reportId}',
                ),
          child: Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
            decoration: BoxDecoration(
              border: Border.all(color: AletheiaTheme.border),
              borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _ReportIcon(status: native?.status),
                const SizedBox(width: 13),
                Expanded(child: content),
                _ReportActions(report: report, endpoint: endpoint),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NativeReportContent extends StatelessWidget {
  const _NativeReportContent({required this.report, required this.native});

  final AletheiaReport report;
  final NativeReportSummary native;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              native.title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          const SizedBox(width: 8),
          _StatusChip(status: native.status),
        ],
      ),
      const SizedBox(height: 5),
      Text(
        '${_kindLabel(native.kind)} · ${_formatDate(native.createdAt)} · ${_formatDuration(native.duration)}',
        style: Theme.of(context).textTheme.bodySmall,
      ),
      if (native.headline != null) ...[
        const SizedBox(height: 10),
        Text(native.headline!, maxLines: 2, overflow: TextOverflow.ellipsis),
      ],
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 6,
        children: [
          _MetricLabel('任务 ${native.summary.total}'),
          _MetricLabel(
            '通过 ${native.summary.passed}',
            color: AletheiaTheme.mint,
          ),
          _MetricLabel(
            '异常 ${native.summary.exceptionCount}',
            color: _statusColor(native.status),
          ),
        ],
      ),
    ],
  );
}

class _LegacyReportContent extends StatelessWidget {
  const _LegacyReportContent({required this.report});

  final AletheiaReport report;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        report.title ?? report.filename,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 5),
      Text(
        '${report.modifiedLabel} · ${report.sizeLabel}',
        style: Theme.of(context).textTheme.bodySmall,
      ),
      const SizedBox(height: 12),
      Text(
        '车端尚未提供原生报告数据',
        style: TextStyle(
          color: AletheiaTheme.textSecondary,
          fontWeight: FontWeight.w600,
        ),
      ),
    ],
  );
}

class _ReportIcon extends StatelessWidget {
  const _ReportIcon({this.status});

  final ReportStatus? status;

  @override
  Widget build(BuildContext context) => Container(
    width: 42,
    height: 42,
    decoration: BoxDecoration(
      color: _statusColor(status).withValues(alpha: .12),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Icon(
      status == null ? Icons.description_outlined : _statusIcon(status!),
      color: _statusColor(status),
    ),
  );
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final ReportStatus status;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Semantics(
      label: '报告状态：${_statusLabel(status)}',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .12),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Text(
          _statusLabel(status),
          style: TextStyle(
            color: color,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _MetricLabel extends StatelessWidget {
  const _MetricLabel(this.label, {this.color});

  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) => Text(
    label,
    style: Theme.of(context).textTheme.labelMedium
        ?.copyWith(color: color ?? AletheiaTheme.textSecondary),
  );
}

class _ReportActions extends ConsumerWidget {
  const _ReportActions({required this.report, required this.endpoint});

  final AletheiaReport report;
  final RobotEndpoint endpoint;

  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      PopupMenuButton<_ReportAction>(
        tooltip: '报告操作',
        onSelected: (action) => _delete(context, ref, action),
        itemBuilder: (_) => const [
          PopupMenuItem(value: _ReportAction.delete, child: Text('删除报告')),
        ],
      );

  Future<void> _delete(
    BuildContext context,
    WidgetRef ref,
    _ReportAction action,
  ) async {
    if (action != _ReportAction.delete) return;
    final confirmed =
        await showDialog<bool>(
          context: context,
          animationStyle: AletheiaMotion.surfaceAnimationStyle(context),
          builder: (context) => AlertDialog(
            title: const Text('删除测试报告？'),
            content: Text('将删除“${report.filename}”及其 CSV 与轨迹证据。此操作无法撤销。'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消'),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AletheiaTheme.danger,
                ),
                onPressed: () => Navigator.pop(context, true),
                child: const Text('删除'),
              ),
            ],
          ),
        ) ??
        false;
    if (!confirmed) return;
    try {
      await ref.read(reportsRepositoryProvider).delete(endpoint, report);
      ref.invalidate(reportsProvider);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('报告已删除。')));
      }
    } catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('删除失败：$error')));
      }
    }
  }
}

enum _ReportAction { delete }

class _EmptyReports extends StatelessWidget {
  const _EmptyReports();

  @override
  Widget build(BuildContext context) => const _MessageBlock(
    icon: Icons.description_outlined,
    title: '尚未生成测试报告',
    detail: '完成测试后，报告会显示在这里。',
  );
}

class _LoadingList extends StatelessWidget {
  const _LoadingList();

  @override
  Widget build(BuildContext context) => const Center(
    child: Padding(
      padding: EdgeInsets.all(24),
      child: CircularProgressIndicator(),
    ),
  );
}

class _ErrorList extends StatelessWidget {
  const _ErrorList({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => ListView(
    physics: const AlwaysScrollableScrollPhysics(),
    padding: const EdgeInsets.all(24),
    children: [
      _MessageBlock(
        icon: Icons.error_outline_rounded,
        title: '无法读取测试报告',
        detail: message,
        actionLabel: '重试',
        onAction: onRetry,
        danger: true,
      ),
    ],
  );
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: _MessageBlock(
        icon: Icons.lan_outlined,
        title: '先连接机器人',
        detail: '连接机器人后即可查看测试报告。',
        actionLabel: '前往机器人',
        onAction: () => context.go(RobotConnectionScreen.routePath),
      ),
    ),
  );
}

class _MessageBlock extends StatelessWidget {
  const _MessageBlock({
    required this.icon,
    required this.title,
    required this.detail,
    this.actionLabel,
    this.onAction,
    this.danger = false,
  });

  final IconData icon;
  final String title;
  final String detail;
  final String? actionLabel;
  final VoidCallback? onAction;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final color = danger ? AletheiaTheme.danger : AletheiaTheme.textTertiary;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surface,
        border: Border.all(
          color: danger ? color.withValues(alpha: .65) : AletheiaTheme.border,
        ),
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 26),
            const SizedBox(height: 14),
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(
              detail,
              style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
            ),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
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
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, color: AletheiaTheme.cyan, size: 17),
      const SizedBox(width: 8),
      Text(text, style: Theme.of(context).textTheme.labelMedium),
    ],
  );
}

String _formatDate(DateTime value) {
  final local = value.toLocal();
  String two(int input) => input.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} ${two(local.hour)}:${two(local.minute)}';
}

String _formatDuration(Duration value) {
  if (value.inHours > 0) {
    return '${value.inHours} 小时 ${value.inMinutes.remainder(60)} 分';
  }
  if (value.inMinutes > 0) {
    return '${value.inMinutes} 分 ${value.inSeconds.remainder(60)} 秒';
  }
  return '${value.inSeconds} 秒';
}

String _kindLabel(ReportKind kind) => switch (kind) {
  ReportKind.test => '自动化测试',
  ReportKind.acceptance => '部署验收',
  ReportKind.unknown => '测试报告',
};

String _statusLabel(ReportStatus status) => switch (status) {
  ReportStatus.passed => '通过',
  ReportStatus.failed => '失败',
  ReportStatus.blocked => '受阻',
  ReportStatus.cancelled => '已取消',
  ReportStatus.incomplete => '未完成',
  ReportStatus.unknown => '未知',
};

Color _statusColor(ReportStatus? status) => switch (status) {
  ReportStatus.passed => AletheiaTheme.mint,
  ReportStatus.failed => AletheiaTheme.danger,
  ReportStatus.blocked || ReportStatus.incomplete => AletheiaTheme.warning,
  ReportStatus.cancelled ||
  ReportStatus.unknown ||
  null => AletheiaTheme.textTertiary,
};

IconData _statusIcon(ReportStatus status) => switch (status) {
  ReportStatus.passed => Icons.check_circle_outline_rounded,
  ReportStatus.failed => Icons.error_outline_rounded,
  ReportStatus.blocked => Icons.block_outlined,
  ReportStatus.cancelled => Icons.cancel_outlined,
  ReportStatus.incomplete => Icons.pending_outlined,
  ReportStatus.unknown => Icons.help_outline_rounded,
};
