import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/responsive_layout.dart';
import '../../../app/motion/aletheia_motion.dart';
import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../test_cases/application/test_cases_controller.dart';
import '../../test_cases/domain/aletheia_test_case.dart';
import '../../test_cases/presentation/test_cases_screen.dart';
import '../application/test_runs_controller.dart';
import '../domain/aletheia_run.dart';

class TestRunsScreen extends ConsumerWidget {
  const TestRunsScreen({this.scrollController, super.key});

  static const routePath = '/tools/testing';
  static const legacyRoutePath = '/runs';

  /// Externally owned only by the Debug Gallery, so it can inspect the real
  /// run-detail section without maintaining a second, synthetic screen.
  final ScrollController? scrollController;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) {
      return const _RunConnectionRequired();
    }

    final catalog = ref.watch(caseCatalogProvider);
    final cases = catalog.maybeWhen(
      data: (data) => data.cases,
      orElse: () => const <AletheiaTestCase>[],
    );
    final runState = ref.watch(testRunsControllerProvider);

    return SafeArea(
      top: false,
      child: RefreshIndicator(
        onRefresh: () =>
            ref.read(testRunsControllerProvider.notifier).refresh(),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = usesTwoColumnWorkspace(
              availableWidth: constraints.maxWidth,
              isLandscape: constraints.maxWidth > constraints.maxHeight,
            );
            final composer = _RunComposer(
              cases: cases,
              casesLoading: catalog.isLoading,
              casesError: catalog.hasError ? catalog.error.toString() : null,
              runState: runState,
            );
            final details = _RunDetails(runState: runState);
            final content = wide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 9, child: composer),
                      const SizedBox(width: 18),
                      Expanded(flex: 11, child: details),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [composer, const SizedBox(height: 16), details],
                  );
            return SingleChildScrollView(
              controller: scrollController,
              physics: const AlwaysScrollableScrollPhysics(),
              padding: EdgeInsets.fromLTRB(20, 16, 20, wide ? 32 : 28),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1240),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const _PageEyebrow(
                        icon: Icons.play_circle_outline_rounded,
                        text: '自动化测试',
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '创建与跟踪自动化验证',
                        style: Theme.of(context).textTheme.headlineSmall
                            ?.copyWith(
                              fontWeight: FontWeight.w700,
                              letterSpacing: -.4,
                            ),
                      ),
                      SizedBox(height: 7),
                      Text(
                        '开始前会自动完成必要检查；不满足条件时不会执行。',
                        style: TextStyle(
                          color: AletheiaTheme.textSecondary,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 14),
                      OutlinedButton.icon(
                        onPressed: () => context.go(TestCasesScreen.routePath),
                        icon: const Icon(Icons.inventory_2_outlined),
                        label: const Text('浏览用例库'),
                      ),
                      if (runState.message.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        _RunNotice(
                          text: runState.message,
                          isError: runState.isError,
                        ),
                      ],
                      const SizedBox(height: 20),
                      content,
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _RunComposer extends ConsumerStatefulWidget {
  const _RunComposer({
    required this.cases,
    required this.casesLoading,
    required this.casesError,
    required this.runState,
  });

  final List<AletheiaTestCase> cases;
  final bool casesLoading;
  final String? casesError;
  final TestRunsScreenState runState;

  @override
  ConsumerState<_RunComposer> createState() => _RunComposerState();
}

class _RunComposerState extends ConsumerState<_RunComposer> {
  late final TextEditingController _countController;
  late final TextEditingController _intervalController;
  String _formError = '';

  @override
  void initState() {
    super.initState();
    _countController = TextEditingController(text: '1');
    _intervalController = TextEditingController(text: '3');
  }

  @override
  void dispose() {
    _countController.dispose();
    _intervalController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final selectedCaseId = ref.watch(selectedCaseIdProvider);
    final selectedCase = widget.cases
        .where((testCase) => testCase.id == selectedCaseId)
        .firstOrNull;
    final activeRun = widget.runState.run?.status.isActive == true;
    final disabled =
        widget.runState.isBusy ||
        activeRun ||
        widget.casesLoading ||
        widget.cases.isEmpty;

    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionTitle(icon: Icons.add_task_outlined, title: '创建测试计划'),
          SizedBox(height: 8),
          Text(
            '确认后，测试将按设定的轮次执行。',
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
          ),
          const SizedBox(height: 22),
          if (widget.casesError != null)
            _RunNotice(text: '无法读取用例：${widget.casesError}', isError: true)
          else if (widget.casesLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (widget.cases.isEmpty)
            const _MutedBlock(
              icon: Icons.folder_off_outlined,
              text: '没有可执行用例。请先在“用例库”确认可用测试内容。',
            )
          else ...[
            DropdownButtonFormField<String>(
              key: ValueKey(selectedCase?.id),
              initialValue: selectedCase?.id,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '测试用例',
                prefixIcon: Icon(Icons.inventory_2_outlined),
              ),
              hint: const Text('选择一个用例'),
              items: widget.cases
                  .map(
                    (testCase) => DropdownMenuItem(
                      value: testCase.id,
                      child: Text(
                        testCase.displayName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  )
                  .toList(growable: false),
              onChanged: disabled
                  ? null
                  : (value) =>
                        ref.read(selectedCaseIdProvider.notifier).select(value),
            ),
            if (selectedCase != null) ...[
              const SizedBox(height: 10),
              _SelectedCaseHint(testCase: selectedCase),
            ],
            const SizedBox(height: 16),
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 380;
                final count = TextField(
                  controller: _countController,
                  enabled: !disabled,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: '执行轮次',
                    prefixIcon: Icon(Icons.repeat_rounded),
                  ),
                );
                final interval = TextField(
                  controller: _intervalController,
                  enabled: !disabled,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: '轮次间隔（秒）',
                    prefixIcon: Icon(Icons.timer_outlined),
                  ),
                );
                if (compact) {
                  return Column(
                    children: [count, const SizedBox(height: 12), interval],
                  );
                }
                return Row(
                  children: [
                    Expanded(child: count),
                    const SizedBox(width: 12),
                    Expanded(child: interval),
                  ],
                );
              },
            ),
            SizedBox(height: 10),
            Text(
              '允许范围：1–1000 轮；间隔 0–3600 秒。',
              style: TextStyle(
                color: AletheiaTheme.textTertiary,
                fontSize: 12,
                height: 1.35,
              ),
            ),
            if (_formError.isNotEmpty) ...[
              const SizedBox(height: 12),
              _RunNotice(text: _formError, isError: true),
            ],
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: disabled || selectedCase == null
                  ? null
                  : () => _confirmStart(selectedCase),
              icon: widget.runState.isActionPending
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.play_arrow_rounded),
              label: Text(
                activeRun
                    ? '当前已有运行进行中'
                    : widget.runState.isActionPending
                    ? '正在创建…'
                    : '确认并创建测试计划',
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _confirmStart(AletheiaTestCase testCase) async {
    final count = int.tryParse(_countController.text.trim());
    final interval = double.tryParse(_intervalController.text.trim());
    if (count == null || count < 1 || count > 1000) {
      setState(() => _formError = '执行轮次必须介于 1 和 1000 之间。');
      return;
    }
    if (interval == null || interval < 0 || interval > 3600) {
      setState(() => _formError = '轮次间隔必须介于 0 和 3600 秒之间。');
      return;
    }
    setState(() => _formError = '');
    final approved = await showTestRunConfirmDialog(
      context: context,
      eyebrow: '确认自动化测试',
      title: '开始执行这个测试计划？',
      body:
          '用例：${testCase.displayName}\n执行 $count 轮，每轮间隔 ${_intervalController.text.trim()} 秒。\n\n开始前会自动完成必要检查；检查未通过时，计划不会开始。',
      confirmText: '确认开始',
    );
    if (!approved || !mounted) {
      return;
    }
    await ref
        .read(testRunsControllerProvider.notifier)
        .create(
          TestRunRequest(
            caseId: testCase.id,
            count: count,
            intervalSeconds: interval,
          ),
        );
  }
}

class _RunDetails extends ConsumerWidget {
  const _RunDetails({required this.runState});

  final TestRunsScreenState runState;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final run = runState.run;
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select((state) => state.endpoint),
    );
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: _SectionTitle(
                  icon: Icons.monitor_heart_outlined,
                  title: '当前运行',
                ),
              ),
              IconButton(
                tooltip: '重新读取运行状态',
                onPressed: runState.isBusy
                    ? null
                    : () => ref
                          .read(testRunsControllerProvider.notifier)
                          .refresh(),
                icon: runState.isRefreshing
                    ? const SizedBox(
                        width: 19,
                        height: 19,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh_rounded),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (run == null)
            const _NoRun()
          else ...[
            AletheiaFadeThrough(
              child: KeyedSubtree(
                key: ValueKey('run-status-${run.id}-${run.status.name}'),
                child: _RunStatusHeader(run: run),
              ),
            ),
            const SizedBox(height: 18),
            _RunProgress(run: run),
            if (run.liveProgress?.alert == true) ...[
              const SizedBox(height: 14),
              _StallAlert(run: run, pending: runState.isActionPending),
            ],
            const SizedBox(height: 16),
            AletheiaFadeThrough(
              child: KeyedSubtree(
                key: ValueKey(
                  'supervisor-${run.id}-${run.supervisorStateSignature}',
                ),
                child: _SupervisorReadiness(run: run),
              ),
            ),
            if (run.error != null || run.preflightMessage != null) ...[
              const SizedBox(height: 14),
              _RunNotice(
                text: run.error ?? run.preflightMessage!,
                isError:
                    run.status == AletheiaRunStatus.blocked ||
                    run.status == AletheiaRunStatus.failed,
              ),
            ],
            if (run.status == AletheiaRunStatus.awaitingRecovery) ...[
              const SizedBox(height: 16),
              _RecoveryAction(run: run, pending: runState.isActionPending),
            ],
            if (run.status.canCancel) ...[
              const SizedBox(height: 12),
              _CancelAction(run: run, pending: runState.isActionPending),
            ],
            if (run.attempts.isNotEmpty) ...[
              const SizedBox(height: 22),
              const Divider(),
              const SizedBox(height: 16),
              const Text(
                '已记录轮次',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 10),
              ...run.attempts.reversed
                  .take(6)
                  .map(
                    (attempt) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: _AttemptRow(
                        attempt: attempt,
                        runId: run.id,
                        endpoint: endpoint,
                      ),
                    ),
                  ),
            ],
            if (run.interventions.isNotEmpty) ...[
              const SizedBox(height: 14),
              _InterventionSummary(intervention: run.interventions.last),
            ],
          ],
        ],
      ),
    );
  }
}

