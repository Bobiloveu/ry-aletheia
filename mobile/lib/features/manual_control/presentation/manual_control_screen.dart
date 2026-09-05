import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../robot_connection/presentation/robot_connection_screen.dart';
import '../application/manual_control_controller.dart';
import '../domain/vehicle_control_state.dart';

/// A deliberately bounded Mobile HMI for the existing vehicle-control API.
///
/// The screen never bypasses backend control-source, session or emergency-stop
/// rules. Its directional surface is enabled only after the controller has a
/// local opaque session id *and* the newest backend snapshot explicitly marks
/// manual motion as ready.
class ManualControlScreen extends ConsumerStatefulWidget {
  const ManualControlScreen({super.key});

  static const routePath = '/tools/manual-control';

  @override
  ConsumerState<ManualControlScreen> createState() =>
      _ManualControlScreenState();
}

class _ManualControlScreenState extends ConsumerState<ManualControlScreen>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycleState) {
    final controller = ref.read(manualControlControllerProvider.notifier);
    if (lifecycleState == AppLifecycleState.resumed) {
      controller.resumeAfterLifecycle();
      return;
    }
    unawaited(controller.pauseForLifecycle());
  }

  @override
  Widget build(BuildContext context) {
    final connected = ref.watch(
      robotConnectionControllerProvider.select((state) => state.isConnected),
    );
    if (!connected) return const _ConnectionRequired();

    final viewState = ref.watch(manualControlControllerProvider);
    final controller = ref.read(manualControlControllerProvider.notifier);
    final status = viewState.status;
    if (status == null) {
      return const SafeArea(
        top: false,
        child: Center(child: CircularProgressIndicator()),
      );
    }

    return SafeArea(
      top: false,
      child: RefreshIndicator(
        onRefresh: controller.refresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          children: [
            Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 680),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const _Eyebrow(),
                    const SizedBox(height: 10),
                    Text(
                      '手动控制',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: -.4,
                          ),
                    ),
                    const SizedBox(height: 7),
                    Text(
                      '仅在现场具备安全条件时使用。松开摇杆、离开页面或 App 进入后台都会请求停止并退出手动会话。',
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        height: 1.45,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _ControlStatusCard(
                      state: viewState,
                      onEnter: () => _confirmEnter(context, controller),
                      onExit: controller.exit,
                      onRefresh: controller.refresh,
                    ),
                    const SizedBox(height: 12),
                    _DirectionPanel(
                      enabled: viewState.canSendMotion,
                      busy: viewState.isBusy,
                      onVector: controller.sendVector,
                      onStop: controller.stop,
                    ),
                    const SizedBox(height: 12),
                    _SpeedPanel(
                      state: viewState,
                      onChanged: (linear, angular) => controller.setSpeed(
                        linearMps: linear,
                        angularRadps: angular,
                      ),
                    ),
                    const SizedBox(height: 12),
                    _ChassisParametersPanel(
                      parameters: status.chassisParameters,
                      busy: viewState.isBusy,
                      onSave: controller.saveChassisParameters,
                    ),
                    if (status.emergency.state !=
                        EmergencyStopState.normal) ...[
                      const SizedBox(height: 12),
                      _EmergencyPanel(
                        state: status.emergency,
                        busy: viewState.isBusy,
                        onRelease: controller.releaseEmergencyStop,
                      ),
                    ],
                    if (viewState.message.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      _Notice(
                        message: viewState.message,
                        isError: viewState.isError,
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmEnter(
    BuildContext context,
    ManualControlController controller,
  ) async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认进入手动控制？'),
        content: const Text(
          '请确认机器人周围无人、路径清晰，并由现场人员持续观察。进入后仍需等待车端确认控制源和急停状态，摇杆才会解锁。',
          style: TextStyle(height: 1.45),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('进入控制'),
          ),
        ],
      ),
    );
    if (accepted == true) await controller.enter();
  }
}

