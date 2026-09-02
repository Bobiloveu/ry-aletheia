import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

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
    if (endpoint == null) {
      return const _ConnectionRequired();
    }
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
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 900),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _PageLabel(
                  icon: Icons.description_outlined,
                  text: '工具 / 测试报告',
                ),
                const SizedBox(height: 10),
                Text(
                  '测试报告',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    letterSpacing: -.4,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  '查看当前机器人已生成的测试报告。点击后将在浏览器中打开。',
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 16),
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
}

class _ReportCard extends StatelessWidget {
  const _ReportCard({required this.report, required this.endpoint});

  final AletheiaReport report;
  final RobotEndpoint endpoint;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AletheiaTheme.surface,
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      child: InkWell(
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        onTap: () => _open(context),
        child: Container(
          padding: const EdgeInsets.all(16),
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
                child: Icon(
                  Icons.description_outlined,
                  color: AletheiaTheme.cyan,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      report.filename,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '${report.modifiedLabel}  ·  ${report.sizeLabel}',
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '在浏览器打开',
                      style: TextStyle(
                        color: AletheiaTheme.cyan,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Padding(
                padding: EdgeInsets.only(top: 10),
                child: Icon(
                  Icons.open_in_new_rounded,
                  color: AletheiaTheme.textTertiary,
                  size: 18,
                ),
              ),
              _ReportActions(report: report, endpoint: endpoint),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context) async {
    if (!report.isOpenableHtml) {
      _showOpenError(context);
      return;
    }
    final uri = endpoint.apiUri('api/report-files/${report.filename}');
    try {
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened && context.mounted) {
        _showOpenError(context);
      }
    } catch (_) {
      if (context.mounted) {
        _showOpenError(context);
      }
    }
  }

  void _showOpenError(BuildContext context) {
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('无法在浏览器中打开该报告。')));
  }
}

class _ReportActions extends ConsumerWidget {
  const _ReportActions({required this.report, required this.endpoint});
  final AletheiaReport report;
  final RobotEndpoint endpoint;

  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      PopupMenuButton<_ReportAction>(
        tooltip: '报告操作',
        onSelected: (action) => _handle(context, ref, action),
        itemBuilder: (context) => [
          const PopupMenuItem(
            value: _ReportAction.downloadHtml,
            child: Text('下载 HTML'),
          ),
          if (report.csvFilename != null)
            const PopupMenuItem(
              value: _ReportAction.downloadCsv,
              child: Text('下载 CSV'),
            ),
          const PopupMenuDivider(),
          const PopupMenuItem(value: _ReportAction.delete, child: Text('删除报告')),
        ],
      );

  Future<void> _handle(
    BuildContext context,
    WidgetRef ref,
    _ReportAction action,
  ) async {
    if (action == _ReportAction.downloadHtml ||
        action == _ReportAction.downloadCsv) {
      final name = action == _ReportAction.downloadHtml
          ? report.filename
          : report.csvFilename!;
      final opened = await launchUrl(
        endpoint.apiUri(
          action == _ReportAction.downloadHtml
              ? 'api/reports/$name/download'
              : 'api/report-files/$name',
        ),
        mode: LaunchMode.externalApplication,
      );
      if (!opened && context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('无法开始下载。')));
      }
      return;
    }
    final confirmed =
        await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('删除测试报告？'),
            content: Text(
              '将删除“${report.filename}”及其 CSV 与轨迹证据。此操作无法撤销。',
              style: const TextStyle(height: 1.4),
            ),
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

enum _ReportAction { downloadHtml, downloadCsv, delete }

class _EmptyReports extends StatelessWidget {
  const _EmptyReports();

  @override
  Widget build(BuildContext context) {
    return const _MessageBlock(
      icon: Icons.description_outlined,
      title: '尚未生成测试报告',
      detail: '完成测试后，报告会显示在这里。',
    );
  }
}

class _LoadingList extends StatelessWidget {
  const _LoadingList();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: CircularProgressIndicator(),
      ),
    );
  }
}

class _ErrorList extends StatelessWidget {
  const _ErrorList({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(
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
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();

  @override
  Widget build(BuildContext context) {
    return Center(
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
            Text(
              title,
              style: Theme.of(context).textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
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
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: AletheiaTheme.cyan, size: 17),
        const SizedBox(width: 8),
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
