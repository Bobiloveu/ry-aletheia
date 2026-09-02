import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'branding/aletheia_brand_mark.dart';
import '../core/connection/robot_connection_controller.dart';
import '../features/robot_connection/presentation/robot_connection_screen.dart';
import '../features/live_observation/presentation/live_observation_screen.dart';
import '../features/tools/presentation/tools_screen.dart';
import '../features/app_settings/presentation/app_settings_screen.dart';
import 'responsive_layout.dart';
import 'motion/aletheia_motion.dart';
import 'theme/aletheia_theme.dart';

class AletheiaAppShell extends ConsumerWidget {
  const AletheiaAppShell({
    required this.location,
    required this.child,
    super.key,
  });

  final String location;
  final Widget child;

  static const _destinations = [
    _Destination(
      route: RobotConnectionScreen.routePath,
      label: '首页',
      icon: Icons.smart_toy_outlined,
      selectedIcon: Icons.smart_toy_rounded,
    ),
    _Destination(
      route: LiveObservationScreen.routePath,
      label: '观测',
      icon: Icons.radar_outlined,
      selectedIcon: Icons.radar_rounded,
    ),
    _Destination(
      route: ToolsScreen.routePath,
      label: '工具',
      icon: Icons.handyman_outlined,
      selectedIcon: Icons.handyman_rounded,
    ),
    _Destination(
      route: AppSettingsScreen.routePath,
      label: '设置',
      icon: Icons.settings_outlined,
      selectedIcon: Icons.settings_rounded,
    ),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Depend on the inherited Theme instead of reading the static palette
    // directly. Without this dependency the settings page rebuilt after a
    // preference change while the shell AppBar retained its old dark color.
    final theme = Theme.of(context);
    final canvas =
        theme.appBarTheme.backgroundColor ?? theme.scaffoldBackgroundColor;
    final viewport = MediaQuery.sizeOf(context);
    final isLandscape = viewport.width > viewport.height;
    final compactLandscape = isCompactLandscape(
      viewportHeight: viewport.height,
      isLandscape: isLandscape,
    );
    final selectedIndex = _destinations.indexWhere(
      (destination) => destination.matches(location),
    );
    final currentIndex = selectedIndex < 0 ? 0 : selectedIndex;
    final isObservationRoot = location == LiveObservationScreen.routePath;
    final isSettingsRoot = location == AppSettingsScreen.routePath;
    final isSettingsRoute =
        isSettingsRoot ||
        location.startsWith('${AppSettingsScreen.routePath}/');
    final connection = ref.watch(
      robotConnectionControllerProvider.select(
        (state) => (state.isConnected, state.endpoint?.displayAddress),
      ),
    );
    // The three HMI workspaces share one recognizable top-level identity.
    // Observation keeps the same Logo + name as robot home while the map is
    // allowed to continue under the translucent material behind it. Tools is
    // still an HMI workspace, not a detached developer console.
    final showProductIdentity =
        location == RobotConnectionScreen.routePath ||
        isObservationRoot ||
        location == ToolsScreen.routePath;
    final usesObservationOverlay =
        isObservationRoot && isLandscape && connection.$1;

    return Scaffold(
      // In observation, the map is the work surface. Let it continue under a
      // restrained status material rather than reserving an opaque header.
      extendBodyBehindAppBar: usesObservationOverlay,
      appBar: AppBar(
        toolbarHeight: compactLandscape ? 44 : kToolbarHeight,
        backgroundColor: usesObservationOverlay
            ? canvas.withValues(alpha: .82)
            : canvas,
        surfaceTintColor: Colors.transparent,
        scrolledUnderElevation: 0,
        // Do not reserve a phantom leading slot on root destinations. The
        // short-landscape HMI needs the brand to align with the shell edge.
        automaticallyImplyLeading: false,
        titleSpacing: compactLandscape ? 8 : 16,
        leading: _parentRoute == null
            ? null
            : IconButton(
                tooltip: _parentRoute == AppSettingsScreen.routePath
                    ? '返回设置'
                    : '返回工具',
                onPressed: () => context.go(_parentRoute!),
                icon: const Icon(Icons.arrow_back_rounded),
              ),
        // Every HMI workspace keeps the full product identity. App Settings is
        // a separate, phone-local root, so it uses an ordinary page title.
        title: showProductIdentity
            ? Row(
                children: [
                  AletheiaBrandMark(size: compactLandscape ? 22 : 30),
                  SizedBox(width: compactLandscape ? 7 : 10),
                  const Text('Aletheia'),
                ],
              )
            : isObservationRoot
            ? Semantics(
                label: 'Aletheia',
                child: AletheiaBrandMark(size: compactLandscape ? 22 : 30),
              )
            : isSettingsRoot
            ? const Text('设置')
            : null,
        actions: isSettingsRoute
            ? const []
            : [
                Padding(
                  padding: EdgeInsets.only(right: compactLandscape ? 4 : 12),
                  child: _ConnectionChip(
                    connected: connection.$1,
                    address: connection.$2,
                    onTap: () => context.go(RobotConnectionScreen.routePath),
                  ),
                ),
              ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final useRail = usesNavigationRail(
            availableWidth: constraints.maxWidth,
            isLandscape: constraints.maxWidth > constraints.maxHeight,
          );
          if (!useRail) {
            return child;
          }
          if (compactLandscape) {
            return Row(
              children: [
                _CompactNavigationStrip(
                  currentIndex: currentIndex,
                  leadingSafeInset: MediaQuery.paddingOf(context).left,
                  onDestinationSelected: (index) =>
                      context.go(_destinations[index].route),
                ),
                const VerticalDivider(width: 1),
                Expanded(child: child),
              ],
            );
          }
          return Row(
            children: [
              SafeArea(
                top: false,
                child: NavigationRail(
                  selectedIndex: currentIndex,
                  minWidth: 72,
                  labelType: NavigationRailLabelType.all,
                  onDestinationSelected: (index) =>
                      context.go(_destinations[index].route),
                  destinations: _destinations
                      .map(
                        (destination) => NavigationRailDestination(
                          icon: _RailIcon(
                            icon: destination.icon,
                            label: destination.label,
                          ),
                          selectedIcon: _RailIcon(
                            icon: destination.selectedIcon,
                            label: destination.label,
                          ),
                          label: Text(destination.label),
                        ),
                      )
                      .toList(growable: false),
                ),
              ),
              const VerticalDivider(width: 1),
              Expanded(child: child),
            ],
          );
        },
      ),
      bottomNavigationBar: LayoutBuilder(
        builder: (context, constraints) {
          final useRail = usesNavigationRail(
            availableWidth: constraints.maxWidth,
            isLandscape: constraints.maxWidth > constraints.maxHeight,
          );
          if (useRail) {
            return const SizedBox.shrink();
          }
          return NavigationBar(
            selectedIndex: currentIndex,
            onDestinationSelected: (index) =>
                context.go(_destinations[index].route),
            destinations: _destinations
                .map(
                  (destination) => NavigationDestination(
                    icon: Icon(destination.icon),
                    selectedIcon: Icon(destination.selectedIcon),
                    label: destination.label,
                  ),
                )
                .toList(growable: false),
          );
        },
      ),
    );
  }

