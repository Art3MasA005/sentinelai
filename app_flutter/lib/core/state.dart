import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api/api_client.dart';
import 'api/models.dart';
import 'auth.dart';

// ---------------------------------------------------------------- navigation

enum AppPage {
  dashboard('Dashboard', Icons.grid_view_rounded),
  alerts('Alerts', Icons.notifications_active_outlined),
  traffic('Traffic Monitor', Icons.show_chart_rounded),
  analysis('Analysis', Icons.radar_rounded),
  drift('Drift Monitor', Icons.waves_rounded),
  adaptation('Adaptation Center', Icons.published_with_changes_rounded),
  experiments('Experiments', Icons.science_outlined),
  reports('Reports', Icons.description_outlined),
  rules('Rules', Icons.flag_outlined),
  system('System', Icons.memory_rounded),
  settings('Settings', Icons.settings_outlined);

  const AppPage(this.label, this.icon);
  final String label;
  final IconData icon;
}

class NavNotifier extends Notifier<AppPage> {
  @override
  AppPage build() {
    // `?page=alerts` deep link (web) wins over the configured landing page.
    final landing = Uri.base.queryParameters['page'] ?? ref.read(settingsProvider).landingPage;
    return AppPage.values.firstWhere((p) => p.name == landing, orElse: () => AppPage.dashboard);
  }

  void go(AppPage page) => state = page;
}

final navProvider = NotifierProvider<NavNotifier, AppPage>(NavNotifier.new);

// ---------------------------------------------------------------- settings

final prefsProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError('override in main'));

class AppSettings {
  const AppSettings({
    this.baseUrl = 'http://127.0.0.1:8765',
    this.timeoutSeconds = 10,
    this.landingPage = 'dashboard',
    this.utc = false,
    this.autoLoadLast = true,
    this.lastRunId,
    this.themeMode = 'dark',
  });

  final String baseUrl;
  final int timeoutSeconds;
  final String landingPage;
  final bool utc;
  final bool autoLoadLast;
  final String? lastRunId;

  /// 'dark' | 'light' (frosted glass) | 'system'.
  final String themeMode;

  AppSettings copyWith({
    String? baseUrl,
    int? timeoutSeconds,
    String? landingPage,
    bool? utc,
    bool? autoLoadLast,
    String? lastRunId,
    String? themeMode,
  }) => AppSettings(
    baseUrl: baseUrl ?? this.baseUrl,
    timeoutSeconds: timeoutSeconds ?? this.timeoutSeconds,
    landingPage: landingPage ?? this.landingPage,
    utc: utc ?? this.utc,
    autoLoadLast: autoLoadLast ?? this.autoLoadLast,
    lastRunId: lastRunId ?? this.lastRunId,
    themeMode: themeMode ?? this.themeMode,
  );
}

class SettingsNotifier extends Notifier<AppSettings> {
  SharedPreferences get _p => ref.read(prefsProvider);

  @override
  AppSettings build() {
    const d = AppSettings();
    return AppSettings(
      // `?api=` deep link (web) overrides the saved backend address.
      baseUrl: Uri.base.queryParameters['api'] ?? _p.getString('baseUrl') ?? d.baseUrl,
      timeoutSeconds: _p.getInt('timeoutSeconds') ?? d.timeoutSeconds,
      landingPage: _p.getString('landingPage') ?? d.landingPage,
      utc: _p.getBool('utc') ?? d.utc,
      autoLoadLast: _p.getBool('autoLoadLast') ?? d.autoLoadLast,
      lastRunId: _p.getString('lastRunId'),
      // `?theme=light` deep link (web) overrides the saved choice.
      themeMode: Uri.base.queryParameters['theme'] ?? _p.getString('themeMode') ?? d.themeMode,
    );
  }

  void update(AppSettings s) {
    state = s;
    _p
      ..setString('baseUrl', s.baseUrl)
      ..setInt('timeoutSeconds', s.timeoutSeconds)
      ..setString('landingPage', s.landingPage)
      ..setBool('utc', s.utc)
      ..setBool('autoLoadLast', s.autoLoadLast)
      ..setString('themeMode', s.themeMode);
    if (s.lastRunId != null) _p.setString('lastRunId', s.lastRunId!);
  }
}

