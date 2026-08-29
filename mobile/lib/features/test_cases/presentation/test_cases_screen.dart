import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../application/test_cases_controller.dart';
import '../data/test_cases_repository.dart';
import '../domain/aletheia_test_case.dart';
import '../../test_runs/presentation/test_runs_screen.dart';
import '../../scenario_setup/application/scenario_setup_controller.dart';
import '../../scenario_setup/domain/scenario_setup.dart';
import '../../scenario_setup/presentation/scenario_setup_screen.dart';

class TestCasesScreen extends ConsumerWidget {
  const TestCasesScreen({super.key});

  static const routePath = '/tools/testing/cases';
  static const legacyRoutePath = '/cases';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    final catalog = ref.watch(caseCatalogProvider);

    if (!connected) {
      return const _ConnectionRequired();
    }

    return SafeArea(
      top: false,
      child: catalog.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _CatalogError(
          message: error.toString(),
          onRetry: () => ref.read(caseCatalogProvider.notifier).refresh(),
        ),
        data: (data) => _CaseCatalogBody(catalog: data),
      ),
    );
  }
}

class _CaseCatalogBody extends ConsumerWidget {
  const _CaseCatalogBody({required this.catalog});

  final CaseCatalog catalog;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RefreshIndicator(
      onRefresh: () => ref.read(caseCatalogProvider.notifier).refresh(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1120),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _PageEyebrow(
                    icon: Icons.inventory_2_outlined,
                    text: '用例库',
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '浏览可执行测试内容',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      letterSpacing: -.4,
                    ),
                  ),
                  SizedBox(height: 7),
                  Text(
                    '选择测试内容，查看说明后开始自动化测试。',
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 20),
                  _CaseLibraryActions(),
                  const SizedBox(height: 16),
                  _CatalogSummary(
                    caseCount: catalog.cases.length,
                    issueCount: catalog.validationIssues.length,
                  ),
                  if (catalog.validationIssues.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    _ValidationIssues(issues: catalog.validationIssues),
                  ],
                  const SizedBox(height: 20),
                  if (catalog.cases.isEmpty)
                    const _EmptyCatalog()
                  else
                    ...catalog.cases.map(
                      (testCase) => Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: _CaseCard(testCase: testCase),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CaseCard extends ConsumerWidget {
  const _CaseCard({required this.testCase});

  final AletheiaTestCase testCase;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    void selectAndOpenRun() {
      ref.read(selectedCaseIdProvider.notifier).select(testCase.id);
      context.go(TestRunsScreen.routePath);
    }

    Future<void> manage() async {
      final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
      if (endpoint == null) return;
      final profiles = await ref.read(scenarioSetupProvider.future);
      if (!context.mounted) return;
      final changed = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (context) => _CaseManagementSheet(
          testCase: testCase,
          profiles: profiles.document.profiles,
          selectedProfileId:
              profiles.document.caseBindings[testCase.id] as String? ?? '',
        ),
      );
      if (changed == true) {
        ref.read(caseCatalogProvider.notifier).refresh();
      }
    }

    return Material(
      color: AletheiaTheme.surface,
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      child: InkWell(
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        onTap: selectAndOpenRun,
        child: Container(
          padding: EdgeInsets.all(18),
          decoration: BoxDecoration(
            border: Border.all(color: AletheiaTheme.border),
            borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 620;
              final details = Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          testCase.displayName,
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ),
                      _LifecycleChip(value: testCase.management.lifecycle),
                    ],
                  ),
                  SizedBox(height: 6),
                  Text(
                    testCase.parameters.locationLabel,
                    style: TextStyle(color: AletheiaTheme.textSecondary),
                  ),
                  SizedBox(height: 6),
                  Text(
                    testCase.filename,
                    style: TextStyle(
                      color: AletheiaTheme.textTertiary,
                      fontSize: 12,
                    ),
                  ),
                  if (testCase.management.summary.isNotEmpty) ...[
                    SizedBox(height: 12),
                    Text(
                      testCase.management.summary,
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        height: 1.35,
                      ),
                    ),
                  ],
                  if (testCase.management.tags.isNotEmpty) ...[
                    const SizedBox(height: 13),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: testCase.management.tags
                          .map((tag) => _TagChip(label: tag))
                          .toList(growable: false),
                    ),
                  ],
                ],
              );
              final action = FilledButton.tonalIcon(
                onPressed: selectAndOpenRun,
                icon: const Icon(Icons.arrow_forward_rounded),
                label: const Text('用于测试'),
              );
              final manageAction = OutlinedButton.icon(
                onPressed: manage,
                icon: const Icon(Icons.tune_outlined),
                label: const Text('管理'),
              );
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    details,
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(child: manageAction),
                        const SizedBox(width: 10),
                        Expanded(child: action),
                      ],
                    ),
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(child: details),
                  const SizedBox(width: 24),
                  SizedBox(width: 112, child: manageAction),
                  const SizedBox(width: 10),
                  SizedBox(width: 132, child: action),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _CaseLibraryActions extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      OutlinedButton.icon(
        onPressed: () => _import(context, ref, false),
        icon: const Icon(Icons.upload_file_outlined),
        label: const Text('导入任务 JSON'),
      ),
      OutlinedButton.icon(
        onPressed: () => _import(context, ref, true),
        icon: const Icon(Icons.inventory_2_outlined),
        label: const Text('导入用例包'),
      ),
      OutlinedButton.icon(
        onPressed: () => context.go(ScenarioSetupScreen.routePath),
        icon: const Icon(Icons.auto_awesome_motion_outlined),
        label: const Text('场景方案'),
      ),
    ],
  );

  Future<void> _import(
    BuildContext context,
    WidgetRef ref,
    bool package,
  ) async {
    final selected = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: package ? const ['zip'] : const ['json'],
      withData: true,
    );
    final file = selected != null && selected.files.isNotEmpty
        ? selected.files.first
        : null;
    final bytes = file?.bytes;
    if (file == null || bytes == null) return;
    if (bytes.isEmpty ||
        bytes.length > 8 * 1024 * 1024 ||
        (package && !file.name.toLowerCase().endsWith('.rycase.zip'))) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              package
                  ? '请选择小于 8 MiB 的 .rycase.zip 用例包。'
                  : '请选择小于 8 MiB 的 JSON 用例文件。',
            ),
          ),
        );
      }
      return;
    }
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    try {
      final message = await ref
          .read(testCasesRepositoryProvider)
          .importFile(
            endpoint,
            bytes: bytes,
            filename: file.name,
            isPackage: package,
          );
      ref.read(caseCatalogProvider.notifier).refresh();
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(message)));
      }
    } catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('导入失败：$error')));
      }
    }
  }
}

