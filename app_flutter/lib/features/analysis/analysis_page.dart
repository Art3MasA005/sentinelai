import 'dart:math' as math;

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

class AnalysisPage extends ConsumerWidget {
  const AnalysisPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RunGuard(
      title: 'Analysis',
      subtitle: 'Evaluate detection quality, unknown rejection, and performance over time',
      builder: (run) {
        final metrics = ref.watch(metricsProvider);
        final m = metrics.value;
        final o = m?.overall ?? const <String, dynamic>{};
        if (m != null && m.overall.isEmpty) {
          return [
            Panel(
              child: EmptyState(
                run.isActive
                    ? 'Overall metrics appear when the run completes (window ${run.window}/${run.totalWindows}).'
                    : 'No metrics for this run.',
                icon: Icons.hourglass_empty,
              ),
            ),
            if (m.windows.isNotEmpty) _WindowPerf(windows: m.windows, defs: m.definitions),
          ];
        }
        return [
          StatRow(
            cards: [
              StatCard(
                label: 'Macro F1',
                value: fmtNum(o['macro_f1'] as num?),
                caption: 'Open-set, classes in ground truth',
              ),
              StatCard(
                label: 'Unknown AUROC',
                value: fmtNum(o['unknown_auroc'] as num?),
                caption: 'Unseen-class flows vs known',
                color: AppColors.purple,
              ),
              StatCard(
                label: 'False positive rate',
                value: fmtPct(o['fpr'] as num?),
                caption: 'Benign → attack (reviews excluded)',
                color: AppColors.orange,
              ),
              StatCard(
                label: 'Forgetting',
                value: fmtPp(o['forgetting_max'] as num?),
                caption: 'Max drop on reference set',
                color: AppColors.red,
              ),
            ],
          ),
          if (m != null)
            ResponsiveRow(
              flex: const [3, 2],
              children: [
                _WindowPerf(windows: m.windows, defs: m.definitions),
                _Summary(o: o, defs: m.definitions),
              ],
            ),
          if (m != null) _PerClass(metrics: m),
          if (m != null) _Confusion(confusion: m.confusion),
        ];
      },
    );
  }
}

class _WindowPerf extends StatelessWidget {
  const _WindowPerf({required this.windows, required this.defs});
  final List<Json> windows;
  final Json defs;

  @override
  Widget build(BuildContext context) {
    List<double?> pick(String k) => [for (final w in windows) asDouble(asJson(w['metrics'])[k])];
    return Panel(
      title: 'Per-window detection performance',
      trailing: Legend([
        ('Macro F1', AppColors.blue),
        ('Reference F1', AppColors.purple),
        ('Unknown recall', AppColors.orange),
        ('FPR', AppColors.red),
      ]),
      child: TrendChart(
        height: 330, // matches the metric summary panel beside it
        minY: 0,
        maxY: 1,
        yFormat: (v) => v.toStringAsFixed(2),
        series: [
          Series('Macro F1', AppColors.blue, pick('macro_f1')),
          Series('Reference F1', AppColors.purple, pick('ref_macro_f1')),
          Series('Unknown recall', AppColors.orange, pick('unknown_recall'), dashed: true),
          Series('FPR', AppColors.red, pick('fpr')),
        ],
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.o, required this.defs});
  final Json o;
  final Json defs;

  Widget _row(String label, String value, Color color, String? defKey) => Tooltip(
    message: defKey == null ? '' : '${defs[defKey] ?? ''}',
    child: KeyValueRow(label, value, valueColor: color, labelWidth: 200),
  );

  @override
  Widget build(BuildContext context) {
    final delay = asJson(o['adaptation_delay_windows']);
    return Panel(
      title: 'Metric summary',
      child: Column(
        children: [
          _row('Precision (macro)', fmtNum(o['macro_precision'] as num?), AppColors.blue, 'macro_precision'),
          _row('Recall (macro)', fmtNum(o['macro_recall'] as num?), AppColors.green, 'macro_recall'),
          _row('PR-AUC', fmtNum(o['pr_auc'] as num?), AppColors.purple, 'pr_auc'),
          _row('Unknown recall', fmtPct(o['unknown_recall'] as num?), AppColors.orange, 'unknown_recall'),
          _row(
            'Unknown false reject',
            fmtPct(o['known_false_unknown_rate'] as num?),
            AppColors.orange,
            'known_false_unknown_rate',
          ),
          _row(
            'Median inference',
            '${fmtNum(o['latency_ms_per_flow_median'] as num?, 3)} ms/flow',
            AppColors.cyan,
            'latency_ms_per_flow',
          ),
          _row(
            'Adaptation delay',
            delay['mean'] == null ? '—' : '${fmtNum(delay['mean'] as num, 1)} windows',
            AppColors.text,
            'adaptation_delay_windows',
          ),
          _row(
            'Labels used',
            '${fmtInt(o['labels_used'] as num?)} (${fmtPct(o['label_fraction'] as num?)})',
            AppColors.text,
            'labels_used',
          ),
        ],
      ),
    );
  }
}

class _PerClass extends StatelessWidget {
  const _PerClass({required this.metrics});
  final RunMetrics metrics;

