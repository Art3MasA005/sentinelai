import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/adaptation/adaptation_page.dart';
import '../features/alerts/alerts_page.dart';
import '../features/analysis/analysis_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/drift/drift_page.dart';
import '../features/experiments/experiments_page.dart';
import '../features/experiments/quick_test.dart';
import '../features/reports/reports_page.dart';
import '../features/rules/rules_page.dart';
import '../features/settings/settings_page.dart';
import '../features/system/system_page.dart';
import '../features/traffic/traffic_page.dart';
import 'api/models.dart';
import 'brand.dart';
import 'format.dart';
import 'glass_menu.dart';
import 'state.dart';
import 'status.dart';
import 'theme.dart';
import 'widgets.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  Timer? _live;
  Timer? _health;
  bool _wasActive = false;
  bool _collapsed = false;
  final _scaffold = GlobalKey<ScaffoldState>();

  @override
  void initState() {
    super.initState();
    // Live data: re-fetch while any run is running/paused, plus once after it finishes.
    _live = Timer.periodic(const Duration(seconds: 2), (_) {
      final runs = ref.read(runsProvider).value ?? const <Run>[];
      final active = runs.any((r) => r.isActive);
      if (active || _wasActive) ref.read(refreshTickProvider.notifier).bump();
      _wasActive = active;
    });
    _health = Timer.periodic(const Duration(seconds: 5), (_) {
      ref.invalidate(healthProvider);
      final runs = ref.read(runsProvider);
      if (runs.hasError || !runs.hasValue) ref.read(refreshTickProvider.notifier).bump();
    });
  }

  @override
  void dispose() {
    _live?.cancel();
    _health?.cancel();
    super.dispose();
  }

  Widget _page(AppPage p) => switch (p) {
    AppPage.dashboard => const DashboardPage(),
    AppPage.alerts => const AlertsPage(),
    AppPage.traffic => const TrafficPage(),
    AppPage.analysis => const AnalysisPage(),
    AppPage.drift => const DriftPage(),
    AppPage.adaptation => const AdaptationPage(),
    AppPage.experiments => const ExperimentsPage(),
    AppPage.reports => const ReportsPage(),
    AppPage.rules => const RulesPage(),
    AppPage.system => const SystemPage(),
    AppPage.settings => const SettingsPage(),
  };

  @override
  Widget build(BuildContext context) {
    final page = ref.watch(navProvider);
    final wide = MediaQuery.sizeOf(context).width >= 1100;
    final showSidebar = wide && !_collapsed;
    return Scaffold(
      key: _scaffold,
      drawer: wide ? null : Drawer(backgroundColor: AppColors.sidebar, child: Sidebar(inDrawer: true)),
      body: Stack(
        children: [
          const Positioned.fill(child: AppBackground()),
          Row(
            children: [
              // Space for the sidebar, which is painted above the pages (last in the stack) so its edge
              // shadow is never covered by a page layer during a transition.
              if (showSidebar) SizedBox(width: Sidebar.extent),
              Expanded(
                child: Column(
                  children: [
                    TopBar(
                      onMenu: () {
                        if (wide) {
                          setState(() => _collapsed = !_collapsed);
                        } else {
                          _scaffold.currentState?.openDrawer();
                        }
                      },
                    ),
                    Expanded(
                      child: _PageStack(current: page, builder: _page),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (showSidebar) const Positioned(left: 0, top: 0, bottom: 0, child: Sidebar()),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- page transitions

/// Keeps every visited page alive (scroll position, filters and loaded data survive navigation) and
/// cross-fades between them: the new page fades in while rising a few pixels, the old one fades out
/// quickly. Hidden pages are offstage with tickers muted, so they cost no paint or animation time.
class _PageStack extends StatefulWidget {
  const _PageStack({required this.current, required this.builder});
  final AppPage current;
  final Widget Function(AppPage) builder;

  @override
  State<_PageStack> createState() => _PageStackState();
}

class _PageStackState extends State<_PageStack> {
  final _visited = <AppPage>[];

  /// Where this area sits in the window, so a layer can repaint the window background exactly behind itself.
  Offset _origin = Offset.zero;

  void _measure() {
    if (!mounted) return;
    final box = context.findRenderObject() as RenderBox?;
    if (box == null || !box.hasSize) return;
    final o = box.localToGlobal(Offset.zero);
    if (o != _origin) setState(() => _origin = o);
  }

  @override
  Widget build(BuildContext context) {
    WidgetsBinding.instance.addPostFrameCallback((_) => _measure());
    if (!_visited.contains(widget.current)) _visited.add(widget.current);
    // The current page is painted last so it sits on top during the cross-fade.
    final order = [..._visited.where((p) => p != widget.current), widget.current];
    return Stack(
      fit: StackFit.expand,
      children: [
        for (final p in order)
          _PageLayer(key: ValueKey(p), active: p == widget.current, origin: _origin, child: widget.builder(p)),
      ],
    );
  }
}

class _PageLayer extends StatefulWidget {
  const _PageLayer({super.key, required this.active, required this.origin, required this.child});
  final bool active;
  final Offset origin;
  final Widget child;

  @override
  State<_PageLayer> createState() => _PageLayerState();
}

class _PageLayerState extends State<_PageLayer> with SingleTickerProviderStateMixin {
  static const _in = Duration(milliseconds: 280);
  static const _out = Duration(milliseconds: 140);

  late final AnimationController _c = AnimationController(vsync: this, duration: _in, reverseDuration: _out)
    ..addStatusListener((_) => setState(() {}));

  @override
  void initState() {
    super.initState();
    if (widget.active) _c.forward();
  }

  @override
  void didUpdateWidget(_PageLayer old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) {
      _c.forward(from: 0);
    } else if (!widget.active && old.active) {
      _c.reverse();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hidden = !widget.active && _c.isDismissed;
    final fading = _c.isAnimating;
    final fade = CurvedAnimation(parent: _c, curve: Curves.easeOutCubic, reverseCurve: Curves.easeInCubic);
    final window = MediaQuery.sizeOf(context);
    return Offstage(
      offstage: hidden,
      child: TickerMode(
        enabled: !hidden,
        child: IgnorePointer(
          ignoring: !widget.active,
          child: FadeTransition(
            opacity: fade,
            child: ClipRect(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  // While fading, the page is drawn into its own layer, and frosted-glass cards blur whatever
                  // that layer already holds. Without the window background inside it they blur nothing and
                  // flash dark, so the background is repainted here, aligned with the one behind the shell.
                  if (fading)
                    Positioned(
                      left: -widget.origin.dx,
                      top: -widget.origin.dy,
                      width: window.width,
                      height: window.height,
                      child: const IgnorePointer(child: AppBackground()),
                    ),
                  SlideTransition(
                    key: const ValueKey('page'),
                    // Rise in from slightly below; the outgoing page stays in place while it fades.
                    position: widget.active
                        ? Tween(begin: const Offset(0, 0.018), end: Offset.zero).animate(fade)
                        : const AlwaysStoppedAnimation(Offset.zero),
                    child: RepaintBoundary(child: widget.child),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- sidebar

class Sidebar extends ConsumerWidget {
  const Sidebar({super.key, this.inDrawer = false});
  final bool inDrawer;

  /// Horizontal space the docked sidebar takes: 240 wide, plus a 12 px inset for the floating frosted one.
  static double get extent => AppColors.isGlass ? 252 : 240;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final page = ref.watch(navProvider);
    final health = ref.watch(healthProvider);
    final ok = health.value?['status'] == 'ok';
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 26, 20, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SentinelWordmark(markSize: 24, fontSize: 19),
              const SizedBox(height: 10),
              Text(
                'NETWORK DEFENSE LAB',
                style: TextStyle(fontSize: 10, letterSpacing: 0.8, color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
        const Divider(height: 1, indent: 20, endIndent: 20),
        const SizedBox(height: 12),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            children: [
              for (final p in AppPage.values)
                _NavItem(
                  page: p,
                  active: p == page,
                  onTap: () {
                    ref.read(navProvider.notifier).go(p);
                    if (inDrawer) Navigator.of(context).pop();
                  },
                ),
            ],
          ),
        ),
        Container(
          margin: const EdgeInsets.fromLTRB(14, 8, 14, 12),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppColors.isGlass ? const Color(0x66FFFFFF) : const Color(0xFF0E1A26),
            borderRadius: BorderRadius.circular(AppColors.isGlass ? 12 : 10),
            border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.circle, size: 9, color: ok ? AppColors.green : AppColors.red),
                  const SizedBox(width: 8),
                  const Text(
                    'SYSTEM STATUS',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 0.5),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                health.isLoading && !health.hasValue
                    ? 'Connecting…'
                    : ok
                    ? 'Local backend ready'
                    : 'Backend unreachable',
                style: TextStyle(color: ok ? AppColors.green : AppColors.red, fontSize: 12.5),
              ),
              const SizedBox(height: 6),
              Text('Offline replay mode', style: TextStyle(color: AppColors.textSecondary, fontSize: 11.5)),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(26, 0, 20, 18),
          child: Text(
            'SENTINELAI  ·  v${health.value?['version'] ?? '0.1'}',
            style: TextStyle(color: AppColors.textMuted, fontSize: 10.5, letterSpacing: 0.4),
          ),
        ),
      ],
    );
    if (AppColors.isGlass && !inDrawer) {
      // Floating frosted sidebar, inset from the window edge like macOS.
      return Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 0, 12),
        child: SizedBox(
          width: 240,
          child: Glass(radius: 18, color: AppColors.sidebar, child: content),
        ),
      );
    }
    return Container(
      width: 240,
      decoration: BoxDecoration(
        color: AppColors.sidebar,
        border: Border(right: BorderSide(color: AppColors.border)),
      ),
      child: content,
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.page, required this.active, required this.onTap});
  final AppPage page;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    // Highlight, icon and label colours ease between states instead of switching in one frame.
    const d = Duration(milliseconds: 220);
    const curve = Curves.easeOutCubic;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: AnimatedContainer(
        duration: d,
        curve: curve,
        decoration: BoxDecoration(
          color: active ? AppColors.navActive : AppColors.navActive.withValues(alpha: 0),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: active ? AppColors.navActiveBorder : AppColors.navActiveBorder.withValues(alpha: 0),
          ),
        ),
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
              child: Row(
                children: [
                  TweenAnimationBuilder<Color?>(
                    tween: ColorTween(end: active ? AppColors.purple : AppColors.textSecondary),
                    duration: d,
                    curve: curve,
                    builder: (_, c, _) => Icon(page.icon, size: 17, color: c),
                  ),
                  const SizedBox(width: 14),
                  AnimatedDefaultTextStyle(
                    duration: d,
                    curve: curve,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: active ? FontWeight.w700 : FontWeight.w400,
                      color: active ? AppColors.text : AppColors.textSecondary,
                    ),
                    child: Text(page.label),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- top bar

class TopBar extends ConsumerWidget {
  const TopBar({super.key, required this.onMenu});
  final VoidCallback onMenu;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider);
    final ok = health.value?['status'] == 'ok';
    final run = ref.watch(currentRunProvider);
    final roomy = MediaQuery.sizeOf(context).width >= 1450;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 28, 10),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Toggle navigation',
            onPressed: onMenu,
            icon: Icon(Icons.menu, color: AppColors.textSecondary),
          ),
          const SizedBox(width: 10),
          const Flexible(child: SizedBox(width: 320, child: _SearchBox())),
          const Spacer(),
          if (run?.isDemo == true) ...[const DemoBadge(), const SizedBox(width: 12)],
          const _QuickTestButton(),
          const SizedBox(width: 10),
          const _RunPicker(),
          const SizedBox(width: 8),
          const _ThemeToggle(),
          const SizedBox(width: 8),
          _Notifications(showText: roomy),
          if (roomy) ...[
            const SizedBox(width: 18),
            Icon(Icons.circle, size: 8, color: AppColors.text),
            const SizedBox(width: 8),
            const Text('Researcher', style: TextStyle(fontSize: 13)),
          ],
          const SizedBox(width: 16),
          Tooltip(
            message: ok ? 'Backend healthy at ${ref.watch(settingsProvider).baseUrl}' : 'Backend not reachable',
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              decoration: BoxDecoration(
                color: ok ? AppColors.okSurface : AppColors.offlineSurface,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: ok ? AppColors.okBorder : AppColors.red.withValues(alpha: 0.5)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(ok ? Icons.circle : Icons.cloud_off, size: 10, color: ok ? AppColors.green : AppColors.red),
                  const SizedBox(width: 8),
                  Text(
                    ok ? 'LOCAL BACKEND' : 'BACKEND OFFLINE',
                    style: TextStyle(
                      color: ok ? AppColors.green : AppColors.red,
                      fontWeight: FontWeight.w800,
                      fontSize: 11.5,
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

/// Opens the one-click test dialog (dataset, size, method → start; the run shows live on the Dashboard).
class _QuickTestButton extends StatelessWidget {
  const _QuickTestButton();

  @override
  Widget build(BuildContext context) => Tooltip(
    message: 'Start a test run in one click',
    child: FilledButton.icon(
      onPressed: () => showQuickTest(context),
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.blue,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
      ),
      icon: const Icon(Icons.bolt_rounded, size: 17),
      label: const Text('Quick test'),
    ),
  );
}

class _SearchBox extends ConsumerStatefulWidget {
  const _SearchBox();

  @override
  ConsumerState<_SearchBox> createState() => _SearchBoxState();
}

class _SearchBoxState extends ConsumerState<_SearchBox> {
  final _ctl = TextEditingController();

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  void _submit(String q) {
    q = q.trim();
    if (q.isEmpty) return;
    final flowId = int.tryParse(q.replaceAll(RegExp(r'^(fl-|#|flow\s*)', caseSensitive: false), ''));
    if (flowId != null) {
      ref.read(trafficSearchProvider.notifier).set(flowId);
      ref.read(navProvider.notifier).go(AppPage.traffic);
      return;
    }
    final runs = ref.read(runsProvider).value ?? const <Run>[];
    final ql = q.toLowerCase();
    final hit = runs.where(
      (r) =>
          r.id.toLowerCase().contains(ql) || r.name.toLowerCase().contains(ql) || runLabel(r.seq).toLowerCase() == ql,
    );
    if (hit.isEmpty) {
      showSnack(context, 'No run or flow matches "$q"', error: true);
      return;
    }
    ref.read(selectedRunIdProvider.notifier).select(hit.first.id);
    ref.read(navProvider.notifier).go(AppPage.experiments);
    showSnack(context, 'Selected ${runLabel(hit.first.seq)} · ${hit.first.name}');
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _ctl,
      onSubmitted: _submit,
      style: const TextStyle(fontSize: 13),
      decoration: InputDecoration(
        hintText: 'Search experiments, flows…',
        prefixIcon: Icon(Icons.search, size: 18, color: AppColors.textSecondary),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(22),
          borderSide: BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(22),
          borderSide: BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(22),
          borderSide: BorderSide(color: AppColors.blue),
        ),
      ),
    );
  }
}

/// Flow id requested from the global search, consumed by the Traffic Monitor.
class TrafficSearch extends Notifier<int?> {
  @override
  int? build() => int.tryParse(Uri.base.queryParameters['flow'] ?? ''); // `?flow=<id>` deep link
  void set(int? id) => state = id;
}

final trafficSearchProvider = NotifierProvider<TrafficSearch, int?>(TrafficSearch.new);

class _RunPicker extends ConsumerWidget {
  const _RunPicker();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(runsProvider).value ?? const <Run>[];
    final current = ref.watch(currentRunProvider);
    return GlassMenu<String>(
      header: 'Experiment runs',
      emptyText: 'No runs yet',
      selected: current?.id,
      minWidth: 340,
      onSelected: (id) => ref.read(selectedRunIdProvider.notifier).select(id),
      items: [
        for (final r in runs.take(30))
          GlassMenuItem(
            value: r.id,
            icon: Icons.science_outlined,
            iconColor: runStatusColor(r.status),
            label: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 72,
                  child: Text(runLabel(r.seq), style: const TextStyle(fontWeight: FontWeight.w700)),
                ),
                Flexible(child: Text(methodName(r.method))),
              ],
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(r.status, style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                if (r.isDemo) ...[const SizedBox(width: 10), const DemoBadge(compact: true)],
              ],
            ),
          ),
      ],
      builder: (context, controller) => Tooltip(
        message: 'Choose the experiment run shown on every page',
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => controller.isOpen ? controller.close() : controller.open(),
          child: Glass(
            radius: 12,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.science_outlined, size: 15, color: AppColors.textSecondary),
                const SizedBox(width: 8),
                Text(
                  current == null ? 'No run' : '${runLabel(current.seq)} · ${methodName(current.method)}',
                  style: const TextStyle(fontSize: 12.5),
                ),
                const SizedBox(width: 4),
                Icon(Icons.expand_more, size: 16, color: AppColors.textSecondary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Notifications extends ConsumerWidget {
  const _Notifications({required this.showText});
  final bool showText;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ov = ref.watch(overviewProvider).value;
    final drift = asJsonList(ov?['recent_drift_events']);
    final adapt = asJsonList(ov?['recent_adaptation_events']);
    final events = [
      for (final d in drift.reversed)
        ('Drift: ${d['method']} on window ${d['window']}', AppColors.purple, Icons.waves, AppPage.drift),
      for (final a in adapt.reversed)
        (
          'Adaptation ${a['decision']} (window ${a['window']})',
          AppColors.blue,
          Icons.published_with_changes,
          AppPage.adaptation,
        ),
    ];
    return GlassMenu<AppPage>(
      header: 'Recent events · this run',
      emptyText: 'No events for this run',
      minWidth: 300,
      onSelected: (page) => ref.read(navProvider.notifier).go(page),
      items: [
        for (final (text, color, icon, page) in events.take(12))
          GlassMenuItem(value: page, icon: icon, iconColor: color, label: Text(text)),
      ],
      builder: (context, controller) => Tooltip(
        message: 'Recent drift and adaptation events',
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => controller.isOpen ? controller.close() : controller.open(),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Badge(
                  isLabelVisible: events.isNotEmpty,
                  label: Text('${events.length}'),
                  backgroundColor: AppColors.purple,
                  offset: const Offset(8, -6),
                  child: Icon(Icons.notifications_none, size: 18, color: AppColors.textSecondary),
                ),
                if (showText) ...[
                  const SizedBox(width: 16),
                  Text('Notifications', style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ThemeToggle extends ConsumerWidget {
  const _ThemeToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(settingsProvider).themeMode;
    return GlassMenu<String>(
      header: 'Appearance',
      selected: mode,
      minWidth: 240,
      onSelected: (m) => ref.read(settingsProvider.notifier).update(ref.read(settingsProvider).copyWith(themeMode: m)),
      items: const [
        GlassMenuItem(value: 'dark', icon: Icons.dark_mode_outlined, label: Text('Dark · Security console')),
        GlassMenuItem(value: 'light', icon: Icons.light_mode_outlined, label: Text('Light · Frosted glass')),
        GlassMenuItem(value: 'system', icon: Icons.contrast_rounded, label: Text('Follow system')),
      ],
      builder: (context, controller) => IconButton(
        tooltip: 'Theme',
        onPressed: () => controller.isOpen ? controller.close() : controller.open(),
        icon: Icon(
          AppColors.isGlass ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
          size: 19,
          color: AppColors.textSecondary,
        ),
      ),
    );
  }
}
