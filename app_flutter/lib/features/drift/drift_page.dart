import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/charts.dart';
import '../../core/format.dart';
import '../../core/run_guard.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';

const _methodNames = {'ks': 'KS test', 'psi': 'PSI', 'confidence': 'Confidence drop'};
Map<String, Color> get _methodColors => {'ks': AppColors.purple, 'psi': AppColors.blue, 'confidence': AppColors.orange};

class _Method extends Notifier<String?> {
  @override
  String? build() => null;
  void set(String? m) => state = m;
}

final _methodProvider = NotifierProvider<_Method, String?>(_Method.new);

class _SelectedEvent extends Notifier<String?> {
  @override
  String? build() {
    ref.watch(currentRunIdProvider);
    return null;
  }

  void set(String? id) => state = id;
}

final _eventProvider = NotifierProvider<_SelectedEvent, String?>(_SelectedEvent.new);

class DriftPage extends ConsumerWidget {
  const DriftPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RunGuard(
      title: 'Drift Monitor',
      subtitle: 'Reference vs current window, detector scores against thresholds, and event history',
      builder: (run) {
        final metrics = ref.watch(metricsProvider).value;
        final events = ref.watch(driftEventsProvider).value?.items ?? const <Json>[];
        final windows = metrics?.windows ?? const <Json>[];
        final methods = <String>{for (final w in windows) ...asJson(w['drift_scores']).keys}.toList();
        final selected = ref.watch(_methodProvider) ?? (methods.isEmpty ? null : methods.first);
        final last = windows.isEmpty ? null : windows.last;
        final lastTriggered =
            last != null && asJson(last['drift_scores']).values.any((d) => asJson(d)['triggered'] == true);
        final lastEvent = events.isEmpty ? null : events.last;
        final refWindow = asInt(asJson(lastEvent?['details'])['reference_window']);
        return [
          StatRow(
            cards: [
              StatCard(
                label: 'Drift events',
                value: fmtInt(events.length),
                caption: 'Detector triggers (cooldown applied)',
                color: AppColors.purple,
              ),
              StatCard(
                label: 'Current window',
                value: lastTriggered ? 'Drifting' : 'Stable',
                caption: last == null ? 'No windows yet' : 'Window W${last['window']}',
                color: lastTriggered ? AppColors.orange : AppColors.green,
              ),
              StatCard(
                label: 'Last event',
                value: lastEvent == null ? '—' : 'W${lastEvent['window']}',
                caption: lastEvent == null ? 'No drift detected' : _methodNames[lastEvent['method']] ?? '',
                color: AppColors.blue,
              ),
              StatCard(
                label: 'Reference',
                value: refWindow == null || refWindow < 0 ? 'Training' : 'W$refWindow',
                caption: 'Updated after accepted adaptation',
                color: AppColors.cyan,
              ),
            ],
          ),
          Panel(
            title: 'Detector score vs threshold',
            subtitle: 'Drift = the input distribution changed. It is not evidence of an attack.',
            trailing: Wrap(
              spacing: 8,
              children: [
                for (final m in methods)
                  ChoiceChip(
                    label: Text(_methodNames[m] ?? m),
                    selected: m == selected,
                    onSelected: (_) => ref.read(_methodProvider.notifier).set(m),
                    selectedColor: AppColors.navActive,
                    side: BorderSide(color: AppColors.border),
                  ),
              ],
            ),
            child: selected == null
                ? const EmptyState('No drift detector scores yet.')
                : _ScoreChart(windows: windows, method: selected),
          ),
          ResponsiveRow(
            flex: const [3, 2],
            children: [
              _History(events: events),
              _EventDetail(
                event: events.where((e) => e['event_id'] == ref.watch(_eventProvider)).firstOrNull ?? lastEvent,
                featureNames:
                    ((metrics?.provenance['feature_names'] ?? run.summary?['feature_names']) as List?)
                        ?.cast<String>() ??
                    const [],
              ),
            ],
          ),
        ];
      },
    );
  }
}

class _ScoreChart extends StatelessWidget {
  const _ScoreChart({required this.windows, required this.method});
  final List<Json> windows;
  final String method;