class _ConnectionRequired extends StatelessWidget {
  const _ConnectionRequired();

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.lan_outlined, color: AletheiaTheme.textTertiary),
          const SizedBox(height: 12),
          Text(
            '先连接机器人后再进入手动控制。',
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

class _Eyebrow extends StatelessWidget {
  const _Eyebrow();

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(Icons.gamepad_outlined, size: 17, color: AletheiaTheme.cyan),
      const SizedBox(width: 8),
      Text(
        '工具 / 车辆操作',
        style: TextStyle(
          color: AletheiaTheme.textSecondary,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    ],
  );
}

class _ControlStatusCard extends StatelessWidget {
  const _ControlStatusCard({
    required this.state,
    required this.onEnter,
    required this.onExit,
    required this.onRefresh,
  });

  final ManualControlScreenState state;
  final Future<void> Function() onEnter;
  final Future<void> Function() onExit;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final status = state.status!;
    final ready = state.canSendMotion;
    final active = state.hasActiveSession;
    final (label, icon, color) = switch ((
      active,
      ready,
      status.emergency.state,
    )) {
      (_, _, EmergencyStopState.triggered) => (
        '急停已触发',
        Icons.emergency_rounded,
        AletheiaTheme.danger,
      ),
      (_, _, EmergencyStopState.unknown) => (
        '急停状态未知',
        Icons.help_outline_rounded,
        AletheiaTheme.warning,
      ),
      (true, true, _) => ('已就绪', Icons.verified_rounded, AletheiaTheme.mint),
      (true, false, _) => ('等待车端确认', Icons.sync_rounded, AletheiaTheme.warning),
      _ => ('未进入', Icons.lock_outline_rounded, AletheiaTheme.textTertiary),
    };

    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '控制状态',
                  style: Theme.of(context).textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              _StatusPill(icon: icon, label: label, color: color),
            ],
          ),
          const SizedBox(height: 12),
          _StatusLine(
            label: '控制源',
            value: status.actualSource.isEmpty ? '等待状态' : status.actualSource,
          ),
          const SizedBox(height: 7),
          _StatusLine(label: '急停', value: status.emergency.state.label),
          const SizedBox(height: 16),
          if (active)
            OutlinedButton.icon(
              onPressed: state.isBusy ? null : onExit,
              icon: const Icon(Icons.stop_circle_outlined),
              label: const Text('退出手动控制'),
            )
          else
            FilledButton.icon(
              onPressed: state.isBusy || !status.canBeginManual
                  ? null
                  : onEnter,
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Text('开始手动控制'),
            ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: state.isBusy ? null : onRefresh,
            icon: const Icon(Icons.refresh_rounded, size: 18),
            label: const Text('刷新车端状态'),
          ),
        ],
      ),
    );
  }
}

class _DirectionPanel extends StatelessWidget {
  const _DirectionPanel({
    required this.enabled,
    required this.busy,
    required this.onVector,
    required this.onStop,
  });

  final bool enabled;
  final bool busy;
  final Future<void> Function(VehicleControlVector vector) onVector;
  final Future<void> Function() onStop;

  @override
  Widget build(BuildContext context) => _Panel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '方向',
          style: Theme.of(context).textTheme.titleMedium
              ?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 16),
        Center(
          child: _DirectionJoystick(
            enabled: enabled && !busy,
            onVector: onVector,
            onStop: onStop,
          ),
        ),
      ],
    ),
  );
}

class _DirectionJoystick extends StatefulWidget {
  const _DirectionJoystick({
    required this.enabled,
    required this.onVector,
    required this.onStop,
  });

  final bool enabled;
  final Future<void> Function(VehicleControlVector vector) onVector;
  final Future<void> Function() onStop;

  @override
  State<_DirectionJoystick> createState() => _DirectionJoystickState();
}

