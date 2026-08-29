import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/scenario_setup_controller.dart';
import '../domain/scenario_setup.dart';

/// Mobile workflow for the existing guarded scenario setup transaction.
/// Applying and restoring remain explicit separate actions because they can
/// change only the server's registered startup arguments.
class ScenarioSetupScreen extends ConsumerWidget {
  const ScenarioSetupScreen({super.key});
  static const routePath = '/tools/scenario-setup';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) return const _ConnectionRequired();
    final state = ref.watch(scenarioSetupProvider);
    return SafeArea(
      top: false,
      child: state.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _StateMessage(
          title: '无法读取场景方案',
          detail: '$error',
          action: () => ref.invalidate(scenarioSetupProvider),
        ),
        data: (value) => _ScenarioEditor(initial: value),
      ),
    );
  }
}

class _ScenarioEditor extends ConsumerStatefulWidget {
  const _ScenarioEditor({required this.initial});
  final ScenarioSetupStatus initial;
  @override
  ConsumerState<_ScenarioEditor> createState() => _ScenarioEditorState();
}

class _ScenarioEditorState extends ConsumerState<_ScenarioEditor> {
  late ScenarioDocument _document;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _document = widget.initial.document;
  }

  Future<void> _refresh() async {
    ref.invalidate(scenarioSetupProvider);
    await ref.read(scenarioSetupProvider.future);
  }

  Future<void> _save() async {
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null || _saving) return;
    setState(() => _saving = true);
    try {
      final status = await ref
          .read(scenarioSetupRepositoryProvider)
          .save(endpoint, _document);
      if (!mounted) return;
      setState(() => _document = status.document);
      ref.invalidate(scenarioSetupProvider);
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('场景方案已保存。')));
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('保存失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _editProfile([ScenarioProfile? profile]) async {
    final result = await showModalBottomSheet<ScenarioProfile>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _ProfileEditorSheet(
        profile: profile,
        endpoint: ref.read(robotConnectionControllerProvider).endpoint,
      ),
    );
    if (result == null || !mounted) return;
    setState(() {
      final profiles = List<ScenarioProfile>.of(_document.profiles);
      final index = profiles.indexWhere((item) => item.id == result.id);
      if (index < 0) {
        profiles.add(result);
      } else {
        profiles[index] = result;
      }
      _document = ScenarioDocument(
        startupScript: _document.startupScript,
        searchDirectories: _document.searchDirectories,
        bindings: _document.bindings,
        profiles: profiles,
        caseBindings: _document.caseBindings,
      );
    });
  }

  Future<void> _preview(ScenarioProfile profile) async {
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    try {
      final preview = await ref
          .read(scenarioSetupRepositoryProvider)
          .preview(endpoint, _document, profile.id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (context) => _PreviewSheet(preview: preview),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('无法生成预览：$error')));
      }
    }
  }

  Future<void> _apply(ScenarioProfile profile) async {
    final confirmed = await _confirm(
      title: '应用场景方案？',
      detail: '“${profile.name}”将修改机器人上已登记的启动参数。系统会先保存可验证备份，测试结束后可恢复常规配置。',
      confirm: '应用方案',
    );
    if (!confirmed) return;
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    try {
      await ref
          .read(scenarioSetupRepositoryProvider)
          .apply(endpoint, profile.id);
      if (!mounted) return;
      await _refresh();
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('场景方案已应用。')));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('应用失败：$error')));
      }
    }
  }

  Future<void> _restore() async {
    final confirmed = await _confirm(
      title: '恢复常规配置？',
      detail: '仅恢复当前 Aletheia 事务备份中记录的受控启动参数。若脚本被外部修改，机器人会拒绝覆盖。',
      confirm: '恢复配置',
      danger: true,
    );
    if (!confirmed) return;
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    try {
      await ref.read(scenarioSetupRepositoryProvider).restore(endpoint);
      if (!mounted) return;
      await _refresh();
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('已恢复常规启动配置。')));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('恢复失败：$error')));
      }
    }
  }

  Future<bool> _confirm({
    required String title,
    required String detail,
    required String confirm,
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
  Widget build(BuildContext context) {
    final backup = widget.initial.activeBackup;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          LayoutBuilder(
            builder: (context, constraints) => Center(
              child: SizedBox(
                // ListView lets its children choose their horizontal extent.
                // Give responsive rows a concrete working width first.
                width: constraints.maxWidth > 880 ? 880 : constraints.maxWidth,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const _Eyebrow(
                      icon: Icons.tune_outlined,
                      text: '工具 / 场景前置配置',
                    ),
                    const SizedBox(height: 10),
                    Text(
                      '场景前置配置',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: -.4,
                          ),
                    ),
                    SizedBox(height: 7),
                    Text(
                      '为测试用例准备受控启动参数。先预览，再保存或应用。',
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _Panel(
                      title: '启动脚本与恢复保护',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _InfoRow(
                            label: '启动脚本',
                            value: _document.startupScript.isEmpty
                                ? '未配置'
                                : _document.startupScript,
                          ),
                          _InfoRow(
                            label: '可写状态',
                            value: widget.initial.inspection.writable
                                ? '可应用受控更改'
                                : '不可写或未找到',
                            tone: widget.initial.inspection.writable
                                ? AletheiaTheme.mint
                                : AletheiaTheme.warning,
                          ),
                          if (backup != null) ...[
                            const SizedBox(height: 10),
                            _PendingBackup(
                              profile: backup.profileName,
                              createdAt: backup.createdAt,
                              onRestore: _restore,
                            ),
                          ] else
                            Padding(
                              padding: EdgeInsets.only(top: 10),
                              child: Text(
                                '当前为常规启动配置。',
                                style: TextStyle(
                                  color: AletheiaTheme.textSecondary,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '场景方案',
                      style: Theme.of(context).textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: () => _editProfile(),
                      icon: const Icon(Icons.add),
                      label: const Text('添加方案'),
                    ),
                    const SizedBox(height: 10),
                    if (_document.profiles.isEmpty)
                      const _StateMessage(
                        title: '尚未添加场景方案',
                        detail: '添加方案后选择受控 FCRP 启动文件与定位 YAML。',
                      )
                    else
                      ..._document.profiles.map(
                        (profile) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _ProfileCard(
                            profile: profile,
                            onEdit: () => _editProfile(profile),
                            onPreview: () => _preview(profile),
                            onApply: () => _apply(profile),
                            onRemove: () {
                              setState(() {
                                _document = ScenarioDocument(
                                  startupScript: _document.startupScript,
                                  searchDirectories:
                                      _document.searchDirectories,
                                  bindings: _document.bindings,
                                  profiles: _document.profiles
                                      .where((item) => item.id != profile.id)
                                      .toList(growable: false),
                                  caseBindings: Map.of(_document.caseBindings)
                                    ..removeWhere(
                                      (_, value) => value == profile.id,
                                    ),
                                );
                              });
                            },
                          ),
                        ),
                      ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _saving ? null : _save,
                        icon: _saving
                            ? const SizedBox.square(
                                dimension: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.save_outlined),
                        label: Text(_saving ? '正在保存…' : '保存方案库'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfileEditorSheet extends ConsumerStatefulWidget {
  const _ProfileEditorSheet({this.profile, required this.endpoint});
  final ScenarioProfile? profile;
  final dynamic endpoint;

  @override
  ConsumerState<_ProfileEditorSheet> createState() =>
      _ProfileEditorSheetState();
}

class _ProfileEditorSheetState extends ConsumerState<_ProfileEditorSheet> {
  late final TextEditingController _name = TextEditingController(
    text: widget.profile?.name ?? '新场景方案',
  );
  late final TextEditingController _fcrp = TextEditingController(
    text: widget.profile?.fcrpLaunch ?? '',
  );
  late final TextEditingController _lightning = TextEditingController(
    text: widget.profile?.lightningConfig ?? '',
  );

  @override
  void dispose() {
    _name.dispose();
    _fcrp.dispose();
    _lightning.dispose();
    super.dispose();
  }

  Future<void> _browse(String kind, TextEditingController target) async {
    if (widget.endpoint == null) return;
    final picked = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _FileBrowserSheet(
        kind: kind,
        initialPath: target.text,
        endpoint: widget.endpoint,
      ),
    );
    if (picked != null) target.text = picked;
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: Material(
        color: AletheiaTheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                widget.profile == null ? '添加场景方案' : '编辑场景方案',
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _name,
                decoration: const InputDecoration(labelText: '方案名称'),
              ),
              const SizedBox(height: 12),
              _BrowseField(
                label: 'FCRP 启动文件',
                controller: _fcrp,
                action: () => _browse('fcrp', _fcrp),
              ),
              const SizedBox(height: 12),
              _BrowseField(
                label: 'lightning 定位 YAML',
                controller: _lightning,
                action: () => _browse('lightning', _lightning),
              ),
              const SizedBox(height: 18),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () {
                    if (_name.text.trim().isEmpty ||
                        _fcrp.text.trim().isEmpty ||
                        _lightning.text.trim().isEmpty) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('请完整选择方案名称、FCRP 文件和定位 YAML。'),
                        ),
                      );
                      return;
                    }
                    Navigator.pop(
                      context,
                      ScenarioProfile(
                        id:
                            widget.profile?.id ??
                            'profile-${DateTime.now().millisecondsSinceEpoch}',
                        name: _name.text.trim(),
                        fcrpLaunch: _fcrp.text.trim(),
                        lightningConfig: _lightning.text.trim(),
                      ),
                    );
                  },
                  child: const Text('完成'),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _FileBrowserSheet extends ConsumerStatefulWidget {
  const _FileBrowserSheet({
    required this.kind,
    required this.initialPath,
    required this.endpoint,
  });
  final String kind;
  final String initialPath;
  final dynamic endpoint;
  @override
  ConsumerState<_FileBrowserSheet> createState() => _FileBrowserSheetState();
}

class _FileBrowserSheetState extends ConsumerState<_FileBrowserSheet> {
  ScenarioFileBrowser? _browser;
  Object? _error;
  late String _path = widget.initialPath;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load([String? path]) async {
    setState(() {
      _browser = null;
      _error = null;
    });
    try {
      final result = await ref
          .read(scenarioSetupRepositoryProvider)
          .browse(widget.endpoint, kind: widget.kind, path: path ?? _path);
      if (mounted) {
        setState(() {
          _path = result.path;
          _browser = result;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = error);
      }
    }
  }

  Future<void> _previewFile(ScenarioFileEntry item) async {
    try {
      final preview = await ref
          .read(scenarioSetupRepositoryProvider)
          .readFile(widget.endpoint, item.path);
      if (!mounted) return;
      final selected = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        builder: (context) => ScenarioFilePreviewSheet(preview: preview),
      );
      if (selected == true && mounted) {
        Navigator.pop(context, item.path);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('无法预览文件：$error')));
      }
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: DraggableScrollableSheet(
      initialChildSize: .72,
      minChildSize: .45,
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
              widget.kind == 'fcrp' ? '选择 FCRP 启动文件' : '选择 lightning 定位 YAML',
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            SizedBox(height: 6),
            Text(
              _browser?.path ?? '正在读取受控目录…',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                fontSize: 12,
              ),
            ),
            if (_browser?.parent != null)
              TextButton.icon(
                onPressed: () => _load(_browser!.parent),
                icon: const Icon(Icons.arrow_upward),
                label: const Text('上级目录'),
              ),
            if (_error != null)
              _StateMessage(title: '无法读取目录', detail: '$_error', action: _load),
            if (_browser == null && _error == null)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
            ...?_browser?.directories.map(
              (item) => ListTile(
                leading: Icon(Icons.folder_outlined, color: AletheiaTheme.cyan),
                title: Text(item.name),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _load(item.path),
              ),
            ),
            ...?_browser?.files.map(
              (item) => ListTile(
                leading: const Icon(Icons.description_outlined),
                title: Text(item.name),
                subtitle: item.size == null
                    ? null
                    : Text('${(item.size! / 1024).toStringAsFixed(1)} KiB'),
                trailing: const Icon(Icons.visibility_outlined),
                onTap: () => _previewFile(item),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _BrowseField extends StatelessWidget {
  const _BrowseField({
    required this.label,
    required this.controller,
    required this.action,
  });
  final String label;
  final TextEditingController controller;
  final VoidCallback action;
  @override
  Widget build(BuildContext context) => TextField(
    controller: controller,
    readOnly: true,
    maxLines: 2,
    decoration: InputDecoration(
      labelText: label,
      suffixIcon: IconButton(
        icon: const Icon(Icons.folder_open_outlined),
        tooltip: '浏览受控目录',
        onPressed: action,
      ),
    ),
  );
}

class _PreviewSheet extends StatelessWidget {
  const _PreviewSheet({required this.preview});
  final ScenarioPreview preview;

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: DraggableScrollableSheet(
      initialChildSize: .82,
      minChildSize: .45,
      maxChildSize: .96,
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
              '启动脚本模拟预览',
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            SizedBox(height: 6),
            Text(
              preview.changed ? '未写入机器人；应用后会替换受控参数。' : '该方案不会改变当前启动参数。',
              style: TextStyle(
                color: preview.changed
                    ? AletheiaTheme.warning
                    : AletheiaTheme.textSecondary,
              ),
            ),
            SizedBox(height: 12),
            SelectableText(
              preview.content,
              style: TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.35,
                color: AletheiaTheme.textSecondary,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

/// The guarded file preview used by scenario setup and the Debug UI Gallery.
/// Keeping this public lets the Gallery render the exact production surface.
class ScenarioFilePreviewSheet extends StatelessWidget {
  const ScenarioFilePreviewSheet({required this.preview, super.key});

  final ScenarioFilePreview preview;

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: DraggableScrollableSheet(
      initialChildSize: .86,
      minChildSize: .48,
      maxChildSize: .96,
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
              '文件预览',
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            SizedBox(height: 6),
            Text(
              preview.path,
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                fontSize: 12,
              ),
            ),
            SizedBox(height: 8),
            Text(
              '大小 ${(preview.size / 1024).toStringAsFixed(1)} KiB\nSHA-256 ${preview.sha256.length > 12 ? preview.sha256.substring(0, 12) : preview.sha256}',
              style: TextStyle(color: AletheiaTheme.textTertiary, fontSize: 12),
            ),
            SizedBox(height: 16),
            SelectableText(
              preview.content,
              style: TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.35,
                color: AletheiaTheme.textSecondary,
              ),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: () => Navigator.pop(context, true),
              icon: const Icon(Icons.check_outlined),
              label: const Text('选择此文件'),
            ),
          ],
        ),
      ),
    ),
  );
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({
    required this.profile,
    required this.onEdit,
    required this.onPreview,
    required this.onApply,
    required this.onRemove,
  });
  final ScenarioProfile profile;
  final VoidCallback onEdit;
  final VoidCallback onPreview;
  final VoidCallback onApply;
  final VoidCallback onRemove;
  @override
  Widget build(BuildContext context) => _Panel(
    title: profile.name,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          profile.fcrpLaunch,
          style: TextStyle(color: AletheiaTheme.textSecondary, fontSize: 12),
        ),
        SizedBox(height: 4),
        Text(
          profile.lightningConfig,
          style: TextStyle(color: AletheiaTheme.textSecondary, fontSize: 12),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: onPreview,
              icon: const Icon(Icons.visibility_outlined),
              label: const Text('预览'),
            ),
            OutlinedButton.icon(
              onPressed: onEdit,
              icon: const Icon(Icons.edit_outlined),
              label: const Text('编辑'),
            ),
            FilledButton.icon(
              onPressed: onApply,
              icon: const Icon(Icons.play_arrow_outlined),
              label: const Text('应用'),
            ),
            TextButton(onPressed: onRemove, child: const Text('删除')),
          ],
        ),
      ],
    ),
  );
}

class _PendingBackup extends StatelessWidget {
  const _PendingBackup({
    required this.profile,
    required this.createdAt,
    required this.onRestore,
  });
  final String profile;
  final String createdAt;
  final VoidCallback onRestore;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.warning.withValues(alpha: .1),
      border: Border.all(color: AletheiaTheme.warning.withValues(alpha: .45)),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Padding(
      padding: EdgeInsets.all(12),
      child: Row(
        children: [
          Icon(Icons.warning_amber_rounded, color: AletheiaTheme.warning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              '待恢复：$profile\n$createdAt',
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                height: 1.35,
              ),
            ),
          ),
          TextButton(onPressed: onRestore, child: const Text('恢复')),
        ],
      ),
    ),
  );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value, this.tone});
  final String label;
  final String value;
  final Color? tone;
  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.only(bottom: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 76,
          child: Text(
            label,
            style: TextStyle(color: AletheiaTheme.textTertiary),
          ),
        ),
        Expanded(
          child: SelectableText(
            value,
            style: TextStyle(color: tone ?? AletheiaTheme.textSecondary),
          ),
        ),
      ],
    ),
  );
}

class _Panel extends StatelessWidget {
  const _Panel({required this.title, required this.child});
  final String title;
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
          const SizedBox(height: 14),
          child,
        ],
      ),
    ),
  );
}

class _Eyebrow extends StatelessWidget {
  const _Eyebrow({required this.icon, required this.text});
  final IconData icon;
  final String text;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, size: 17, color: AletheiaTheme.cyan),
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

class _StateMessage extends StatelessWidget {
  const _StateMessage({required this.title, required this.detail, this.action});
  final String title;
  final String detail;
  final VoidCallback? action;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surface,
      border: Border.all(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    ),
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(fontWeight: FontWeight.w700)),
          SizedBox(height: 6),
          Text(
            detail,
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
          ),
          if (action != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: action, child: const Text('重试')),
          ],
        ],
      ),
    ),
  );
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: _StateMessage(
        title: '先连接机器人',
        detail: '连接机器人后即可管理受控场景前置方案。',
        action: () => context.go(RobotConnectionScreen.routePath),
      ),
    ),
  );
}