class _SupervisorReadiness extends StatelessWidget {
  const _SupervisorReadiness({required this.run});

  final AletheiaRun run;

  @override
  Widget build(BuildContext context) {
    final nodes = run.supervisorNodes;
    final running = nodes.where((node) => node.isRunning).length;
    final hasRequiredIssue = nodes.any(
      (node) => node.required && !node.isRunning,
    );
    final summaryColor = nodes.isEmpty
        ? AletheiaTheme.textTertiary
        : hasRequiredIssue
        ? AletheiaTheme.warning
        : AletheiaTheme.mint;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceMuted,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: AletheiaTheme.border),
      ),
      child: Padding(
        padding: EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.account_tree_outlined,
                  size: 18,
                  color: AletheiaTheme.cyan,
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '运行依赖',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                Text(
                  nodes.isEmpty ? '等待预检' : '$running / ${nodes.length} 运行中',
                  style: TextStyle(
                    color: summaryColor,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            SizedBox(height: 4),
            Text(
              'Supervisor 节点状态随本次测试预检更新。',
              style: TextStyle(
                color: AletheiaTheme.textTertiary,
                fontSize: 12,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 10),
            if (nodes.isEmpty)
              const _SupervisorEmptyState()
            else
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 520 ? 2 : 1;
                  final itemWidth =
                      (constraints.maxWidth - (columns - 1) * 8) / columns;
                  return Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final node in nodes)
                        SizedBox(
                          width: itemWidth,
                          child: _SupervisorNodeRow(node: node),
                        ),
                    ],
                  );
                },
              ),
          ],
        ),
      ),
    );
  }
}