  @override
  Widget build(BuildContext context) {
    final d = [for (final w in windows) asJson(asJson(w['drift_scores'])[method])];
    final triggered = [
      for (final (i, x) in d.indexed)
        if (x['triggered'] == true) i,
    ];
    final color = _methodColors[method] ?? AppColors.purple;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TrendChart(
          height: 240,
          markers: triggered,
          yFormat: (v) => v.toStringAsFixed(2),
          series: [
            Series('Score', color, [for (final x in d) asDouble(x['score'])]),
            Series('Threshold', AppColors.red, [for (final x in d) asDouble(x['threshold'])], dashed: true),
          ],
        ),
        const SizedBox(height: 8),
        Legend([
          ('${_methodNames[method] ?? method} score', color),
          ('Threshold', AppColors.red),
          ('Triggered window', AppColors.purple.withValues(alpha: 0.5)),
        ]),
      ],
    );
  }
}

class _History extends ConsumerWidget {
  const _History({required this.events});
  final List<Json> events;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final utc = ref.watch(settingsProvider).utc;
    final rows = events.reversed.toList();
    return Panel(
      title: 'Drift event history',
      child: SentinelTable(
        columns: const [
          TableCol('Window'),
          TableCol('Method', flex: 2),
          TableCol('Score'),
          TableCol('Threshold'),
          TableCol('Window span', flex: 2),
        ],
        emptyText: 'No drift events in this run',
        selected: rows.indexWhere((e) => e['event_id'] == ref.watch(_eventProvider)),
        onTap: (i) => ref.read(_eventProvider.notifier).set(rows[i]['event_id'] as String),
        rows: [
          for (final e in rows.take(200))
            [
              Text('W${e['window']}'),
              Text(_methodNames[e['method']] ?? '${e['method']}'),
              Text(fmtNum(e['score'] as num, 3), style: TextStyle(color: AppColors.orange)),
              Text(fmtNum(e['threshold'] as num, 3)),
              Text('${fmtTime(e['window_start'], utc: utc)}–${fmtTime(e['window_end'], utc: utc)}'),
            ],
        ],
      ),
    );
  }
}

class _EventDetail extends StatelessWidget {
  const _EventDetail({required this.event, required this.featureNames});
  final Json? event;
  final List<String> featureNames;

  @override
  Widget build(BuildContext context) {
    final e = event;
    if (e == null) {
      return const Panel(title: 'Reference vs current', child: EmptyState('Select a drift event.'));
    }
    final d = asJson(e['details']);
    final top = ((d['top_feature_indices'] as List?) ?? const []).cast<int>();
    String fname(int i) => i < featureNames.length ? featureNames[i] : 'feature #$i';
    final refWindow = asInt(d['reference_window']);
    return Panel(
      title: 'Reference vs current',
      subtitle: '${_methodNames[e['method']] ?? e['method']} · event ${e['event_id']}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KeyValueRow('Reference window', refWindow == null || refWindow < 0 ? 'Training period' : 'W$refWindow'),
          KeyValueRow('Current window', 'W${e['window']}'),
          KeyValueRow(
            'Score / threshold',
            '${fmtNum(e['score'] as num, 4)} / ${fmtNum(e['threshold'] as num, 4)}',
            valueColor: AppColors.orange,
          ),
          if (d['features_drifted'] != null)
            KeyValueRow('Features drifted', '${d['features_drifted']} of ${d['features_tested']}'),
          if (d['corrected_alpha'] != null) KeyValueRow('Bonferroni α', fmtNum(d['corrected_alpha'] as num, 5)),
          if (d['reference_confidence'] != null)
            KeyValueRow(
              'Mean confidence',
              '${fmtNum(d['reference_confidence'] as num, 4)} → ${fmtNum(d['window_confidence'] as num, 4)}',
            ),
          if (top.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text('MOST SHIFTED FEATURES', style: TextStyles.label),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [for (final i in top) Pill(fname(i), color: AppColors.purple)]),
          ],
        ],
      ),
    );
  }
}