class _CaseManagementSheet extends ConsumerStatefulWidget {
  const _CaseManagementSheet({
    required this.testCase,
    required this.profiles,
    required this.selectedProfileId,
  });
  final AletheiaTestCase testCase;
  final List<ScenarioProfile> profiles;
  final String selectedProfileId;
  @override
  ConsumerState<_CaseManagementSheet> createState() =>
      _CaseManagementSheetState();
}

class _CaseManagementSheetState extends ConsumerState<_CaseManagementSheet> {
  late final TextEditingController _alias = TextEditingController(
    text: widget.testCase.alias,
  );
  late final TextEditingController _version = TextEditingController(
    text: widget.testCase.management.version,
  );
  late final TextEditingController _tags = TextEditingController(
    text: widget.testCase.management.tags.join(', '),
  );
  late final TextEditingController _summary = TextEditingController(
    text: widget.testCase.management.summary,
  );
  late String _lifecycle = widget.testCase.management.lifecycle;
  late String _profileId = widget.selectedProfileId;
  bool _saving = false;
  @override
  void dispose() {
    _alias.dispose();
    _version.dispose();
    _tags.dispose();
    _summary.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving) return;
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    setState(() => _saving = true);
    try {
      await ref
          .read(testCasesRepositoryProvider)
          .saveManagement(
            endpoint,
            widget.testCase,
            alias: _alias.text,
            version: _version.text,
            lifecycle: _lifecycle,
            tags: _tags.text
                .split(',')
                .map((item) => item.trim())
                .where((item) => item.isNotEmpty)
                .toList(growable: false),
            summary: _summary.text,
          );
      await ref
          .read(scenarioSetupRepositoryProvider)
          .bindCase(endpoint, widget.testCase.id, _profileId);
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('保存失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _export() async {
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    final uri = endpoint.apiUri('api/cases/${widget.testCase.id}/export');
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!opened && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('无法开始下载用例包。')));
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: DraggableScrollableSheet(
      initialChildSize: .78,
      minChildSize: .5,
      maxChildSize: .94,
      builder: (context, controller) => Material(
        color: AletheiaTheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
        child: ListView(
          controller: controller,
          padding: EdgeInsets.fromLTRB(20, 14, 20, 28),
          children: [
            Center(
              child: Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: AletheiaTheme.border,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              '用例管理与交付',
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            SizedBox(height: 4),
            Text(
              widget.testCase.filename,
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _alias,
              decoration: const InputDecoration(labelText: '显示别名'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _version,
              decoration: const InputDecoration(labelText: '版本'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _lifecycle,
              decoration: const InputDecoration(labelText: '状态'),
              items:
                  const [
                        ('draft', '草拟'),
                        ('local_verified', '本机已验证'),
                        ('published', '可交付'),
                        ('deprecated', '已停用'),
                      ]
                      .map(
                        (item) => DropdownMenuItem(
                          value: item.$1,
                          child: Text(item.$2),
                        ),
                      )
                      .toList(),
              onChanged: (value) =>
                  setState(() => _lifecycle = value ?? _lifecycle),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _tags,
              decoration: const InputDecoration(
                labelText: '标签',
                helperText: '多个标签用英文逗号分隔',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _summary,
              minLines: 3,
              maxLines: 5,
              decoration: const InputDecoration(labelText: '说明'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _profileId,
              decoration: const InputDecoration(labelText: '场景方案'),
              items: [
                const DropdownMenuItem(value: '', child: Text('未绑定（常规配置）')),
                ...widget.profiles.map(
                  (item) =>
                      DropdownMenuItem(value: item.id, child: Text(item.name)),
                ),
              ],
              onChanged: (value) => setState(() => _profileId = value ?? ''),
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: _export,
              icon: const Icon(Icons.download_outlined),
              label: const Text('导出 .rycase.zip 用例包'),
            ),
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.save_outlined),
              label: Text(_saving ? '正在保存…' : '保存管理信息'),
            ),
          ],
        ),
      ),
    ),
  );
}

class _CatalogSummary extends StatelessWidget {
  const _CatalogSummary({required this.caseCount, required this.issueCount});

  final int caseCount;
  final int issueCount;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _StatTile(
          label: '可执行用例',
          value: '$caseCount',
          color: AletheiaTheme.mint,
        ),
        SizedBox(width: 12),
        _StatTile(
          label: '校验提示',
          value: '$issueCount',
          color: issueCount == 0 ? AletheiaTheme.cyan : AletheiaTheme.warning,
        ),
      ],
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: color.withValues(alpha: .09),
          borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
          border: Border.all(color: color.withValues(alpha: .28)),
        ),
        child: Padding(
          padding: EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: TextStyle(color: AletheiaTheme.textSecondary)),
              const SizedBox(height: 5),
              Text(
                value,
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(color: color, fontWeight: FontWeight.w700),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ValidationIssues extends StatelessWidget {
  const _ValidationIssues({required this.issues});

  final List<CaseValidationIssue> issues;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.warning.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: AletheiaTheme.warning.withValues(alpha: .35)),
      ),
      child: Padding(
        padding: EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.warning_amber_rounded, color: AletheiaTheme.warning),
                SizedBox(width: 8),
                Text(
                  '有些测试内容暂不可用',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
            ),
            SizedBox(height: 9),
            ...issues.map(
              (issue) => Padding(
                padding: EdgeInsets.only(top: 5),
                child: Text(
                  '${issue.filename}：${issue.message}',
                  style: TextStyle(color: AletheiaTheme.warning, height: 1.3),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyCatalog extends StatelessWidget {
  const _EmptyCatalog();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surface,
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        border: Border.all(color: AletheiaTheme.border),
      ),
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Row(
          children: [
            Icon(Icons.folder_off_outlined, color: AletheiaTheme.textTertiary),
            SizedBox(width: 12),
            Expanded(
              child: Text(
                '当前没有可执行的测试内容。请在机器人管理端添加或检查测试内容。',
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

class _CatalogError extends StatelessWidget {
  const _CatalogError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: 460),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.error_outline_rounded,
                color: AletheiaTheme.danger,
                size: 34,
              ),
              const SizedBox(height: 12),
              const Text(
                '无法读取测试用例',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('重新读取'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: 460),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.lan_outlined, color: AletheiaTheme.cyan, size: 34),
              const SizedBox(height: 12),
              Text(
                '先连接机器人',
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 7),
              Text(
                '连接后即可查看可执行的测试内容。',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
      ),
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

class _LifecycleChip extends StatelessWidget {
  const _LifecycleChip({required this.value});

  final String value;

  @override
  Widget build(BuildContext context) {
    final normalized = value.toLowerCase();
    final color = normalized == 'released' || normalized == 'active'
        ? AletheiaTheme.mint
        : normalized == 'deprecated'
        ? AletheiaTheme.warning
        : AletheiaTheme.cyan;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        child: Text(
          value.toUpperCase(),
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

class _TagChip extends StatelessWidget {
  const _TagChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceMuted,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Text(label, style: const TextStyle(fontSize: 11)),
      ),
    );
  }
}
