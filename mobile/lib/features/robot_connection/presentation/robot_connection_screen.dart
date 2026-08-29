import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/branding/aletheia_brand_mark.dart';
import '../../../app/motion/aletheia_motion.dart';
import '../../../app/responsive_layout.dart';
import '../../../app/theme/aletheia_theme.dart';
import '../../../core/connection/observation_status.dart';
import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_connection_state.dart';

class RobotConnectionScreen extends ConsumerStatefulWidget {
  const RobotConnectionScreen({this.embedded = false, super.key});

  static const routePath = '/robot';
  static const legacyRoutePath = '/connection';

  final bool embedded;

  @override
  ConsumerState<RobotConnectionScreen> createState() =>
      _RobotConnectionScreenState();
}

class _RobotConnectionScreenState extends ConsumerState<RobotConnectionScreen> {
  late final TextEditingController _addressController;

  @override
  void initState() {
    super.initState();
    _addressController = TextEditingController();
  }

  @override
  void dispose() {
    _addressController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final connection = ref.watch(robotConnectionControllerProvider);
    ref.listen<RobotConnectionState>(robotConnectionControllerProvider, (
      previous,
      next,
    ) {
      final restored = next.endpoint?.toString();
      if (restored != null &&
          next.endpoint != previous?.endpoint &&
          _addressController.text.isEmpty) {
        _addressController.text = restored;
      }
    });

    final body = SafeArea(
      top: false,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compactLandscape = isCompactLandscape(
            viewportHeight: constraints.maxHeight,
            isLandscape: constraints.maxWidth > constraints.maxHeight,
          );
          final wide = usesTwoColumnWorkspace(
            availableWidth: constraints.maxWidth,
            isLandscape: constraints.maxWidth > constraints.maxHeight,
          );
          final content = wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      flex: 11,
                      child: _ConnectionPanel(
                        addressController: _addressController,
                        state: connection,
                        compactLandscape: compactLandscape,
                      ),
                    ),
                    const SizedBox(width: 20),
                    Expanded(flex: 9, child: _StatusPanel(state: connection)),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _ConnectionPanel(
                      addressController: _addressController,
                      state: connection,
                      compactLandscape: compactLandscape,
                    ),
                    const SizedBox(height: 16),
                    _StatusPanel(state: connection),
                  ],
                );
          return SingleChildScrollView(
            padding: EdgeInsets.fromLTRB(20, 12, 20, wide ? 32 : 24),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1240),
                child: content,
              ),
            ),
          );
        },
      ),
    );
    if (widget.embedded) {
      return body;
    }
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 24,
        title: const _Brand(),
        actions: const [
          Padding(
            padding: EdgeInsets.only(right: 20),
            child: Center(child: _PhaseChip()),
          ),
        ],
      ),
      body: body,
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const AletheiaBrandMark(size: 30),
        const SizedBox(width: 10),
        const Text('Aletheia'),
      ],
    );
  }
}

class _PhaseChip extends StatelessWidget {
  const _PhaseChip();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceRaised,
        border: Border.all(color: AletheiaTheme.border),
        borderRadius: BorderRadius.circular(999),
      ),
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Text('机器人连接', style: TextStyle(fontSize: 12)),
      ),
    );
  }
}

class _ConnectionPanel extends ConsumerWidget {
  const _ConnectionPanel({
    required this.addressController,
    required this.state,
    required this.compactLandscape,
  });

  final TextEditingController addressController;
  final RobotConnectionState state;
  final bool compactLandscape;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(robotConnectionControllerProvider.notifier);
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionEyebrow(icon: Icons.smart_toy_outlined, text: '当前机器人'),
          SizedBox(height: compactLandscape ? 10 : 14),
          Text(
            '连接或确认机器人',
            style:
                (compactLandscape
                        ? Theme.of(context).textTheme.titleLarge
                        : Theme.of(context).textTheme.headlineSmall)
                    ?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -.4),
          ),
          SizedBox(height: compactLandscape ? 6 : 8),
          Text(
            '连接机器人后，可查看状态、实时观测以及测试与诊断工具。',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: AletheiaTheme.textSecondary, height: 1.45),
          ),
          SizedBox(height: compactLandscape ? 16 : 28),
          TextField(
            controller: addressController,
            enabled: !state.isBusy,
            keyboardType: TextInputType.url,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => controller.connect(addressController.text),
            decoration: const InputDecoration(
              labelText: '机器人地址',
              hintText: '192.168.1.20 或 robot.local',
              prefixIcon: Icon(Icons.dns_outlined),
            ),
          ),
          SizedBox(height: compactLandscape ? 16 : 22),
          FilledButton.icon(
            onPressed: state.isBusy
                ? null
                : () => controller.connect(addressController.text),
            icon: state.phase == ConnectionPhase.checking
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.network_ping_rounded),
            label: Text(
              state.phase == ConnectionPhase.checking ? '正在探测…' : '连接并检查',
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPanel extends ConsumerWidget {
  const _StatusPanel({required this.state});

  final RobotConnectionState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final observation = state.observation;
    final controller = ref.read(robotConnectionControllerProvider.notifier);
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionEyebrow(
            icon: Icons.monitor_heart_outlined,
            text: '连接状态',
          ),
          const SizedBox(height: 18),
          AletheiaFadeThrough(
            child: KeyedSubtree(
              key: ValueKey('connection-phase-${state.phase.name}'),
              child: _ConnectionBanner(state: state),
            ),
          ),
          if (state.message.isNotEmpty &&
              state.phase != ConnectionPhase.checking) ...[
            const SizedBox(height: 14),
            _InlineNotice(
              text: state.message,
              isError: state.phase == ConnectionPhase.failure,
            ),
          ],
          const SizedBox(height: 22),
          _StatusLine(
            label: '机器人连接',
            value: state.isConnected ? '已连接' : '等待连接',
            active: state.isConnected,
          ),
          const SizedBox(height: 15),
          _StatusLine(
            label: '实时数据',
            value: observation?.telemetryOnline == true ? '运行中' : '未运行',
            active: observation?.telemetryOnline == true,
          ),
          const SizedBox(height: 15),
          _StatusLine(
            label: '观测服务',
            value: observation?.preprocessorManaged == true
                ? '运行中'
                : observation?.preprocessorAvailable == true
                ? '可用'
                : '未就绪',
            active: observation?.preprocessorManaged == true,
          ),
          const SizedBox(height: 15),
          _StatusLine(
            label: '地图',
            value: observation?.activeMapId != null ? '已缓存' : '尚未发现',
            active: observation?.activeMapId != null,
          ),
          if (state.isConnected) ...[
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            if (observation?.telemetryOnline == true)
              _ObservationRunningHint(observation: observation!)
            else
              _StartObservationAction(
                enabledInConfiguration:
                    observation?.enabledInConfiguration == true,
                isBusy: state.isBusy,
                onPressed: controller.startObservation,
              ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: state.isBusy ? null : controller.refresh,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('重新检查状态'),
            ),
          ],
        ],
      ),
    );
  }
}