class _DirectionJoystickState extends State<_DirectionJoystick>
    with TickerProviderStateMixin {
  static const _returnSpring = SpringDescription(
    mass: 1,
    stiffness: 440,
    damping: 33,
  );

  Offset _offset = Offset.zero;
  VehicleControlVector _vector = VehicleControlVector.stop;
  late final AnimationController _xReturn;
  late final AnimationController _yReturn;

  @override
  void initState() {
    super.initState();
    _xReturn = AnimationController.unbounded(vsync: this)
      ..addListener(_syncSpringOffset);
    _yReturn = AnimationController.unbounded(vsync: this)
      ..addListener(_syncSpringOffset);
  }

  @override
  void dispose() {
    _xReturn
      ..removeListener(_syncSpringOffset)
      ..dispose();
    _yReturn
      ..removeListener(_syncSpringOffset)
      ..dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant _DirectionJoystick oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled && oldWidget.enabled) _release();
  }

  void _update(Offset localPosition, Size size) {
    if (!widget.enabled) return;
    _xReturn.stop();
    _yReturn.stop();
    final center = Offset(size.width / 2, size.height / 2);
    final raw = localPosition - center;
    final maxRadius = size.shortestSide * .29;
    final distance = raw.distance;
    final offset = distance > maxRadius ? raw / distance * maxRadius : raw;
    final vector = VehicleControlVector.fromJoystick(
      horizontal: offset.dx / maxRadius,
      vertical: offset.dy / maxRadius,
    );
    if (_vector.isStop && !vector.isStop) {
      HapticFeedback.selectionClick();
      widget.onVector(vector);
    } else if (vector != _vector && !vector.isStop) {
      widget.onVector(vector);
    } else if (vector.isStop && !_vector.isStop) {
      widget.onStop();
    }
    setState(() {
      _offset = offset;
      _vector = vector;
    });
  }

  void _release() {
    if (!_vector.isStop) widget.onStop();
    _xReturn.value = _offset.dx;
    _yReturn.value = _offset.dy;
    _xReturn.animateWith(SpringSimulation(_returnSpring, _offset.dx, 0, 0));
    _yReturn.animateWith(SpringSimulation(_returnSpring, _offset.dy, 0, 0));
    if (mounted) setState(() => _vector = VehicleControlVector.stop);
  }

  void _syncSpringOffset() {
    if (!mounted) return;
    setState(() => _offset = Offset(_xReturn.value, _yReturn.value));
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.enabled
        ? AletheiaTheme.cyan
        : AletheiaTheme.textTertiary;
    final semanticLabel = widget.enabled
        ? '连续方向摇杆，当前${_vector.label}'
        : '连续方向摇杆已锁定';
    return Semantics(
      label: semanticLabel,
      enabled: widget.enabled,
      child: ExcludeSemantics(
        child: SizedBox.square(
          dimension: 236,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final size = Size.square(constraints.maxWidth);
              final knobSize = size.shortestSide * .34;
              final active = !_vector.isStop;
              final thumbColor = active ? AletheiaTheme.cyan : color;
              final thumbIcon = switch ((widget.enabled, active)) {
                (false, _) => Icons.lock_outline_rounded,
                (true, true) => Icons.navigation_rounded,
                (true, false) => null,
              };
              final heading = math.atan2(_offset.dx, -_offset.dy);
              return GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanStart: widget.enabled
                    ? (details) => _update(details.localPosition, size)
                    : null,
                onPanUpdate: widget.enabled
                    ? (details) => _update(details.localPosition, size)
                    : null,
                onPanEnd: widget.enabled ? (_) => _release() : null,
                onPanCancel: widget.enabled ? _release : null,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: widget.enabled
                        ? AletheiaTheme.surfaceSunken
                        : AletheiaTheme.surfaceRaised,
                    border: Border.all(color: color.withValues(alpha: .28)),
                  ),
                  child: Center(
                    child: Transform.translate(
                      offset: _offset,
                      child: Container(
                        width: knobSize,
                        height: knobSize,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: widget.enabled
                              ? AletheiaTheme.surface
                              : AletheiaTheme.surfaceRaised,
                          border: Border.all(
                            color: thumbColor.withValues(
                              alpha: active ? .8 : .42,
                            ),
                            width: active ? 2 : 1.5,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: .10),
                              blurRadius: 8,
                              offset: const Offset(0, 3),
                            ),
                          ],
                        ),
                        child: Center(
                          child: thumbIcon == null
                              ? Container(
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    color: thumbColor.withValues(alpha: .7),
                                    shape: BoxShape.circle,
                                  ),
                                )
                              : Transform.rotate(
                                  angle: active ? heading : 0,
                                  child: Icon(
                                    thumbIcon,
                                    color: thumbColor,
                                    size: active ? 25 : 22,
                                  ),
                                ),
                        ),
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

class _SpeedPanel extends StatefulWidget {
  const _SpeedPanel({required this.state, required this.onChanged});

  final ManualControlScreenState state;
  final Future<void> Function(double linear, double angular) onChanged;

  @override
  State<_SpeedPanel> createState() => _SpeedPanelState();
}

class _SpeedPanelState extends State<_SpeedPanel> {
  late double _linear;
  late double _angular;

  @override
  void initState() {
    super.initState();
    _syncFromStatus();
  }

  @override
  void didUpdateWidget(covariant _SpeedPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state.status != widget.state.status && !widget.state.isBusy) {
      _syncFromStatus();
    }
  }

  void _syncFromStatus() {
    final speed = widget.state.status!.speed;
    final minimum = speed.minimum.clamp(.1, 1.0).toDouble();
    final maximum = speed.maximum.clamp(minimum, 1.0).toDouble();
    _linear = speed.linearMps.clamp(minimum, maximum).toDouble();
    _angular = speed.angularRadps.clamp(minimum, maximum).toDouble();
  }

  @override
  Widget build(BuildContext context) {
    final speed = widget.state.status!.speed;
    final enabled = widget.state.canSendMotion && !widget.state.isBusy;
    final minimum = speed.minimum.clamp(.1, 1.0).toDouble();
    final maximum = speed.maximum.clamp(minimum, 1.0).toDouble();
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '速度档',
            style: Theme.of(context).textTheme.titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Text(
            '调整最大线速度和转向速度；实际安全限幅始终以车端为准。',
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
          ),
          const SizedBox(height: 12),
          _SpeedSlider(
            label: '线速度',
            unit: 'm/s',
            value: _linear,
            min: minimum,
            max: maximum,
            enabled: enabled,
            onChanged: (next) => setState(() => _linear = next),
            onChangeEnd: enabled
                ? (next) => widget.onChanged(next, _angular)
                : null,
          ),
          const SizedBox(height: 10),
          _SpeedSlider(
            label: '转向速度',
            unit: 'rad/s',
            value: _angular,
            min: minimum,
            max: maximum,
            enabled: enabled,
            onChanged: (next) => setState(() => _angular = next),
            onChangeEnd: enabled
                ? (next) => widget.onChanged(_linear, next)
                : null,
          ),
        ],
      ),
    );
  }
}