class _SupervisorEmptyState extends StatelessWidget {
  const _SupervisorEmptyState();

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(
        Icons.info_outline_rounded,
        size: 16,
        color: AletheiaTheme.textTertiary,
      ),
      SizedBox(width: 8),
      Expanded(
        child: Text(
          '开始测试后自动读取本机运行依赖。',
          style: TextStyle(color: AletheiaTheme.textSecondary, fontSize: 13),
        ),
      ),
    ],
  );
}

class _SupervisorNodeRow extends StatelessWidget {
  const _SupervisorNodeRow({required this.node});

  final RunSupervisorNode node;

  @override
  Widget build(BuildContext context) {
    final isTransitional =
        node.status == 'STARTING' ||
        node.status == 'STOPPING' ||
        node.status == 'BACKOFF';
    final color = node.isRunning
        ? AletheiaTheme.mint
        : isTransitional || !node.required
        ? AletheiaTheme.warning
        : AletheiaTheme.danger;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceRaised,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: .34)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        child: Row(
          children: [
            Icon(
              node.isRunning
                  ? Icons.check_circle_outline_rounded
                  : Icons.error_outline_rounded,
              color: color,
              size: 17,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    node.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    node.supervisor.isEmpty
                        ? (node.required ? '必需节点' : '可选节点')
                        : '${node.supervisor} · ${node.required ? '必需' : '可选'}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: AletheiaTheme.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Text(
              node.statusLabel,
              style: TextStyle(
                color: color,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RunStatusHeader extends StatelessWidget {
  const _RunStatusHeader({required this.run});

  final AletheiaRun run;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(run.status);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: color.withValues(alpha: .38)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Icon(_statusIcon(run.status), color: color),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    run.status.label,
                    style: TextStyle(color: color, fontWeight: FontWeight.w700),
                  ),
                  SizedBox(height: 3),
                  Text(
                    run.testCase.name.isNotEmpty
                        ? run.testCase.name
                        : run.testCase.filename,
                    style: TextStyle(color: AletheiaTheme.textSecondary),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            Text(
              'RUN\n${run.id}',
              textAlign: TextAlign.right,
              style: TextStyle(
                color: AletheiaTheme.textTertiary,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RunProgress extends StatelessWidget {
  const _RunProgress({required this.run});

  final AletheiaRun run;

  @override
  Widget build(BuildContext context) {
    final overall = run.requestedCount == 0
        ? 0.0
        : (run.summary.completed / run.requestedCount).clamp(0.0, 1.0);
    final live = run.liveProgress;
    final liveValue = live?.progressAvailable == true && live?.percent != null
        ? (live!.percent! / 100).clamp(0.0, 1.0)
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _ProgressLabel(
          label: '测试计划',
          value: '${run.summary.completed}/${run.requestedCount} 轮已完成',
        ),
        const SizedBox(height: 7),
        LinearProgressIndicator(value: overall),
        const SizedBox(height: 16),
        if (live?.visible == true) ...[
          _ProgressLabel(
            label: '当前轮轨迹',
            value: liveValue == null
                ? '等待可验证投影'
                : '${(liveValue * 100).round()}%',
          ),
          SizedBox(height: 7),
          LinearProgressIndicator(value: liveValue),
          if (live!.state.isNotEmpty) ...[
            SizedBox(height: 6),
            Text(
              live.state,
              style: TextStyle(color: AletheiaTheme.textTertiary, fontSize: 12),
            ),
          ],
        ],
        SizedBox(height: 16),
        Wrap(
          spacing: 9,
          runSpacing: 7,
          children: [
            _MetricChip(
              label: '通过',
              value: '${run.summary.passed}',
              color: AletheiaTheme.mint,
            ),
            _MetricChip(
              label: '失败',
              value: '${run.summary.failed}',
              color: AletheiaTheme.danger,
            ),
            _MetricChip(
              label: '通过率',
              value: '${run.summary.passRate.toStringAsFixed(1)}%',
              color: AletheiaTheme.cyan,
            ),
          ],
        ),
      ],
    );
  }
}

class _RecoveryAction extends ConsumerWidget {
  const _RecoveryAction({required this.run, required this.pending});

  final AletheiaRun run;
  final bool pending;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.warning.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: AletheiaTheme.warning.withValues(alpha: .38)),
      ),
      child: Padding(
        padding: EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.build_circle_outlined, color: AletheiaTheme.warning),
                SizedBox(width: 9),
                Text('需要人工恢复', style: TextStyle(fontWeight: FontWeight.w700)),
              ],
            ),
            SizedBox(height: 8),
            Text(
              '请先确认机器人已回到测试起点。继续后会重新检查测试条件。',
              style: TextStyle(color: AletheiaTheme.warning, height: 1.35),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              onPressed: pending ? null : () => _confirmResume(context, ref),
              icon: const Icon(Icons.play_circle_outline_rounded),
              label: const Text('确认恢复并继续'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmResume(BuildContext context, WidgetRef ref) async {
    final approved = await showTestRunConfirmDialog(
      context: context,
      eyebrow: '人工恢复确认',
      title: '机器人已经恢复到测试起点？',
      body: '继续后会从下一轮开始执行，并再次检查测试条件。',
      confirmText: '确认恢复并继续',
    );
    if (approved && context.mounted) {
      await ref.read(testRunsControllerProvider.notifier).resume();
    }
  }
}

/// This is a test-run intervention record, not a robot command surface.
/// Each option maps to the existing server-side stall workflow and requires a
/// deliberate confirmation before it is recorded against the active attempt.
class _StallAlert extends ConsumerWidget {
  const _StallAlert({required this.run, required this.pending});

  final AletheiaRun run;
  final bool pending;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final live = run.liveProgress!;
    final detail = live.alertReason.isEmpty ? '当前轮检测到持续停滞。' : live.alertReason;
    final seconds = live.stalledSeconds == null
        ? ''
        : ' 已持续 ${live.stalledSeconds!.round()} 秒。';
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.warning.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: AletheiaTheme.warning.withValues(alpha: .5)),
      ),
      child: Padding(
        padding: EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.warning_amber_rounded, color: AletheiaTheme.warning),
                SizedBox(width: 9),
                Text('需要人工处置', style: TextStyle(fontWeight: FontWeight.w700)),
              ],
            ),
            SizedBox(height: 7),
            Text(
              '$detail$seconds',
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: pending
                      ? null
                      : () => _confirm(
                          context,
                          ref,
                          action: 'continue_observing',
                          title: '继续观察当前轮？',
                          detail: '将关闭本次停滞提醒，并继续记录当前轮的状态。',
                          confirm: '继续观察',
                        ),
                  child: const Text('继续观察'),
                ),
                OutlinedButton(
                  onPressed: pending
                      ? null
                      : () => _confirm(
                          context,
                          ref,
                          action: 'released_estop',
                          title: '确认阻塞已解除？',
                          detail: '将记录人工确认，并继续观察当前轮。',
                          confirm: '已解除',
                        ),
                  child: Text('已解除阻塞'),
                ),
                FilledButton.tonal(
                  style: FilledButton.styleFrom(
                    foregroundColor: AletheiaTheme.danger,
                  ),
                  onPressed: pending
                      ? null
                      : () => _confirm(
                          context,
                          ref,
                          action: 'mark_attempt_failed',
                          title: '判定当前轮失败？',
                          detail: '当前服务调用返回后，测试将等待人工恢复；此处置会写入本次报告。',
                          confirm: '判定失败',
                          danger: true,
                        ),
                  child: const Text('判定本轮失败'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirm(
    BuildContext context,
    WidgetRef ref, {
    required String action,
    required String title,
    required String detail,
    required String confirm,
    bool danger = false,
  }) async {
    final approved = await showTestRunConfirmDialog(
      context: context,
      eyebrow: '停滞处置确认',
      title: title,
      body: detail,
      confirmText: confirm,
      danger: danger,
    );
    if (approved && context.mounted) {
      await ref.read(testRunsControllerProvider.notifier).stallAction(action);
    }
  }
}

class _CancelAction extends ConsumerWidget {
  const _CancelAction({required this.run, required this.pending});

  final AletheiaRun run;
  final bool pending;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return OutlinedButton.icon(
      style: OutlinedButton.styleFrom(
        foregroundColor: AletheiaTheme.danger,
        side: BorderSide(color: AletheiaTheme.danger),
      ),
      onPressed: pending ? null : () => _confirmCancel(context, ref),
      icon: const Icon(Icons.stop_circle_outlined),
      label: const Text('终止剩余测试轮次'),
    );
  }

  Future<void> _confirmCancel(BuildContext context, WidgetRef ref) async {
    final approved = await showTestRunConfirmDialog(
      context: context,
      eyebrow: '终止剩余测试',
      title: '确认终止尚未开始的轮次？',
      body: '当前轮结束后将停止后续轮次。',
      confirmText: '终止剩余轮次',
      danger: true,
    );
    if (approved && context.mounted) {
      await ref.read(testRunsControllerProvider.notifier).cancel();
    }
  }
}

class _AttemptRow extends StatelessWidget {
  const _AttemptRow({
    required this.attempt,
    required this.runId,
    required this.endpoint,
  });