final settingsProvider = NotifierProvider<SettingsNotifier, AppSettings>(SettingsNotifier.new);

final apiProvider = Provider<ApiClient>((ref) {
  final s = ref.watch(settingsProvider);
  return ApiClient(
    baseUrl: s.baseUrl,
    timeout: Duration(seconds: s.timeoutSeconds),
    token: ref.watch(sessionTokenProvider),
  );
});

// ---------------------------------------------------------------- refresh

/// Bumped by the shell while a run is active so that live views re-fetch.
class RefreshTick extends Notifier<int> {
  @override
  int build() => 0;
  void bump() => state++;
}

final refreshTickProvider = NotifierProvider<RefreshTick, int>(RefreshTick.new);

final healthProvider = FutureProvider<Json>((ref) => ref.watch(apiProvider).health());

final systemProvider = FutureProvider<SystemStatus>((ref) {
  ref.watch(refreshTickProvider);
  return ref.watch(apiProvider).system();
});

// ---------------------------------------------------------------- runs

/// Every run, newest first. The API serves at most 200 per page, so later pages are fetched too.
final runsProvider = FutureProvider<List<Run>>((ref) async {
  ref.watch(refreshTickProvider);
  final api = ref.watch(apiProvider);
  final first = await api.runs();
  final seen = <String>{};
  final runs = [
    for (final r in first.items)
      if (seen.add(r.id)) r,
  ];
  for (var page = 2; (page - 1) * first.pageSize < first.total; page++) {
    // A run created between two requests shifts the pages by one; `seen` drops the repeat.
    for (final r in (await api.runs(page: page)).items) {
      if (seen.add(r.id)) runs.add(r);
    }
  }
  return runs;
});

class SelectedRun extends Notifier<String?> {
  @override
  String? build() {
    final s = ref.read(settingsProvider);
    return s.autoLoadLast ? s.lastRunId : null;
  }

  void select(String? runId) {
    state = runId;
    if (runId != null) {
      final settings = ref.read(settingsProvider.notifier);
      settings.update(ref.read(settingsProvider).copyWith(lastRunId: runId));
    }
  }
}

final selectedRunIdProvider = NotifierProvider<SelectedRun, String?>(SelectedRun.new);

/// The run every page shows: the explicit selection, else an active run, else the newest completed one.
final currentRunProvider = Provider<Run?>((ref) {
  final runs = ref.watch(runsProvider).value;
  if (runs == null || runs.isEmpty) return null;
  final selected = ref.watch(selectedRunIdProvider);
  for (final r in runs) {
    if (r.id == selected) return r;
  }
  return runs.where((r) => r.isActive).firstOrNull ??
      runs.where((r) => r.status == 'completed').firstOrNull ??
      runs.first;
});

final currentRunIdProvider = Provider<String?>((ref) => ref.watch(currentRunProvider)?.id);

// ---------------------------------------------------------------- per-run data

FutureProvider<T?> _perRun<T>(Future<T> Function(ApiClient api, String runId) load) => FutureProvider<T?>((ref) {
  ref.watch(refreshTickProvider);
  final id = ref.watch(currentRunIdProvider);
  return id == null ? Future.value(null) : load(ref.watch(apiProvider), id);
});

final overviewProvider = _perRun((api, id) => api.overview(id));
final metricsProvider = _perRun((api, id) => api.metrics(id));
final classDistributionProvider = _perRun((api, id) => api.classDistribution(id));
final driftEventsProvider = _perRun((api, id) => api.driftEvents(id));
final adaptationEventsProvider = _perRun((api, id) => api.adaptationEvents(id));
final modelVersionsProvider = _perRun((api, id) => api.models(id));
final alertSummaryProvider = _perRun((api, id) => api.alertSummary(id));
final recentAlertsProvider = _perRun((api, id) => api.alerts(id, {'page_size': 5}));

final datasetsProvider = FutureProvider<List<Dataset>>((ref) => ref.watch(apiProvider).datasets());
final policiesProvider = FutureProvider<List<Json>>((ref) => ref.watch(apiProvider).policies());
final reportStatsProvider = FutureProvider<Json>((ref) {
  ref.watch(refreshTickProvider);
  return ref.watch(apiProvider).reportStats();
});