class _SpeedSlider extends StatelessWidget {
  const _SpeedSlider({
    required this.label,
    required this.unit,
    required this.value,
    required this.min,
    required this.max,
    required this.enabled,
    required this.onChanged,
    required this.onChangeEnd,
  });

  final String label;
  final String unit;
  final double value;
  final double min;
  final double max;
  final bool enabled;
  final ValueChanged<double> onChanged;
  final ValueChanged<double>? onChangeEnd;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Row(
        children: [
          Text(label, style: Theme.of(context).textTheme.labelLarge),
          const Spacer(),
          Text(
            '${value.toStringAsFixed(2)} $unit',
            style: TextStyle(
              color: AletheiaTheme.cyan,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
      Slider(
        value: value,
        min: min,
        max: max,
        divisions: ((max - min) / .1).round().clamp(1, 18),
        onChanged: enabled ? onChanged : null,
        onChangeEnd: onChangeEnd,
      ),
    ],
  );
}

class _ChassisParametersPanel extends StatelessWidget {
  const _ChassisParametersPanel({
    required this.parameters,
    required this.busy,
    required this.onSave,
  });

  final ChassisParameters parameters;
  final bool busy;
  final Future<void> Function(ChassisParameters parameters) onSave;

  @override
  Widget build(BuildContext context) => _Panel(
    child: Row(
      children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: AletheiaTheme.cyan.withValues(alpha: .1),
            borderRadius: BorderRadius.circular(13),
          ),
          child: Icon(Icons.tune_rounded, color: AletheiaTheme.cyan),
        ),
        const SizedBox(width: 13),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '底盘参数',
                style: Theme.of(context).textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 3),
              Text(
                '压力、运动加速度与停止加速度',
                style: TextStyle(
                  color: AletheiaTheme.textSecondary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: '编辑底盘参数',
          onPressed: busy
              ? null
              : () => _showChassisSheet(context, parameters, onSave),
          icon: const Icon(Icons.chevron_right_rounded),
        ),
      ],
    ),
  );

  Future<void> _showChassisSheet(
    BuildContext context,
    ChassisParameters initial,
    Future<void> Function(ChassisParameters parameters) onSave,
  ) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _ChassisParametersSheet(initial: initial, onSave: onSave),
  );
}

