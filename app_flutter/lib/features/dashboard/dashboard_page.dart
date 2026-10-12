import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/charts.dart';
import '../../core/format.dart';
import '../../core/run_guard.dart';
import '../../core/state.dart';
import '../../core/status.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

/// Per-window decision counts (benign / attack / unknown) from window metrics.
(List<double?>, List<double?>, List<double?>) decisionSeries(List<Json> windows) {
  final benign = <double?>[], attack = <double?>[], unknown = <double?>[];
  for (final w in windows) {
    final d = asJson(asJson(w['metrics'])['decision_distribution']);
    var b = 0.0, a = 0.0, u = 0.0;
    d.forEach((k, v) {
      final n = (v as num).toDouble();
      if (k == 'UNKNOWN') {
        u += n;
      } else if (isBenignLabel(k)) {
        b += n;
      } else {
        a += n;
      }
    });
    benign.add(b);
    attack.add(a);
    unknown.add(u);
  }
  return (benign, attack, unknown);
}

class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RunGuard(
      title: 'Dashboard',
      subtitle: 'Drift-aware open-world intrusion detection · Research workspace',
      builder: (run) {
        final ov = ref.watch(overviewProvider).value;
        final dist = ref.watch(classDistributionProvider).value;
        final kpis = asJson(ov?['kpis']);
        final decisions = asJson(dist?['decision']);
        final attacks = decisions.entries
            .where((e) => e.key != 'UNKNOWN' && !isBenignLabel(e.key))
            .fold<num>(0, (a, e) => a + (e.value as num));
        final benign = decisions.entries
            .where((e) => isBenignLabel(e.key))
            .fold<num>(0, (a, e) => a + (e.value as num));
        final unknown = (decisions['UNKNOWN'] as num?) ?? 0;
        final trends = asJsonList(ov?['trends']);
        final recentDrift = trends.reversed.take(3).any((t) => t['drift_triggered'] == true);
        final nDrift = asInt(kpis['drift_events']) ?? 0;
        return [
          StatRow(
            cards: [
              StatCard(
                label: 'Flows analyzed',
                value: fmtInt(kpis['flows'] as num?),
                caption: 'Replay window · ${run.window}/${run.totalWindows}',
              ),
              StatCard(
                label: 'Known attacks',
                value: fmtInt(attacks),
                caption: 'Predicted attack classes',
                color: AppColors.red,
              ),
              StatCard(
                label: 'Unknown / review',
                value: fmtInt(kpis['unknown_flows'] as num?),
                caption: 'Flagged for inspection',
                color: AppColors.orange,
              ),
              StatCard(
                label: 'Drift status',
                value: recentDrift ? 'Detected' : (nDrift > 0 ? 'Adapted' : 'Stable'),
                caption: '$nDrift drift event${nDrift == 1 ? '' : 's'} this run',
                color: recentDrift ? AppColors.purple : AppColors.green,
              ),
              StatCard(
                label: 'Active experiment',
                value: runLabel(run.seq),
                caption: '${titleCase(run.status)} · chronological replay',
                color: AppColors.green,
              ),
            ],
          ),
          ResponsiveRow(
            flex: const [3, 2],
            children: [
              const _TrendPanel(),
              Panel(
                title: 'Traffic classification',
                subtitle: 'Reported decisions for this run',
                // Same height as the trend chart so the two panels line up.
                child: SizedBox(
                  height: 230,
                  child: Center(
                    child: DonutChart(
                      centerTop: _compact(benign + attacks + unknown),
                      centerBottom: 'Flows',
                      slices: [
                        ('Benign', benign.toDouble(), AppColors.blue),
                        ('Known attack', attacks.toDouble(), AppColors.red),
                        ('Unknown / review', unknown.toDouble(), AppColors.orange),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
          ResponsiveRow(
            flex: const [3, 2],
            children: [
              const _RecentReview(),
              _SystemPanel(run: run),
            ],
          ),
        ];
      },
    );
  }

  static String _compact(num n) => n >= 1000 ? '${(n / 1000).toStringAsFixed(1)}K' : '$n';
}

class _TrendPanel extends ConsumerWidget {
  const _TrendPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final metrics = ref.watch(metricsProvider);
    return Panel(
      title: 'Traffic & detection trend',
      subtitle: 'Decisions per replay window',
      trailing: Legend([('Benign', AppColors.blue), ('Unknown', AppColors.orange), ('Attack', AppColors.red)]),
      child: AsyncView(
        value: metrics,
        builder: (m) {
          final (b, a, u) = decisionSeries(m?.windows ?? const []);
          final drift = [
            for (final (i, w) in (m?.windows ?? const <Json>[]).indexed)
              if (asJson(w['drift_scores']).values.any((d) => asJson(d)['triggered'] == true)) i,
          ];
          return TrendChart(
            height: 230,
            minY: 0,
            markers: drift,
            yFormat: (v) => v.toStringAsFixed(0),
            series: [
              Series('Benign', AppColors.blue, b),
              Series('Unknown', AppColors.orange, u),
              Series('Attack', AppColors.red, a),
            ],
          );
        },
      ),
    );
  }
}

class _RecentReview extends ConsumerWidget {
  const _RecentReview();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final alerts = ref.watch(recentAlertsProvider);
    final utc = ref.watch(settingsProvider).utc;
    return Panel(
      title: 'Recent review events',
      trailing: FilledButton(
        onPressed: () => ref.read(navProvider.notifier).go(AppPage.alerts),
        child: const Text('View all'),
      ),
      child: AsyncView(
        value: alerts,
        builder: (page) => SentinelTable(
          columns: const [TableCol('Time'), TableCol('Prediction', flex: 2), TableCol('Score'), TableCol('Status')],
          emptyText: 'No alerts in this run',
          onTap: (_) => ref.read(navProvider.notifier).go(AppPage.alerts),
          rows: [
            for (final a in page?.items ?? const <Alert>[])
              [
                Text(fmtTime(a.timestamp, utc: utc)),
                decisionLabel(a.decision),
                Text(fmtNum(a.decision == 'UNKNOWN' ? a.confidence : (a.attackScore ?? a.confidence), 4)),
                severityLabel(a.severity),
              ],
          ],
        ),
      ),
    );
  }
}

class _SystemPanel extends ConsumerWidget {
  const _SystemPanel({required this.run});
  final Run run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sys = ref.watch(systemProvider);
    final progress = run.totalWindows == 0 ? 0.0 : run.window / run.totalWindows;
    return Panel(
      title: 'System & model status',
      child: Column(
        children: [
          AsyncView(
            value: sys,
            builder: (s) => Column(
              children: [
                Meter(label: 'CPU usage', value: s.cpu / 100, color: AppColors.blue),
                const SizedBox(height: 18),
                Meter(label: 'Memory usage', value: s.memory / 100, color: AppColors.purple),
                const SizedBox(height: 18),
                Meter(label: 'Disk usage', value: s.disk / 100, color: AppColors.orange),
              ],
            ),
          ),
          const SizedBox(height: 18),
          Meter(
            label: 'Replay progress · ${titleCase(run.status)}',
            value: progress,
            color: AppColors.green,
            valueText: '${run.window}/${run.totalWindows} windows',
          ),
        ],
      ),
    );
  }
}
