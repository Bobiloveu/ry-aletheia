import 'package:flutter/material.dart';

import '../app/theme/aletheia_theme.dart';
import '../app/motion/aletheia_motion.dart';
import 'gallery_manifest.dart';
import 'gallery_preview.dart';

/// Debug-only UI review entry point. The router only registers this screen
/// when [kDebugMode] is true; production builds have no route or navigation
/// entry for it.
class DebugUiGalleryScreen extends StatefulWidget {
  const DebugUiGalleryScreen({this.initialScreenId, super.key});

  static const routePath = '/__debug/ui-gallery';

  final String? initialScreenId;

  @override
  State<DebugUiGalleryScreen> createState() => _DebugUiGalleryScreenState();
}

class _DebugUiGalleryScreenState extends State<DebugUiGalleryScreen> {
  late GalleryScreenSpec _selected;

  @override
  void initState() {
    super.initState();
    _selected = galleryScreenById(
      widget.initialScreenId ?? 'robot_disconnected',
    );
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final selected = _selected;
      // The constrained canvas is the source of truth here. On an iOS
      // rotation, MediaQuery can briefly retain the former orientation while
      // this layout has already become wide. Rendering a portrait mock during
      // that transition makes the Gallery unreadable.
      // A phone remains a phone after rotation. Its long edge can exceed
      // 900 logical pixels on Android and newer large phones, so classify
      // the Gallery from the constrained *short* edge only. Otherwise a
      // wide phone falls into the desktop review scaffold and loses the
      // persistent quick-switch control.
      final phoneSized = constraints.smallest.shortestSide < 600;
      if (phoneSized) {
        return _buildDevicePreview(
          context,
          selected,
          portrait: constraints.maxHeight > constraints.maxWidth,
        );
      }
      return _buildReviewScaffold(context, selected);
    },
  );

  /// On a phone the Gallery is a state injector, not a review chrome. The
  /// selected production page must retain its real device size in both
  /// orientations, otherwise the nested preview ceases to be useful for HMI
  /// ergonomics review. Tablets and desktop retain the inventory layout.
  Widget _buildDevicePreview(
    BuildContext context,
    GalleryScreenSpec selected, {
    required bool portrait,
  }) {
    return Scaffold(
      body: Stack(
        children: [
          Positioned.fill(
            child: SizedBox.expand(
              key: ValueKey('gallery-device-preview-${selected.id}'),
              child: DebugGalleryPreview(spec: selected),
            ),
          ),
          PositionedDirectional(
            // In landscape the production shell already owns a dedicated
            // left navigation strip. Put the debug-only picker in its unused
            // lower space instead of covering live map/video evidence.
            start: portrait ? null : 4,
            end: portrait ? 14 : null,
            // The production shell owns the bottom NavigationBar in portrait.
            // Keep this debug-only control above it after every rotation.
            bottom: portrait ? 96 : 14,
            child: SafeArea(
              top: false,
              left: !portrait,
              right: portrait,
              child: _GalleryQuickSwitch(
                spec: selected,
                onTap: () => _chooseScreen(context),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildReviewScaffold(
    BuildContext context,
    GalleryScreenSpec selected,
  ) {
    return Scaffold(
      appBar: AppBar(
        title: Text('界面检查'),
        actions: [
          Padding(
            padding: EdgeInsets.only(right: 18),
            child: Center(
              child: Text(
                '仅调试',
                style: TextStyle(
                  color: AletheiaTheme.textTertiary,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 900;
          final picker = _GalleryPicker(
            selected: selected,
            onSelected: (spec) => setState(() => _selected = spec),
          );
          final preview = AletheiaFadeThrough(
            child: KeyedSubtree(
              key: ValueKey('gallery-preview-${selected.id}'),
              child: _SelectedPreview(spec: selected),
            ),
          );
          if (wide) {
            return Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(width: 328, child: picker),
                const VerticalDivider(width: 1),
                Expanded(child: preview),
              ],
            );
          }
          return Column(
            children: [
              Expanded(child: preview),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 18),
                  child: OutlinedButton.icon(
                    onPressed: () => _chooseScreen(context),
                    icon: const Icon(Icons.dashboard_outlined),
                    label: Text('选择界面状态 · ${selected.module.label}'),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _chooseScreen(BuildContext context) async {
    final selected = await showModalBottomSheet<GalleryScreenSpec>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        top: false,
        child: SizedBox(
          height: MediaQuery.sizeOf(sheetContext).height * .8,
          child: _GalleryPicker(
            selected: _selected,
            onSelected: (spec) => Navigator.of(sheetContext).pop(spec),
          ),
        ),
      ),
    );
    if (selected != null && mounted) {
      setState(() => _selected = selected);
    }
  }
}

/// A deliberately small, debug-only way back to the state picker when the
/// selected production page occupies the whole compact landscape viewport.
class _GalleryQuickSwitch extends StatelessWidget {
  const _GalleryQuickSwitch({required this.spec, required this.onTap});

  final GalleryScreenSpec spec;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final label = '选择界面状态 · ${spec.title}';
    return Semantics(
      button: true,
      label: '$label，当前为${spec.state}',
      child: Tooltip(
        message: label,
        child: Material(
          key: Key('gallery-quick-switch'),
          color: AletheiaTheme.surfaceRaised.withValues(alpha: .96),
          elevation: 6,
          shadowColor: Colors.black54,
          shape: RoundedRectangleBorder(
            side: BorderSide(color: AletheiaTheme.border),
            borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
          ),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
            child: const SizedBox(
              width: 48,
              height: 48,
              child: Icon(Icons.dashboard_outlined),
            ),
          ),
        ),
      ),
    );
  }
}

class _GalleryPicker extends StatelessWidget {
  const _GalleryPicker({required this.selected, required this.onSelected});

  final GalleryScreenSpec selected;
  final ValueChanged<GalleryScreenSpec> onSelected;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(color: AletheiaTheme.surfaceSunken),
    child: ListView(
      shrinkWrap: true,
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 20),
      children: [
        const _PickerIntro(),
        const SizedBox(height: 18),
        for (final module in GalleryModule.values) ...[
          _ModuleLabel(module: module),
          const SizedBox(height: 6),
          ...galleryScreenManifest
              .where((spec) => spec.module == module)
              .map(
                (spec) => _ScreenChoice(
                  spec: spec,
                  selected: spec.id == selected.id,
                  onTap: () => onSelected(spec),
                ),
              ),
          const SizedBox(height: 14),
        ],
      ],
    ),
  );
}

class _PickerIntro extends StatelessWidget {
  const _PickerIntro();

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        '完整状态预览',
        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
      ),
      SizedBox(height: 5),
      Text(
        '所有预览只使用本地模拟状态，不会连接机器人。',
        style: TextStyle(color: AletheiaTheme.textSecondary, height: 1.35),
      ),
    ],
  );
}

class _ModuleLabel extends StatelessWidget {
  const _ModuleLabel({required this.module});

  final GalleryModule module;

  @override
  Widget build(BuildContext context) => Text(
    module.label,
    style: TextStyle(
      color: AletheiaTheme.cyan,
      fontSize: 12,
      fontWeight: FontWeight.w700,
      letterSpacing: .4,
    ),
  );
}

class _ScreenChoice extends StatelessWidget {
  const _ScreenChoice({
    required this.spec,
    required this.selected,
    required this.onTap,
  });

  final GalleryScreenSpec spec;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: selected
        ? AletheiaTheme.cyan.withValues(alpha: .12)
        : Colors.transparent,
    borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
    child: InkWell(
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      onTap: onTap,
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '${spec.title} · ${spec.state}',
                style: TextStyle(
                  color: selected
                      ? AletheiaTheme.cyan
                      : AletheiaTheme.textPrimary,
                  fontSize: 13,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
            ),
            if (selected)
              Icon(Icons.check_rounded, color: AletheiaTheme.cyan, size: 18),
          ],
        ),
      ),
    ),
  );
}

class _SelectedPreview extends StatelessWidget {
  const _SelectedPreview({required this.spec});

  final GalleryScreenSpec spec;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) => Padding(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 700),
          child: SizedBox(
            height: constraints.maxHeight,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '${spec.title} · ${spec.state}',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                SizedBox(height: 6),
                Text(
                  spec.trigger,
                  style: TextStyle(color: AletheiaTheme.textSecondary),
                ),
                SizedBox(height: 16),
                Expanded(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: AletheiaTheme.canvas,
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: AletheiaTheme.border),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black38,
                          blurRadius: 22,
                          offset: Offset(0, 12),
                        ),
                      ],
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(23),
                      child: FittedBox(
                        fit: BoxFit.contain,
                        alignment: Alignment.topCenter,
                        child: SizedBox(
                          width: 402,
                          height: 874,
                          child: DebugGalleryPreview(spec: spec),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