class _ChassisParametersSheet extends StatefulWidget {
  const _ChassisParametersSheet({required this.initial, required this.onSave});

  final ChassisParameters initial;
  final Future<void> Function(ChassisParameters parameters) onSave;

  @override
  State<_ChassisParametersSheet> createState() =>
      _ChassisParametersSheetState();
}

class _ChassisParametersSheetState extends State<_ChassisParametersSheet> {
  late int _press;
  late int _movementAcceleration;
  late int _stopAcceleration;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _press = widget.initial.press.clamp(20, 2000);
    _movementAcceleration = widget.initial.movementAcceleration.clamp(10, 1000);
    _stopAcceleration = widget.initial.stopAcceleration.clamp(20, 2000);
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await widget.onSave(
      ChassisParameters(
        press: _press,
        movementAcceleration: _movementAcceleration,
        stopAcceleration: _stopAcceleration,
      ),
    );
    if (mounted) setState(() => _saving = false);
  }

  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.fromLTRB(
      20,
      12,
      20,
      20 + MediaQuery.viewInsetsOf(context).bottom,
    ),
    decoration: BoxDecoration(
      color: AletheiaTheme.surface,
      borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
      border: Border.all(color: AletheiaTheme.border),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: .18),
          blurRadius: 28,
          offset: const Offset(0, -8),
        ),
      ],
    ),
    child: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: AletheiaTheme.border,
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Text('底盘参数', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text(
            '仅在明确了解车辆响应时调整。所有数值仍由车端校验和限幅。',
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
          ),
          const SizedBox(height: 18),
          _IntegerParameterField(
            label: '底盘压力',
            value: _press,
            minimum: 20,
            maximum: 2000,
            unit: '',
            onChanged: (value) => setState(() => _press = value),
          ),
          _IntegerParameterField(
            label: '运动加速度',
            value: _movementAcceleration,
            minimum: 10,
            maximum: 1000,
            unit: 'mm/s²',
            onChanged: (value) => setState(() => _movementAcceleration = value),
          ),
          _IntegerParameterField(
            label: '停止加速度',
            value: _stopAcceleration,
            minimum: 20,
            maximum: 2000,
            unit: 'mm/s²',
            onChanged: (value) => setState(() => _stopAcceleration = value),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.save_outlined),
            label: const Text('保存到车端'),
          ),
        ],
      ),
    ),
  );
}