class _ConnectionBanner extends StatelessWidget {
  const _ConnectionBanner({required this.state});

  final RobotConnectionState state;

  @override
  Widget build(BuildContext context) {
    final (color, icon, label, detail) = switch (state.phase) {
      ConnectionPhase.restoring => (
        AletheiaTheme.cyan,
        Icons.more_horiz_rounded,
        '正在准备连接',
        '正在读取上次使用的机器人地址。',
      ),
      ConnectionPhase.idle => (
        AletheiaTheme.textTertiary,
        Icons.link_off_rounded,
        '尚未连接',
        '输入机器人地址后进行状态探测。',
      ),
      ConnectionPhase.checking => (
        AletheiaTheme.cyan,
        Icons.sync_rounded,
        '正在检查',
        state.endpoint?.displayAddress ?? '正在连接机器人。',
      ),
      ConnectionPhase.connected => (
        AletheiaTheme.mint,
        Icons.verified_rounded,
        '机器人已连接',
        state.endpoint?.displayAddress ?? '机器人可以使用。',
      ),
      ConnectionPhase.failure => (
        AletheiaTheme.danger,
        Icons.error_outline_rounded,
        '无法连接',
        state.endpoint?.displayAddress ?? '请检查机器人地址。',
      ),
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .10),
        border: Border.all(color: color.withValues(alpha: .42)),
        borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: TextStyle(fontWeight: FontWeight.w700)),
                  SizedBox(height: 3),
                  Text(
                    detail,
                    style: TextStyle(color: AletheiaTheme.textSecondary),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ObservationRunningHint extends StatelessWidget {
  const _ObservationRunningHint({required this.observation});

  final ObservationStatus observation;

  @override
  Widget build(BuildContext context) {
    final idle = observation.idleStopSeconds;
    return _InlineNotice(
      text: idle == null
          ? '实时观测已开启。保持应用在前台可持续查看数据。'
          : '实时观测已开启。离开应用一段时间后会自动暂停。',
      isError: false,
    );
  }
}

class _StartObservationAction extends StatelessWidget {
  const _StartObservationAction({
    required this.enabledInConfiguration,
    required this.isBusy,
    required this.onPressed,
  });

  final bool enabledInConfiguration;
  final bool isBusy;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    if (!enabledInConfiguration) {
      return const _InlineNotice(
        text: '实时观测尚未启用。请先在机器人管理端开启后再试。',
        isError: false,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          '启动后可在“观测”中查看地图与实时数据。',
          style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.4),
        ),
        const SizedBox(height: 12),
        FilledButton.tonalIcon(
          onPressed: isBusy ? null : onPressed,
          icon: isBusy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.play_circle_outline_rounded),
          label: Text(isBusy ? '正在启动…' : '启动实时观测'),
        ),
      ],
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
        border: Border.all(color: AletheiaTheme.border),
        borderRadius: BorderRadius.circular(AletheiaTheme.panelRadius),
      ),
      child: Padding(padding: const EdgeInsets.all(20), child: child),
    );
  }
}

class _SectionEyebrow extends StatelessWidget {
  const _SectionEyebrow({required this.icon, required this.text});

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

class _StatusLine extends StatelessWidget {
  const _StatusLine({
    required this.label,
    required this.value,
    required this.active,
  });

  final String label;
  final String value;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final color = active ? AletheiaTheme.mint : AletheiaTheme.textTertiary;
    return Row(
      children: [
        Container(
          width: 9,
          height: 9,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 10),
        Expanded(child: Text(label)),
        Text(
          value,
          style: TextStyle(color: color, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.text, required this.isError});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final color = isError ? AletheiaTheme.danger : AletheiaTheme.warning;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .10),
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