  final RunAttempt attempt;
  final String runId;
  final RobotEndpoint? endpoint;

  @override
  Widget build(BuildContext context) {
    final passed = attempt.status == 'passed';
    final color = passed
        ? AletheiaTheme.mint
        : attempt.status == 'failed'
        ? AletheiaTheme.danger
        : AletheiaTheme.warning;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceMuted,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'T-${attempt.index.toString().padLeft(3, '0')}',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                SizedBox(width: 12),
                Expanded(
                  child: Text(
                    attempt.message.isEmpty ? '未提供服务反馈。' : attempt.message,
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      height: 1.3,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      attempt.status.toUpperCase(),
                      style: TextStyle(
                        color: color,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 3),
                    Text(
                      _durationLabel(attempt.durationSeconds),
                      style: TextStyle(
                        color: AletheiaTheme.textTertiary,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ],
            ),
            if (endpoint != null && attempt.trajectoryViews.isNotEmpty) ...[
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed: () => _showTrajectoryViews(context),
                icon: const Icon(Icons.route_outlined, size: 18),
                label: Text('查看 ${attempt.trajectoryViews.length} 份轨迹证据'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _showTrajectoryViews(BuildContext context) async {
    final endpoint = this.endpoint;
    if (endpoint == null) return;
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => SafeArea(
        child: Container(
          padding: EdgeInsets.fromLTRB(20, 12, 20, 24),
          decoration: BoxDecoration(
            color: AletheiaTheme.surface,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'T-${attempt.index.toString().padLeft(3, '0')} 轨迹证据',
                style: Theme.of(sheetContext).textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 6),
              Text(
                '在浏览器中查看只读地图轨迹 SVG。',
                style: TextStyle(color: AletheiaTheme.textSecondary),
              ),
              SizedBox(height: 12),
              ...attempt.trajectoryViews.map(
                (view) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.map_outlined, color: AletheiaTheme.cyan),
                  title: Text(view.label.isEmpty ? view.mapId : view.label),
                  trailing: const Icon(Icons.open_in_new_outlined),
                  onTap: () async {
                    final opened = await launchUrl(
                      endpoint.apiUri(
                        'api/runs/$runId/attempts/${attempt.index}/trajectory/${view.mapId}',
                      ),
                      mode: LaunchMode.inAppBrowserView,
                    );
                    if (!opened && sheetContext.mounted) {
                      ScaffoldMessenger.of(sheetContext).showSnackBar(
                        const SnackBar(content: Text('无法打开轨迹证据。')),
                      );
                    }
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InterventionSummary extends StatelessWidget {
  const _InterventionSummary({required this.intervention});

  final RunIntervention intervention;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceMuted,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: EdgeInsets.all(12),
        child: Text(
          '最近人工记录 · T-${intervention.attempt ?? 0}: ${intervention.detail}',
          style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.35),
        ),
      ),
    );
  }
}

class _NoRun extends StatelessWidget {
  const _NoRun();

  @override
  Widget build(BuildContext context) {
    return const _MutedBlock(
      icon: Icons.hourglass_empty_rounded,
      text: '尚未创建测试计划。选择用例并确认执行后，进度会在这里更新。',
    );
  }
}

class _SelectedCaseHint extends StatelessWidget {
  const _SelectedCaseHint({required this.testCase});

  final AletheiaTestCase testCase;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.cyan.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: EdgeInsets.all(11),
        child: Text(
          '${testCase.parameters.locationLabel}\n${testCase.filename}',
          style: TextStyle(
            color: AletheiaTheme.textSecondary,
            height: 1.35,
            fontSize: 12,
          ),
        ),
      ),
    );
  }
}

class _ProgressLabel extends StatelessWidget {
  const _ProgressLabel({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(label, style: TextStyle(fontWeight: FontWeight.w600)),
        ),
        Text(
          value,
          style: TextStyle(color: AletheiaTheme.textSecondary, fontSize: 12),
        ),
      ],
    );
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        child: Text(
          '$label $value',
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

class _RunNotice extends StatelessWidget {
  const _RunNotice({required this.text, required this.isError});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final color = isError ? AletheiaTheme.danger : AletheiaTheme.warning;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              isError
                  ? Icons.error_outline_rounded
                  : Icons.info_outline_rounded,
              color: color,
              size: 18,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Text(text, style: TextStyle(color: color, height: 1.35)),
            ),
          ],
        ),
      ),
    );
  }
}

