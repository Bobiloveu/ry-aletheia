import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/runtime_settings_controller.dart';
import '../domain/runtime_settings.dart';

/// Compact native editor for the existing console.json contract.
///
/// The page does not expose a shell, ROS graph, arbitrary paths or any direct
/// supervisor action. It only saves the server-validated fields already
/// available from the web runtime-settings page.
class RuntimeSettingsScreen extends ConsumerWidget {
  const RuntimeSettingsScreen({super.key});

  static const routePath = '/tools/runtime';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) return const _ConnectionRequired();
    final settings = ref.watch(runtimeSettingsProvider);
    return SafeArea(
      top: false,
      child: settings.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _LoadError(
          message: error.toString(),
          onRetry: () => ref.invalidate(runtimeSettingsProvider),
        ),
        data: (value) => _RuntimeSettingsEditor(initial: value),
      ),
    );
  }
}

class _RuntimeSettingsEditor extends ConsumerStatefulWidget {
  const _RuntimeSettingsEditor({required this.initial});
  final RuntimeSettings initial;

  @override
  ConsumerState<_RuntimeSettingsEditor> createState() =>
      _RuntimeSettingsEditorState();
}

class _RuntimeSettingsEditorState
    extends ConsumerState<_RuntimeSettingsEditor> {
  late final TextEditingController _taskDirectory;
  late final TextEditingController _commandTimeout;
  late final TextEditingController _elevatorTimeout;
  late final TextEditingController _executionTimeout;
  late final TextEditingController _idleStop;
  late bool _observationEnabled;
  late String _activeVehicle;
  late List<VehicleModel> _models;
  late List<String> _monitorNodes;
  late DependencyPlan _plan;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final item = widget.initial;
    _taskDirectory = TextEditingController(text: item.taskDirectory);
    _commandTimeout = TextEditingController(
      text: '${item.commandTimeoutSeconds}',
    );
    _elevatorTimeout = TextEditingController(
      text: '${item.elevatorWaitTimeoutSeconds}',
    );
    _executionTimeout = TextEditingController(
      text: '${item.taskExecutionTimeoutSeconds}',
    );
    _idleStop = TextEditingController(
      text: '${item.liveObservation.idleStopSeconds}',
    );
    _observationEnabled = item.liveObservation.enabled;
    _activeVehicle = item.liveObservation.activeVehicleModel;
    _models = List.of(item.liveObservation.vehicleModels);
    _monitorNodes = List.of(item.monitorNodes);
    _plan = item.dependencyPlan;
  }

  @override
  void dispose() {
    _taskDirectory.dispose();
    _commandTimeout.dispose();
    _elevatorTimeout.dispose();
    _executionTimeout.dispose();
    _idleStop.dispose();
    super.dispose();
  }

  RuntimeSettings _collect() => RuntimeSettings(
    taskDirectory: _taskDirectory.text.trim(),
    commandTimeoutSeconds: int.tryParse(_commandTimeout.text.trim()) ?? 0,
    elevatorWaitTimeoutSeconds: int.tryParse(_elevatorTimeout.text.trim()) ?? 0,
    taskExecutionTimeoutSeconds:
        int.tryParse(_executionTimeout.text.trim()) ?? 0,
    monitorNodes: _monitorNodes,
    dependencyPlan: _plan,
    liveObservation: LiveObservationSettings(
      enabled: _observationEnabled,
      idleStopSeconds: int.tryParse(_idleStop.text.trim()) ?? 0,
      vehicleModels: _models,
      activeVehicleModel: _activeVehicle,
    ),
  );

  Future<void> _save() async {
    if (_saving) return;
    final endpoint = ref.read(robotConnectionControllerProvider).endpoint;
    if (endpoint == null) return;
    setState(() => _saving = true);
    try {
      final result = await ref
          .read(runtimeSettingsRepositoryProvider)
          .save(endpoint, _collect());
      if (!mounted) return;
      ref.invalidate(runtimeSettingsProvider);
      setState(() {
        _monitorNodes = List.of(result.monitorNodes);
        _plan = result.dependencyPlan;
        _observationEnabled = result.liveObservation.enabled;
        _activeVehicle = result.liveObservation.activeVehicleModel;
        _models = List.of(result.liveObservation.vehicleModels);
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('运行配置已保存。')));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('保存失败：$error')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _editPlan() async {
    final processes = await ref.read(supervisorProcessesProvider.future);
    if (!mounted) return;
    final changed = await showModalBottomSheet<_DependencyDraft>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _DependencyPlanSheet(
        initialPlan: _plan,
        initialMonitorNodes: _monitorNodes,
        processes: processes,
      ),
    );
    if (changed != null && mounted) {
      setState(() {
        _plan = changed.plan;
        _monitorNodes = changed.monitorNodes;
      });
    }
  }

  Future<void> _editVehicle(VehicleModel current) async {
    final result = await showDialog<VehicleModel>(
      context: context,
      builder: (context) => _VehicleDialog(initial: current),
    );
    if (result == null || !mounted) return;
    setState(() {
      _models = _models
          .map((item) => item.id == current.id ? result : item)
          .toList(growable: false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(runtimeSettingsProvider);
        await ref.read(runtimeSettingsProvider.future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          LayoutBuilder(
            builder: (context, constraints) => Center(
              child: SizedBox(
                // A ListView child may otherwise shrink-wrap its column. Keep
                // every responsive panel on a finite canvas before its rows
                // decide between compact and wide layouts.
                width: constraints.maxWidth > 880 ? 880 : constraints.maxWidth,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const _Eyebrow(
                      icon: Icons.tune_outlined,
                      text: '工具 / 运行配置',
                    ),
                    const SizedBox(height: 10),
                    Text(
                      '运行配置',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: -.4,
                          ),
                    ),
                    SizedBox(height: 7),
                    Text(
                      '修改受控运行参数与测试预检编排。保存前由机器人再次校验。',
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _Panel(
                      title: '本机运行参数',
                      subtitle: '仅影响 Aletheia 控制台，不修改任务 JSON。',
                      child: Column(
                        children: [
                          TextField(
                            controller: _taskDirectory,
                            decoration: const InputDecoration(
                              labelText: '任务目标目录',
                              helperText: '机器人上的受控绝对目录',
                            ),
                          ),
                          const SizedBox(height: 12),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final fields = [
                                _NumberField(
                                  label: 'Supervisor 查询超时（秒）',
                                  controller: _commandTimeout,
                                ),
                                _NumberField(
                                  label: '电梯等待确认（秒）',
                                  controller: _elevatorTimeout,
                                ),
                                _NumberField(
                                  label: '单轮任务服务超时（秒）',
                                  controller: _executionTimeout,
                                ),
                              ];
                              if (constraints.maxWidth < 620) {
                                return Column(
                                  children: [
                                    for (
                                      var index = 0;
                                      index < fields.length;
                                      index++
                                    ) ...[
                                      fields[index],
                                      if (index < fields.length - 1)
                                        const SizedBox(height: 12),
                                    ],
                                  ],
                                );
                              }
                              return Row(
                                children: [
                                  for (
                                    var index = 0;
                                    index < fields.length;
                                    index++
                                  ) ...[
                                    Expanded(child: fields[index]),
                                    if (index < fields.length - 1)
                                      const SizedBox(width: 12),
                                  ],
                                ],
                              );
                            },
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    _Panel(
                      title: '测试依赖编排',
                      subtitle: _plan.enabled
                          ? '已启用 ${_plan.steps.length} 个启动阶段；${_monitorNodes.length} 个运行依赖。'
                          : '未启用自动编排；仍可选择运行依赖用于预检。',
                      trailing: OutlinedButton.icon(
                        onPressed: _editPlan,
                        icon: const Icon(Icons.account_tree_outlined),
                        label: const Text('配置'),
                      ),
                      child: _DependencySummary(
                        plan: _plan,
                        monitorNodes: _monitorNodes,
                      ),
                    ),
                    const SizedBox(height: 12),
                    _Panel(
                      title: '实时观测与车型',
                      subtitle: '车体尺寸只影响观测中的真实轮廓投影，不会下发车辆控制。',
                      child: Column(
                        children: [
                          Material(
                            color: Colors.transparent,
                            child: SwitchListTile.adaptive(
                              contentPadding: EdgeInsets.zero,
                              title: const Text('允许实时观测'),
                              subtitle: const Text('打开观测工作区时启动受控实时遥测。'),
                              value: _observationEnabled,
                              onChanged: (value) =>
                                  setState(() => _observationEnabled = value),
                            ),
                          ),
                          const SizedBox(height: 8),
                          _NumberField(
                            label: '空闲自动停止（秒）',
                            controller: _idleStop,
                          ),
                          SizedBox(height: 16),
                          if (_models.isEmpty)
                            Text(
                              '当前未读取到车型配置。',
                              style: TextStyle(color: AletheiaTheme.warning),
                            )
                          else
                            ..._models.map(
                              (model) => Padding(
                                padding: EdgeInsets.only(bottom: 8),
                                child: Material(
                                  color: model.id == _activeVehicle
                                      ? AletheiaTheme.cyan.withValues(alpha: .1)
                                      : AletheiaTheme.surfaceRaised,
                                  borderRadius: BorderRadius.circular(
                                    AletheiaTheme.controlRadius,
                                  ),
                                  child: InkWell(
                                    borderRadius: BorderRadius.circular(
                                      AletheiaTheme.controlRadius,
                                    ),
                                    onTap: () => setState(
                                      () => _activeVehicle = model.id,
                                    ),
                                    child: Padding(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 12,
                                        vertical: 10,
                                      ),
                                      child: Row(
                                        children: [
                                          Icon(
                                            model.id == _activeVehicle
                                                ? Icons.radio_button_checked
                                                : Icons.radio_button_off,
                                            color: model.id == _activeVehicle
                                                ? AletheiaTheme.cyan
                                                : AletheiaTheme.textTertiary,
                                          ),
                                          const SizedBox(width: 12),
                                          Expanded(
                                            child: Column(
                                              crossAxisAlignment:
                                                  CrossAxisAlignment.start,
                                              children: [
                                                Text(
                                                  model.name,
                                                  style: TextStyle(
                                                    fontWeight: FontWeight.w700,
                                                  ),
                                                ),
                                                Text(
                                                  '${model.lengthMetres.toStringAsFixed(2)} m × ${model.widthMetres.toStringAsFixed(2)} m',
                                                  style: TextStyle(
                                                    color: AletheiaTheme
                                                        .textSecondary,
                                                    fontSize: 13,
                                                  ),
                                                ),
                                              ],
                                            ),
                                          ),
                                          IconButton(
                                            tooltip: '编辑车型尺寸',
                                            onPressed: () =>
                                                _editVehicle(model),
                                            icon: const Icon(
                                              Icons.edit_outlined,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),
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
                        label: Text(_saving ? '正在保存…' : '保存运行配置'),
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

class _DependencyPlanSheet extends StatefulWidget {
  const _DependencyPlanSheet({
    required this.initialPlan,
    required this.initialMonitorNodes,
    required this.processes,
  });
  final DependencyPlan initialPlan;
  final List<String> initialMonitorNodes;
  final List<SupervisorProcess> processes;

  @override
  State<_DependencyPlanSheet> createState() => _DependencyPlanSheetState();
}

class _DependencyPlanSheetState extends State<_DependencyPlanSheet> {
  late bool _enabled;
  late List<String> _monitor;
  late List<DependencyStep> _steps;

  @override
  void initState() {
    super.initState();
    _enabled = widget.initialPlan.enabled;
    _monitor = List.of(widget.initialMonitorNodes);
    _steps = List.of(widget.initialPlan.steps);
  }

  List<String> get _names =>
      widget.processes.map((item) => item.name).toList(growable: false);

  void _toggleMonitor(String name, bool enabled) {
    setState(() {
      if (enabled) {
        if (!_monitor.contains(name)) _monitor.add(name);
      } else {
        _monitor.remove(name);
      }
    });
  }

  void _toggleStepNode(int index, String name, bool enabled) {
    final step = _steps[index];
    final nodes = List<String>.of(step.nodes);
    setState(() {
      if (enabled) {
        for (var i = 0; i < _steps.length; i++) {
          if (i != index) {
            _steps[i] = DependencyStep(
              nodes: _steps[i].nodes
                  .where((item) => item != name)
                  .toList(growable: false),
              waitSeconds: _steps[i].waitSeconds,
            );
          }
        }
        if (!nodes.contains(name)) nodes.add(name);
      } else {
        nodes.remove(name);
      }
      _steps[index] = DependencyStep(
        nodes: nodes,
        waitSeconds: step.waitSeconds,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        initialChildSize: .88,
        minChildSize: .5,
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
              const SizedBox(height: 18),
              Text(
                '测试依赖编排',
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 6),
              Text(
                '仅保存预检顺序；实际启动仍由机器人端受限 Supervisor 契约执行。',
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  height: 1.4,
                ),
              ),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                title: const Text('启用自动依赖编排'),
                subtitle: const Text('测试开始前按阶段启动并确认选中的依赖。'),
                value: _enabled,
                onChanged: (value) => setState(() => _enabled = value),
              ),
              const Divider(),
              const SizedBox(height: 8),
              Text('运行依赖', style: TextStyle(fontWeight: FontWeight.w700)),
              SizedBox(height: 4),
              Text(
                '测试运行期间必须持续可用的 Supervisor 进程。',
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  fontSize: 13,
                ),
              ),
              SizedBox(height: 8),
              if (_names.isEmpty)
                Text(
                  '尚未识别到 Supervisor 进程。下拉刷新运行配置后再试。',
                  style: TextStyle(color: AletheiaTheme.warning),
                )
              else
                ..._names.map(
                  (name) => CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: _monitor.contains(name),
                    onChanged: (value) => _toggleMonitor(name, value ?? false),
                    title: Text(name, style: const TextStyle(fontSize: 14)),
                  ),
                ),
              const SizedBox(height: 8),
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '启动阶段',
                      style: TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  TextButton.icon(
                    onPressed: _names.isEmpty
                        ? null
                        : () => setState(
                            () => _steps.add(
                              const DependencyStep(nodes: [], waitSeconds: 0),
                            ),
                          ),
                    icon: const Icon(Icons.add),
                    label: Text('添加阶段'),
                  ),
                ],
              ),
              if (_steps.isEmpty)
                Text(
                  '尚未配置启动阶段。启用时至少需要一个阶段。',
                  style: TextStyle(color: AletheiaTheme.textSecondary),
                ),
              ..._steps.asMap().entries.map(
                (entry) => _StepEditor(
                  index: entry.key,
                  step: entry.value,
                  names: _names,
                  onToggle: _toggleStepNode,
                  onWaitChanged: (value) => setState(
                    () => _steps[entry.key] = DependencyStep(
                      nodes: entry.value.nodes,
                      waitSeconds: value,
                    ),
                  ),
                  onRemove: () => setState(() => _steps.removeAt(entry.key)),
                ),
              ),
              const SizedBox(height: 18),
              FilledButton(
                onPressed: () {
                  final cleanSteps = _steps
                      .where((item) => item.nodes.isNotEmpty)
                      .toList(growable: false);
                  if (_enabled && cleanSteps.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('启用自动编排时至少选择一个启动阶段。')),
                    );
                    return;
                  }
                  Navigator.pop(
                    context,
                    _DependencyDraft(
                      plan: DependencyPlan(
                        enabled: _enabled,
                        steps: cleanSteps,
                      ),
                      monitorNodes: _monitor,
                    ),
                  );
                },
                child: const Text('完成配置'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StepEditor extends StatelessWidget {
  const _StepEditor({
    required this.index,
    required this.step,
    required this.names,
    required this.onToggle,
    required this.onWaitChanged,
    required this.onRemove,
  });
  final int index;
  final DependencyStep step;
  final List<String> names;
  final void Function(int index, String name, bool enabled) onToggle;
  final ValueChanged<int> onWaitChanged;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) => Container(
    margin: EdgeInsets.only(top: 10),
    padding: EdgeInsets.all(12),
    decoration: BoxDecoration(
      border: Border.all(color: AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '阶段 ${index + 1}',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            IconButton(
              tooltip: '移除阶段',
              onPressed: onRemove,
              icon: const Icon(Icons.delete_outline),
            ),
          ],
        ),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: names
              .map(
                (name) => FilterChip(
                  label: Text(name),
                  selected: step.nodes.contains(name),
                  onSelected: (value) => onToggle(index, name, value),
                ),
              )
              .toList(growable: false),
        ),
        const SizedBox(height: 10),
        DropdownButtonFormField<int>(
          initialValue: step.waitSeconds.clamp(0, 300),
          decoration: const InputDecoration(labelText: '稳定等待'),
          items: const [0, 5, 10, 20, 30, 60, 120, 300]
              .map(
                (seconds) =>
                    DropdownMenuItem(value: seconds, child: Text('$seconds 秒')),
              )
              .toList(),
          onChanged: (value) => onWaitChanged(value ?? 0),
        ),
      ],
    ),
  );
}

class _VehicleDialog extends StatefulWidget {
  const _VehicleDialog({required this.initial});
  final VehicleModel initial;
  @override
  State<_VehicleDialog> createState() => _VehicleDialogState();
}

class _VehicleDialogState extends State<_VehicleDialog> {
  late final TextEditingController _name = TextEditingController(
    text: widget.initial.name,
  );
  late final TextEditingController _length = TextEditingController(
    text: widget.initial.lengthMetres.toString(),
  );
  late final TextEditingController _width = TextEditingController(
    text: widget.initial.widthMetres.toString(),
  );
  @override
  void dispose() {
    _name.dispose();
    _length.dispose();
    _width.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('车型尺寸'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: _name,
          decoration: const InputDecoration(labelText: '名称'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _length,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(labelText: '长度（米）'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _width,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(labelText: '宽度（米）'),
        ),
      ],
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('取消'),
      ),
      FilledButton(
        onPressed: () {
          final length = double.tryParse(_length.text.trim());
          final width = double.tryParse(_width.text.trim());
          if (_name.text.trim().isEmpty || length == null || width == null) {
            return;
          }
          Navigator.pop(
            context,
            VehicleModel(
              id: widget.initial.id,
              name: _name.text.trim(),
              lengthMetres: length,
              widthMetres: width,
            ),
          );
        },
        child: const Text('完成'),
      ),
    ],
  );
}

class _DependencyDraft {
  const _DependencyDraft({required this.plan, required this.monitorNodes});
  final DependencyPlan plan;
  final List<String> monitorNodes;
}

class _NumberField extends StatelessWidget {
  const _NumberField({required this.label, required this.controller});
  final String label;
  final TextEditingController controller;
  @override
  Widget build(BuildContext context) => TextField(
    controller: controller,
    keyboardType: TextInputType.number,
    decoration: InputDecoration(labelText: label),
  );
}

class _Panel extends StatelessWidget {
  const _Panel({
    required this.title,
    required this.subtitle,
    required this.child,
    this.trailing,
  });
  final String title;
  final String subtitle;
  final Widget child;
  final Widget? trailing;
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
          SizedBox(height: 5),
          Text(
            subtitle,
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.35),
          ),
          if (trailing != null) ...[
            const SizedBox(height: 10),
            Align(alignment: Alignment.centerLeft, child: trailing!),
          ],
          const SizedBox(height: 16),
          child,
        ],
      ),
    ),
  );
}

class _DependencySummary extends StatelessWidget {
  const _DependencySummary({required this.plan, required this.monitorNodes});
  final DependencyPlan plan;
  final List<String> monitorNodes;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      if (monitorNodes.isNotEmpty)
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: monitorNodes
              .map(
                (item) => Chip(
                  label: Text(item),
                  avatar: Icon(Icons.visibility_outlined, size: 16),
                ),
              )
              .toList(growable: false),
        )
      else
        Text('尚未选择运行依赖。', style: TextStyle(color: AletheiaTheme.textTertiary)),
      if (plan.steps.isNotEmpty) ...[
        const SizedBox(height: 12),
        ...plan.steps.asMap().entries.map(
          (entry) => Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Text(
              '阶段 ${entry.key + 1}：${entry.value.nodes.join('、')}  ·  等待 ${entry.value.waitSeconds} 秒',
              style: TextStyle(
                color: AletheiaTheme.textSecondary,
                fontSize: 13,
              ),
            ),
          ),
        ),
      ],
    ],
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

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.lan_outlined, color: AletheiaTheme.textTertiary, size: 28),
          SizedBox(height: 12),
          Text(
            '先连接机器人后再管理运行配置。',
            style: TextStyle(color: AletheiaTheme.textSecondary),
          ),
          const SizedBox(height: 14),
          OutlinedButton(
            onPressed: () => context.go(RobotConnectionScreen.routePath),
            child: const Text('前往机器人'),
          ),
        ],
      ),
    ),
  );
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.error_outline_rounded,
            color: AletheiaTheme.danger,
            size: 30,
          ),
          SizedBox(height: 12),
          Text(
            '无法读取运行配置：$message',
            textAlign: TextAlign.center,
            style: TextStyle(color: AletheiaTheme.textSecondary),
          ),
          const SizedBox(height: 14),
          OutlinedButton(onPressed: onRetry, child: const Text('重试')),
        ],
      ),
    ),
  );
}