  @override
  Widget build(BuildContext context) {
    final o = metrics.overall;
    final rec = asJson(o['per_class_recall']);
    final prec = asJson(o['per_class_precision']);
    final f1 = asJson(o['per_class_f1']);
    final labels = (metrics.confusion['labels'] as List?)?.cast<String>() ?? const <String>[];
    final matrix = (metrics.confusion['matrix'] as List?) ?? const [];
    int support(String c) {
      final i = labels.indexOf(c);
      return i < 0 ? 0 : (matrix[i] as List).fold<int>(0, (a, v) => a + (v as int));
    }

    final initial = ((metrics.provenance['initial_classes'] as List?) ?? const []).cast<String>();
    final classes = rec.keys.toList()..sort((a, b) => a == 'UNKNOWN' ? 1 : (b == 'UNKNOWN' ? -1 : a.compareTo(b)));
    return Panel(
      title: 'Per-class evaluation',
      subtitle: 'UNKNOWN row = flows of classes the deployed model had not seen (unknown rejection test)',
      child: SentinelTable(
        columns: const [
          TableCol('Class', flex: 2),
          TableCol('Precision'),
          TableCol('Recall'),
          TableCol('F1 score'),
          TableCol('Support'),
          TableCol('Type'),
        ],
        rows: [
          for (final c in classes)
            [
              Text(c == 'UNKNOWN' ? 'Unseen classes (UNKNOWN)' : c),
              Text(c == 'UNKNOWN' ? '—' : fmtNum(prec[c] as num?, 3)),
              Text(fmtNum(rec[c] as num?, 3)),
              Text(c == 'UNKNOWN' ? '—' : fmtNum(f1[c] as num?, 3)),
              Text(fmtInt(support(c))),
              c == 'UNKNOWN'
                  ? StatusLabel('Unknown test', color: AppColors.orange, icon: Icons.help_outline)
                  : initial.contains(c)
                  ? StatusLabel('Known', color: isBenignLabel(c) ? AppColors.green : AppColors.blue)
                  : StatusLabel('Learned in stream', color: AppColors.purple, icon: Icons.school_outlined),
            ],
        ],
      ),
    );
  }
}

class _Confusion extends StatelessWidget {
  const _Confusion({required this.confusion});
  final Json confusion;

  @override
  Widget build(BuildContext context) {
    final labels = (confusion['labels'] as List?)?.cast<String>() ?? const <String>[];
    final m = [for (final r in (confusion['matrix'] as List? ?? const [])) (r as List).cast<int>()];
    if (labels.isEmpty) return const SizedBox();
    final maxV = m.expand((r) => r).fold<int>(1, math.max);
    const cell = 76.0;
    return Panel(
      title: 'Confusion matrix',
      subtitle: 'Rows = open-set ground truth, columns = reported decision',
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const SizedBox(width: 150),
                for (final l in labels)
                  SizedBox(
                    width: cell,
                    child: Text(
                      l,
                      textAlign: TextAlign.center,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyles.label,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            for (final (i, row) in m.indexed)
              Row(
                children: [
                  SizedBox(
                    width: 150,
                    child: Text(labels[i], overflow: TextOverflow.ellipsis, style: TextStyles.secondary),
                  ),
                  for (final (j, v) in row.indexed) _cell(i, j, v, labels[j] == 'UNKNOWN', maxV, cell),
                ],
              ),
            const SizedBox(height: 14),
            Legend([
              ('Correct', AppColors.blue),
              ('Misclassified', AppColors.red),
              ('Sent to review (UNKNOWN)', AppColors.orange),
            ]),
          ],
        ),
      ),
    );
  }

  /// Blue = correct, orange = routed to review (not an error verdict), red = wrong class.
  Widget _cell(int i, int j, int v, bool reviewColumn, int maxV, double cell) {
    final base = i == j
        ? AppColors.blue
        : reviewColumn
        ? AppColors.orange
        : AppColors.red;
    final alpha = v == 0 ? 0.0 : 0.15 + 0.8 * math.sqrt(v / maxV);
    return Container(
      width: cell - 4,
      height: 34,
      margin: const EdgeInsets.all(2),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        color: v == 0 ? AppColors.track : base.withValues(alpha: alpha),
      ),
      child: Text(
        fmtInt(v),
        style: TextStyles.mono.copyWith(
          color: alpha > 0.55 ? Colors.white : (v == 0 ? AppColors.textMuted : AppColors.text),
          fontWeight: v == 0 ? FontWeight.w400 : FontWeight.w600,
        ),
      ),
    );
  }
}
