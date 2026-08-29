import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/tool_logs_controller.dart';
import '../domain/tool_log_entry.dart';

class ToolLogsScreen extends ConsumerWidget {
  const ToolLogsScreen({super.key});

  static const routePath = '/tools/logs';

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

    final scope = ref.watch(toolLogScopeProvider);
    final entries = ref.watch(toolLogEntriesProvider);
    final files = ref.watch(diagnosticFilesProvider);

    return SafeArea(
      top: false,
      child: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(toolLogEntriesProvider);
          await ref.read(toolLogEntriesProvider.future);
        },
        child: entries.when(
          loading: () => const _LoadingList(),
          error: (error, _) => _ErrorList(
            message: error.toString(),
            onRetry: () => ref.invalidate(toolLogEntriesProvider),
          ),
          data: (items) => _LogList(
            entries: items,
            scope: scope,
            endpoint: endpoint,
            files: files.when(
              data: (value) => value,
              loading: () => const [],
              error: (_, _) => const [],
            ),
            onScopeChanged: (value) =>
                ref.read(toolLogScopeProvider.notifier).select(value),
          ),
        ),
      ),
    );
  }
}

class _LogList extends StatelessWidget {
  const _LogList({
    required this.entries,
    required this.scope,
    required this.endpoint,
    required this.files,
    required this.onScopeChanged,
  });

  final List<ToolLogEntry> entries;
  final ToolLogScope scope;
  final RobotEndpoint endpoint;
  final List<DiagnosticFile> files;
  final ValueChanged<ToolLogScope> onScopeChanged;

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
                  icon: Icons.receipt_long_outlined,
                  text: '工具 / 诊断日志',
                ),
                const SizedBox(height: 10),
                Text(
                  '诊断日志',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    letterSpacing: -.4,
                  ),
                ),
                SizedBox(height: 7),
                Text(
                  '查看当前机器人的最近运行日志。下拉可刷新。',
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 18),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton.icon(
                      onPressed: () => _download(
                        context,
                        endpoint.apiUri(
                          'api/tool-logs/download',
                          queryParameters: const {'scope': 'errors'},
                        ),
                      ),
                      icon: const Icon(Icons.file_download_outlined),
                      label: const Text('下载错误日志'),
                    ),
                    OutlinedButton.icon(
                      onPressed: () => _download(
                        context,
                        endpoint.apiUri(
                          'api/tool-logs/download',
                          queryParameters: const {'scope': 'all'},
                        ),
                      ),
                      icon: const Icon(Icons.folder_zip_outlined),
                      label: const Text('下载完整诊断包'),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                if (files.isNotEmpty) ...[
                  Text(
                    '可下载诊断文件',
                    style: Theme.of(context).textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  ...files.map(
                    (file) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: _DiagnosticFileRow(file: file, endpoint: endpoint),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                SegmentedButton<ToolLogScope>(
                  segments: ToolLogScope.values
                      .map(
                        (item) => ButtonSegment<ToolLogScope>(
                          value: item,
                          label: Text(item.label),
                          icon: Icon(
                            item == ToolLogScope.all
                                ? Icons.subject_outlined
                                : Icons.error_outline_rounded,
                          ),
                        ),
                      )
                      .toList(growable: false),
                  selected: {scope},
                  onSelectionChanged: (selection) {
                    if (selection.isNotEmpty) {
                      onScopeChanged(selection.first);
                    }
                  },
                ),
                const SizedBox(height: 16),
                Text(
                  '${entries.length} 条日志',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                const SizedBox(height: 10),
                if (entries.isEmpty)
                  const _EmptyLogs()
                else
                  ...entries.map(
                    (entry) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: _LogEntryCard(entry: entry),
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

Future<void> _download(BuildContext context, Uri uri) async {
  final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
  if (!opened && context.mounted) {
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('无法开始下载。')));
  }
}

class _DiagnosticFileRow extends StatelessWidget {
  const _DiagnosticFileRow({required this.file, required this.endpoint});
  final DiagnosticFile file;
  final RobotEndpoint endpoint;
  @override
  Widget build(BuildContext context) => Material(
    color: AletheiaTheme.surfaceRaised,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    clipBehavior: Clip.antiAlias,
    child: ListTile(
      leading: Icon(Icons.description_outlined, color: AletheiaTheme.cyan),
      title: Text(
        file.label,
        style: const TextStyle(fontWeight: FontWeight.w700),
      ),
      subtitle: Text(
        file.detail.isEmpty
            ? '${file.name} · ${file.sizeLabel}'
            : '${file.detail}\n${file.name} · ${file.sizeLabel}',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: IconButton(
        tooltip: '下载',
        onPressed: () => _download(
          context,
          endpoint.apiUri('api/tool-logs/files/${file.name}/download'),
        ),
        icon: const Icon(Icons.download_outlined),
      ),
    ),
  );
}

class _LogEntryCard extends StatelessWidget {
  const _LogEntryCard({required this.entry});

  final ToolLogEntry entry;

  @override
  Widget build(BuildContext context) {
    final color = switch (entry.level) {
      ToolLogLevel.info => AletheiaTheme.cyan,
      ToolLogLevel.warning => AletheiaTheme.warning,
      ToolLogLevel.error || ToolLogLevel.critical => AletheiaTheme.danger,
      ToolLogLevel.unknown => AletheiaTheme.textTertiary,
    };
    return Material(
      color: AletheiaTheme.surface,
      shape: RoundedRectangleBorder(
        side: BorderSide(
          color: entry.level.isError
              ? color.withValues(alpha: .7)
              : AletheiaTheme.border,
        ),
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                _LevelBadge(label: entry.level.label, color: color),
                Text(
                  entry.source,
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Text(
                  entry.time,
                  style: TextStyle(
                    color: AletheiaTheme.textTertiary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(entry.message, style: const TextStyle(height: 1.4)),
            if (entry.exception.isNotEmpty) ...[
              const SizedBox(height: 10),
              Divider(),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.only(bottom: 8),
                title: Text(
                  '查看详情',
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                children: [
                  SelectableText(
                    entry.exception,
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _LevelBadge extends StatelessWidget {
  const _LevelBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Text(
          label,
          style: TextStyle(
            color: color,
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _EmptyLogs extends StatelessWidget {
  const _EmptyLogs();

  @override
  Widget build(BuildContext context) {
    return const _MessageBlock(
      icon: Icons.notes_outlined,
      title: '当前范围内没有日志',
      detail: '当前筛选下没有日志。',
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
          title: '无法读取诊断日志',
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
          detail: '连接机器人后即可查看诊断日志。',
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
            SizedBox(height: 6),
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