class _MutedBlock extends StatelessWidget {
  const _MutedBlock({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceMuted,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: EdgeInsets.all(15),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: AletheiaTheme.textTertiary),
            SizedBox(width: 10),
            Expanded(
              child: Text(
                text,
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surface,
        borderRadius: BorderRadius.circular(AletheiaTheme.panelRadius),
        border: Border.all(color: AletheiaTheme.border),
      ),
      child: Padding(padding: const EdgeInsets.all(20), child: child),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.icon, required this.title});

  final IconData icon;
  final String title;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 18, color: AletheiaTheme.cyan),
        const SizedBox(width: 8),
        Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
      ],
    );
  }
}

class _PageEyebrow extends StatelessWidget {
  const _PageEyebrow({required this.icon, required this.text});

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

class _RunConnectionRequired extends StatelessWidget {
  const _RunConnectionRequired();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: const _MutedBlock(
            icon: Icons.lan_outlined,
            text: '请先到“机器人”页连接机器人，再创建或查看测试计划。',
          ),
        ),
      ),
    );
  }
}

/// Shared production confirmation dialog for test-run actions.
///
/// It is also surfaced by the debug gallery so UI review never forks this
/// critical confirmation treatment from the real application.
Future<bool> showTestRunConfirmDialog({
  required BuildContext context,
  required String eyebrow,
  required String title,
  required String body,
  required String confirmText,
  bool danger = false,
}) async {
  final approved = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            eyebrow,
            style: Theme.of(context).textTheme.labelMedium
                ?.copyWith(color: AletheiaTheme.textSecondary),
          ),
          const SizedBox(height: 8),
          Text(title),
        ],
      ),
      content: Text(body, style: const TextStyle(height: 1.45)),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: Text('返回'),
        ),
        FilledButton(
          style: danger
              ? FilledButton.styleFrom(
                  backgroundColor: AletheiaTheme.danger,
                  foregroundColor: const Color(0xFF32110F),
                )
              : null,
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: Text(confirmText),
        ),
      ],
    ),
  );
  return approved ?? false;
}

