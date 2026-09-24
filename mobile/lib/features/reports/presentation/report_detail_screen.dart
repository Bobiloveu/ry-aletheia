import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../application/reports_controller.dart';
import '../domain/aletheia_report.dart';

class ReportDetailScreen extends ConsumerWidget {
  const ReportDetailScreen({required this.reportId, super.key});

  final String reportId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(nativeReportDetailProvider(reportId));
    return SafeArea(
      top: false,
      child: detail.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _DetailMessage(
          icon: Icons.error_outline_rounded,
          title: '无法读取原生测试报告',
          detail: '车端暂时未返回原生报告详情，请检查连接后重试。',
          actionLabel: '重试',
          onAction: () => ref.invalidate(nativeReportDetailProvider(reportId)),
          danger: true,
        ),
        data: (state) => _ReportDetailBody(state: state, reportId: reportId),
      ),
    );
  }
}

class _ReportDetailBody extends ConsumerWidget {
  const _ReportDetailBody({required this.state, required this.reportId});

  final NativeReportDetailState state;
  final String reportId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final report = state.report;
    final exceptions = state.items
        .where(
          (item) =>
              item.status == ReportStatus.failed ||
              item.status == ReportStatus.blocked,
        )
        .toList(growable: false);
    final normal = state.items
        .where((item) => !exceptions.contains(item))
        .toList(growable: false);
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
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
                      Icons.assignment_turned_in_outlined,
                      color: AletheiaTheme.cyan,
                      size: 17,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '测试报告 / 详情',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  report.title,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 6),
                Text(
                  '${_kindLabel(report.kind)} · ${_formatDate(report.createdAt)} · ${_formatDuration(report.duration)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 18),
                _Section(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '结论',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        report.headline ?? _statusConclusion(report.status),
                        style: Theme.of(context).textTheme.bodyLarge,
                      ),
                      const SizedBox(height: 16),
                      _Metrics(metrics: report.summary),
                    ],
                  ),
                ),
                if (exceptions.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  Text('需要关注', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  ...exceptions.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: _TaskRow(item: item, emphasize: true),
                    ),
                  ),
                ],
                const SizedBox(height: 18),
                Text('全部任务', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                ...normal.map(
                  (item) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _TaskRow(item: item),
                  ),
                ),
                if (state.items.isEmpty)
                  const _DetailMessage(
                    icon: Icons.format_list_bulleted_outlined,
                    title: '此页尚无任务明细',
                    detail: '车端将在后续分页中提供可展示的测试任务。',
                  ),
                if (state.isLoadingMore) ...[
                  const SizedBox(height: 12),
                  const Center(child: CircularProgressIndicator()),
                ] else if (state.loadMoreError != null) ...[
                  const SizedBox(height: 12),
                  _LoadMoreError(
                    onRetry: () => ref
                        .read(nativeReportDetailProvider(reportId).notifier)
                        .loadNextPage(),
                  ),
                ] else if (state.nextCursor != null) ...[
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () => ref
                        .read(nativeReportDetailProvider(reportId).notifier)
                        .loadNextPage(),
                    icon: const Icon(Icons.expand_more_rounded),
                    label: const Text('加载更多任务'),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surface,
      border: Border.all(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    ),
    child: Padding(padding: const EdgeInsets.all(16), child: child),
  );
}

class _Metrics extends StatelessWidget {
  const _Metrics({required this.metrics});
  final NativeReportMetrics metrics;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Expanded(
        child: _Metric(value: '${metrics.total}', label: '任务'),
      ),
      Expanded(
        child: _Metric(
          value: '${metrics.passed}',
          label: '通过',
          color: AletheiaTheme.mint,
        ),
      ),
      Expanded(
        child: _Metric(
          value: '${metrics.exceptionCount}',
          label: '异常',
          color: AletheiaTheme.danger,
        ),
      ),
    ],
  );
}

class _Metric extends StatelessWidget {
  const _Metric({required this.value, required this.label, this.color});
  final String value;
  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        value,
        style: Theme.of(context).textTheme.titleLarge?.copyWith(color: color),
      ),
      const SizedBox(height: 2),
      Text(label, style: Theme.of(context).textTheme.bodySmall),
    ],
  );
}

class _TaskRow extends StatelessWidget {
  const _TaskRow({required this.item, this.emphasize = false});
  final NativeReportItem item;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(item.status);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: emphasize ? color.withValues(alpha: .08) : AletheiaTheme.surface,
        border: Border.all(
          color: emphasize
              ? color.withValues(alpha: .45)
              : AletheiaTheme.border,
        ),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(_statusIcon(item.status), color: color, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  if (item.summary != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      item.summary!,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ],
                  if (item.detail != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      item.detail!,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            Text(
              _formatDuration(item.duration),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _LoadMoreError extends StatelessWidget {
  const _LoadMoreError({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => _Section(
    child: Row(
      children: [
        Icon(Icons.sync_problem_outlined, color: AletheiaTheme.warning),
        const SizedBox(width: 10),
        const Expanded(child: Text('更多任务暂时未能读取，已显示的内容仍可查看。')),
        TextButton(onPressed: onRetry, child: const Text('重试')),
      ],
    ),
  );
}

class _DetailMessage extends StatelessWidget {
  const _DetailMessage({
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
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: _Section(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, color: color, size: 26),
                const SizedBox(height: 14),
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 6),
                Text(detail, style: Theme.of(context).textTheme.bodyMedium),
                if (actionLabel != null && onAction != null) ...[
                  const SizedBox(height: 14),
                  OutlinedButton(
                    onPressed: onAction,
                    child: Text(actionLabel!),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
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

String _statusConclusion(ReportStatus status) => switch (status) {
  ReportStatus.passed => '本次测试通过。',
  ReportStatus.failed => '本次测试未通过，请检查异常任务。',
  ReportStatus.blocked => '本次测试被受控流程阻断。',
  ReportStatus.cancelled => '本次测试已取消。',
  ReportStatus.incomplete => '本次测试未完整结束。',
  ReportStatus.unknown => '车端返回了未识别的报告状态。',
};

Color _statusColor(ReportStatus status) => switch (status) {
  ReportStatus.passed => AletheiaTheme.mint,
  ReportStatus.failed => AletheiaTheme.danger,
  ReportStatus.blocked || ReportStatus.incomplete => AletheiaTheme.warning,
  ReportStatus.cancelled || ReportStatus.unknown => AletheiaTheme.textTertiary,
};

IconData _statusIcon(ReportStatus status) => switch (status) {
  ReportStatus.passed => Icons.check_circle_outline_rounded,
  ReportStatus.failed => Icons.error_outline_rounded,
  ReportStatus.blocked => Icons.block_outlined,
  ReportStatus.cancelled => Icons.cancel_outlined,
  ReportStatus.incomplete => Icons.pending_outlined,
  ReportStatus.unknown => Icons.help_outline_rounded,
};