  String? get _parentRoute {
    if (location.startsWith('${AppSettingsScreen.routePath}/')) {
      return AppSettingsScreen.routePath;
    }
    if (location.startsWith('${ToolsScreen.routePath}/')) {
      return ToolsScreen.routePath;
    }
    return null;
  }
}

class _ConnectionChip extends StatelessWidget {
  const _ConnectionChip({
    required this.connected,
    required this.address,
    required this.onTap,
  });

  final bool connected;
  final String? address;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = connected
        ? theme.colorScheme.secondary
        : theme.textTheme.bodySmall?.color ?? theme.colorScheme.onSurface;
    return Semantics(
      label: connected ? '已连接 $address' : '尚未连接机器人',
      button: true,
      hint: '前往机器人',
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(999),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Center(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: color.withValues(alpha: .1),
                  border: Border.all(color: color.withValues(alpha: .35)),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        connected
                            ? Icons.check_circle_outline_rounded
                            : Icons.link_off,
                        color: color,
                        size: 15,
                      ),
                      const SizedBox(width: 6),
                      Text(
                        connected ? '已连接' : '未连接',
                        style: TextStyle(
                          color: color,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _RailIcon extends StatelessWidget {
  const _RailIcon({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Icon(icon);
  }
}

/// The stock [NavigationRail] reserves the iPhone side safe area *in
/// addition* to its minimum width. On short landscape phones that turns a
/// 56pt icon rail into an oversized blank column. This compact strip owns a
/// single 56pt visual band instead: its 44pt destinations retain reliable
/// touch targets while the remaining space belongs to the active HMI page.
class _CompactNavigationStrip extends StatelessWidget {
  const _CompactNavigationStrip({
    required this.currentIndex,
    required this.leadingSafeInset,
    required this.onDestinationSelected,
  });

  final int currentIndex;
  final double leadingSafeInset;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context) {
    final canvas = Theme.of(context).scaffoldBackgroundColor;
    return SizedBox(
      key: Key('compact-navigation-strip'),
      width: 56 + leadingSafeInset,
      child: ColoredBox(
        color: canvas,
        child: Row(
          children: [
            if (leadingSafeInset > 0) SizedBox(width: leadingSafeInset),
            SizedBox(
              width: 56,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (
                      var index = 0;
                      index < AletheiaAppShell._destinations.length;
                      index++
                    ) ...[
                      _CompactNavigationDestination(
                        key: Key('compact-navigation-destination-$index'),
                        destination: AletheiaAppShell._destinations[index],
                        selected: currentIndex == index,
                        onTap: () => onDestinationSelected(index),
                      ),
                      if (index != AletheiaAppShell._destinations.length - 1)
                        const SizedBox(height: 8),
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
}

class _CompactNavigationDestination extends StatelessWidget {
  const _CompactNavigationDestination({
    required this.destination,
    required this.selected,
    required this.onTap,
    super.key,
  });

  final _Destination destination;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final iconColor = selected
        ? theme.colorScheme.primary
        : theme.textTheme.bodySmall?.color ?? theme.colorScheme.onSurface;
    return Semantics(
      button: true,
      selected: selected,
      label: destination.label,
      hint: selected ? '当前页面' : '切换到${destination.label}',
      child: Tooltip(
        message: destination.label,
        preferBelow: false,
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
            child: AnimatedContainer(
              duration: AletheiaMotion.durationFor(
                context,
                AletheiaMotion.fast,
              ),
              curve: AletheiaMotion.easeOut,
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: selected
                    ? theme.inputDecorationTheme.fillColor
                    : Colors.transparent,
                border: selected
                    ? Border.all(color: theme.colorScheme.outline)
                    : Border.all(color: Colors.transparent),
                borderRadius: BorderRadius.circular(
                  AletheiaTheme.sectionRadius,
                ),
              ),
              child: Icon(
                selected ? destination.selectedIcon : destination.icon,
                color: iconColor,
                size: 23,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Destination {
  const _Destination({
    required this.route,
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });

  final String route;
  final String label;
  final IconData icon;
  final IconData selectedIcon;

  bool matches(String location) =>
      location == route || location.startsWith('$route/');
}
