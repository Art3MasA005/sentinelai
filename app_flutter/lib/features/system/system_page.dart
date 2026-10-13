import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/format.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

class SystemPage extends ConsumerStatefulWidget {
  const SystemPage({super.key});

  @override
  ConsumerState<SystemPage> createState() => _SystemPageState();
}

class _SystemPageState extends ConsumerState<SystemPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Resource usage is live: refresh while this page is visible (the shell keeps visited pages alive
    // offstage with tickers muted, and a muted page should not poll).
    _timer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (mounted && TickerMode.valuesOf(context).enabled) ref.invalidate(systemProvider);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Color _levelColor(String l) => switch (l) {
    'error' => AppColors.red,
    'warning' => AppColors.orange,
    _ => AppColors.blue,
  };

  @override
  Widget build(BuildContext context) {
    final health = ref.watch(healthProvider);
    final sys = ref.watch(systemProvider);
    final s = sys.value;
    final ok = health.value?['status'] == 'ok';
    final base = Uri.tryParse(ref.watch(settingsProvider).baseUrl);
    final worker = s?.worker ?? const <String, dynamic>{};
    final busy = worker['state'] == 'busy';
    final active = asJsonList(worker['runs']);
    final gpu = s?.gpu;
    final utc = ref.watch(settingsProvider).utc;
    final runs = ref.watch(runsProvider).value ?? const <Run>[];
    return PageScaffold(
      title: 'System',
      subtitle: 'Inspect local services, model versions, resource usage, and diagnostic logs',
      children: [
        StatRow(
          cards: [
            StatCard(
              label: 'Backend API',
              value: health.hasError && !health.hasValue ? 'Offline' : (ok ? 'Healthy' : 'Degraded'),
              caption: '${base?.host ?? '—'}:${base?.port ?? ''} · FastAPI ${health.value?['version'] ?? ''}',
              color: ok ? AppColors.green : AppColors.red,
            ),
            StatCard(
              label: 'ML worker',
              value: s == null ? '—' : (busy ? 'Busy' : 'Idle'),
              caption: busy
                  ? '${active.length} run${active.length == 1 ? '' : 's'} replaying'
                  : 'No active training job',
              color: busy ? AppColors.orange : AppColors.blue,
            ),
            StatCard(
              label: 'Storage',
              value: s == null ? '—' : (s.diskFreeGb > 2 ? 'Available' : 'Low space'),
              caption: s == null
                  ? 'Local results directory'
                  : '${s.diskFreeGb.toStringAsFixed(1)} GB free · results dir',
              color: s != null && s.diskFreeGb <= 2 ? AppColors.red : AppColors.green,
            ),
            StatCard(
              label: 'GPU',
              value: gpu == null ? 'Not detected' : '${gpu['name']}'.replaceFirst('NVIDIA GeForce ', ''),
              caption: gpu == null ? 'CPU-only (fine for tree models)' : 'Detected by backend',
              color: AppColors.purple,
            ),
          ],
        ),
        if (sys.hasError && !sys.hasValue) Panel(child: ErrorNote(sys.error!)),
        ResponsiveRow(
          children: [
            Panel(
              title: 'Service health',
              child: SentinelTable(
                columns: const [TableCol('Service', flex: 2), TableCol('Version'), TableCol('Status')],
                rows: [
                  for (final svc in s?.services ?? const <Json>[])
                    [
                      Text('${svc['name']}'),
                      Text('${svc['version'] ?? '—'}'),
                      StatusLabel(
                        '${svc['status']}',
                        color: svc['ok'] == true ? AppColors.green : AppColors.textSecondary,
                        icon: svc['ok'] == true ? Icons.check_circle_outline : Icons.remove_circle_outline,
                      ),
                    ],
                ],
              ),
            ),
            Panel(
              title: 'Resource usage',
              subtitle: 'Live · refreshed every 3 s',
              child: s == null
                  ? const SizedBox(height: 160, child: Center(child: CircularProgressIndicator(strokeWidth: 2)))
                  : Column(
                      children: [
                        Meter(label: 'CPU', value: s.cpu / 100, color: AppColors.blue),
                        const SizedBox(height: 18),
                        Meter(
                          label: 'RAM',
                          value: s.memory / 100,
                          color: AppColors.purple,
                          valueText: '${s.memory.round()}% · ${s.j['memory_used_gb']} / ${s.j['memory_total_gb']} GB',
                        ),
                        const SizedBox(height: 18),
                        Meter(label: 'Disk', value: s.disk / 100, color: AppColors.orange),
                        if (gpu != null) ...[
                          const SizedBox(height: 18),
                          Meter(
                            label: 'GPU memory',
                            value: (asDouble(gpu['memory_percent']) ?? 0) / 100,
                            color: AppColors.green,
                          ),
                        ],
                      ],
                    ),
            ),
          ],
        ),
        if (active.isNotEmpty)
          Panel(
            title: 'Active replays',
            child: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final r in active)
                  Pill('${r['name']} · ${r['status']}', color: AppColors.orange, icon: Icons.play_circle_outline),
              ],
            ),
          ),
        Panel(
          title: 'Diagnostic events',
          subtitle: 'Latest worker log lines from the three most recent runs',
          child: SentinelTable(
            columns: const [
              TableCol('Time'),
              TableCol('Component'),
              TableCol('Event', flex: 4),
              TableCol('Run'),
              TableCol('Level'),
            ],
            emptyText: 'No diagnostic events yet',
            rows: [
              for (final e in (s?.diagnostics ?? const <Json>[]).take(25))
                [
                  Text(fmtTime(e['time'], utc: utc)),
                  Text('${e['component']}'),
                  Tooltip(
                    message: '${e['event']}',
                    child: Text('${e['event']}', overflow: TextOverflow.ellipsis),
                  ),
                  Text(runLabel(runs.where((r) => r.id == e['run_id']).firstOrNull?.seq)),
                  StatusLabel(
                    titleCase('${e['level']}'),
                    color: _levelColor('${e['level']}'),
                    icon: switch ('${e['level']}') {
                      'error' => Icons.error_outline,
                      'warning' => Icons.warning_amber_rounded,
                      _ => Icons.info_outline,
                    },
                  ),
                ],
            ],
          ),
        ),
      ],
    );
  }
}