class _IntegerParameterField extends StatelessWidget {
  const _IntegerParameterField({
    required this.label,
    required this.value,
    required this.minimum,
    required this.maximum,
    required this.unit,
    required this.onChanged,
  });

  final String label;
  final int value;
  final int minimum;
  final int maximum;
  final String unit;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Column(
      children: [
        Row(
          children: [
            Text(label, style: Theme.of(context).textTheme.labelLarge),
            const Spacer(),
            Text(
              unit.isEmpty ? '$value' : '$value $unit',
              style: TextStyle(
                color: AletheiaTheme.cyan,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        Slider(
          value: value.toDouble(),
          min: minimum.toDouble(),
          max: maximum.toDouble(),
          divisions: 20,
          onChanged: (next) => onChanged(next.round()),
        ),
      ],
    ),
  );
}

class _EmergencyPanel extends StatelessWidget {
  const _EmergencyPanel({
    required this.state,
    required this.busy,
    required this.onRelease,
  });

  final EmergencyStop state;
  final bool busy;
  final Future<void> Function() onRelease;

  @override
  Widget build(BuildContext context) {
    final triggered = state.state == EmergencyStopState.triggered;
    return _Panel(
      borderColor: triggered
          ? AletheiaTheme.danger.withValues(alpha: .55)
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                triggered
                    ? Icons.emergency_rounded
                    : Icons.help_outline_rounded,
                color: triggered ? AletheiaTheme.danger : AletheiaTheme.warning,
              ),
              const SizedBox(width: 9),
              Text(
                triggered ? '急停已触发' : '急停状态未知',
                style: Theme.of(context).textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            triggered
                ? '方向控制已锁定。仅在现场确认风险已经排除后，才可请求车端解除急停。'
                : '为避免误动作，方向控制保持锁定。请刷新状态并检查机器人。',
            style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.45),
          ),
          if (triggered) ...[
            const SizedBox(height: 16),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: AletheiaTheme.danger,
              ),
              onPressed: busy ? null : onRelease,
              icon: const Icon(Icons.lock_open_rounded),
              label: const Text('请求解除急停'),
            ),
          ],
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, this.borderColor});
  final Widget child;
  final Color? borderColor;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surface,
      border: Border.all(color: borderColor ?? AletheiaTheme.border),
      borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
    ),
    child: Padding(padding: const EdgeInsets.all(18), child: child),
  );
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.icon,
    required this.label,
    required this.color,
  });
  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .12),
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: color.withValues(alpha: .35)),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(color: color, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      SizedBox(
        width: 64,
        child: Text(label, style: TextStyle(color: AletheiaTheme.textTertiary)),
      ),
      Expanded(
        child: Text(value, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
    ],
  );
}

class _Notice extends StatelessWidget {
  const _Notice({required this.message, required this.isError});
  final String message;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final color = isError ? AletheiaTheme.danger : AletheiaTheme.cyan;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .1),
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
        border: Border.all(color: color.withValues(alpha: .3)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(13),
        child: Row(
          children: [
            Icon(
              isError
                  ? Icons.error_outline_rounded
                  : Icons.info_outline_rounded,
              color: color,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                message,
                style: TextStyle(color: color, height: 1.35),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

extension on VehicleControlVector {
  String get label {
    if (isStop) return '停止';
    final motion = linearRatio > 0
        ? '前进'
        : linearRatio < 0
        ? '后退'
        : '';
    final turning = angularRatio > 0
        ? '左转'
        : angularRatio < 0
        ? '右转'
        : '';
    return '$motion$turning';
  }
}

extension on EmergencyStopState {
  String get label => switch (this) {
    EmergencyStopState.normal => '正常',
    EmergencyStopState.triggered => '已触发',
    EmergencyStopState.unknown => '未知（已锁定）',
  };
}