Color _statusColor(AletheiaRunStatus status) => switch (status) {
  AletheiaRunStatus.running ||
  AletheiaRunStatus.completed => AletheiaTheme.mint,
  AletheiaRunStatus.awaitingRecovery ||
  AletheiaRunStatus.recovering => AletheiaTheme.warning,
  AletheiaRunStatus.failed || AletheiaRunStatus.blocked => AletheiaTheme.danger,
  _ => AletheiaTheme.cyan,
};

IconData _statusIcon(AletheiaRunStatus status) => switch (status) {
  AletheiaRunStatus.running => Icons.play_circle_rounded,
  AletheiaRunStatus.completed => Icons.check_circle_rounded,
  AletheiaRunStatus.awaitingRecovery => Icons.build_circle_outlined,
  AletheiaRunStatus.recovering => Icons.sync_rounded,
  AletheiaRunStatus.failed || AletheiaRunStatus.blocked => Icons.error_rounded,
  AletheiaRunStatus.cancelled ||
  AletheiaRunStatus.cancelling => Icons.stop_circle_rounded,
  _ => Icons.hourglass_top_rounded,
};

String _durationLabel(double seconds) {
  if (seconds < 60) {
    return '${seconds.round()} 秒';
  }
  return '${(seconds / 60).toStringAsFixed(1)} 分';
}
