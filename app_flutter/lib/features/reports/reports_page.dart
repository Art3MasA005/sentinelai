import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api/models.dart';
import '../../core/format.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../experiments/experiments_page.dart';

/// Runs compared on this page: the Experiments-page selection, else the newest completed runs.
final _comparedIdsProvider = Provider<List<String>>((ref) {
  final picked = ref.watch(compareSelectionProvider);
  final completed = (ref.watch(runsProvider).value ?? const <Run>[]).where((r) => r.status == 'completed');
  if (picked.length >= 2) {
    return [
      for (final r in completed)
        if (picked.contains(r.id)) r.id,
    ];
  }
  return completed.take(4).map((r) => r.id).toList();
});

final _comparisonProvider = FutureProvider<Json?>((ref) {
  final ids = ref.watch(_comparedIdsProvider);
  return ids.length < 2 ? Future.value(null) : ref.watch(apiProvider).compare(ids);
});

/// Column: label, metric key, format, higher-is-better.
typedef _Col = (String, String, String Function(num?), bool);

final List<_Col> _cols = [
  ('Macro F1', 'macro_f1', (v) => fmtNum(v), true),
  ('Unknown AUROC', 'unknown_auroc', (v) => fmtNum(v), true),
  ('Unknown recall', 'unknown_recall', (v) => fmtPct(v), true),
  ('FPR', 'fpr', (v) => fmtPct(v), false),
  ('Forgetting', 'forgetting_max', (v) => fmtPp(v), false),
  ('Labels used', 'labels_used', (v) => fmtInt(v), false),
];

class ReportsPage extends ConsumerWidget {
  const ReportsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stats = ref.watch(reportStatsProvider).value;
    final runs = ref.watch(runsProvider).value ?? const <Run>[];
    final ids = ref.watch(_comparedIdsProvider);
    final last = asJson(stats?['last_export']);
    final lastRun = runs.where((r) => r.id == last['run_id']).firstOrNull;
    final utc = ref.watch(settingsProvider).utc;
    return PageScaffold(
      title: 'Reports',
      subtitle: 'Compare experiment runs and export reproducible paper-ready results',
      children: [
        StatRow(
          cards: [
            StatCard(
              label: 'Completed runs',
              value: fmtInt(stats?['completed_runs'] as num?),
              caption: 'Local results archive',
            ),
            StatCard(
              label: 'Compared runs',
              value: fmtInt(ids.length),
              caption: ref.watch(compareSelectionProvider).length >= 2 ? 'Picked on Experiments' : 'Newest completed',
              color: AppColors.purple,
            ),
            StatCard(
              label: 'Exports this week',
              value: fmtInt(stats?['exports_this_week'] as num?),
              caption: 'CSV / JSON / ZIP',
              color: AppColors.green,
            ),
            StatCard(
              label: 'Last export',
              value: lastRun == null ? '—' : runLabel(lastRun.seq),
              caption: last.isEmpty
                  ? 'Nothing exported yet'
                  : '${last['format']} · ${fmtRelativeDay(last['at'], utc: utc)}',
              color: AppColors.orange,
            ),
          ],
        ),
        const _Comparison(),
        const ResponsiveRow(flex: [3, 2], children: [_Exports(), _Checklist()]),
      ],
    );
  }
}

// ---------------------------------------------------------------- comparison

class _Comparison extends ConsumerWidget {
  const _Comparison();

  String _markdown(List<Json> runs, Map<String, Run> byId) {
    final b = StringBuffer('| Run | Method | ${_cols.map((c) => c.$1).join(' | ')} | Runtime |\n');
    b.writeln('|${List.filled(_cols.length + 3, '---').join('|')}|');
    for (final r in runs) {
      final m = asJson(r['metrics']);
      final run = byId[r['run_id']];
      b.writeln(
        '| ${runLabel(run?.seq)} | ${methodName(r['method'] as String?)} | '
        '${_cols.map((c) => c.$3(m[c.$2] as num?)).join(' | ')} | '
        '${run?.runtime == null ? '—' : fmtSeconds(run!.runtime!.inMilliseconds / 1000)} |',
      );
    }
    return b.toString();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cmp = ref.watch(_comparisonProvider);
    final runs = ref.watch(runsProvider).value ?? const <Run>[];
    final byId = {for (final r in runs) r.id: r};
    final completed = runs.where((r) => r.status == 'completed').toList();
    final ids = ref.watch(_comparedIdsProvider);
    return Panel(
      title: 'Experiment comparison',
      subtitle: 'Best value per column in green. Tick runs on the chips (or on Experiments) to change the set.',
      trailing: cmp.value == null
          ? null
          : Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: _markdown(asJsonList(cmp.value!['runs']), byId)));
                    if (context.mounted) showSnack(context, 'Comparison table copied as Markdown');
                  },
                  icon: const Icon(Icons.content_copy_rounded, size: 16),
                  label: const Text('Copy as Markdown'),
                ),
                OutlinedButton.icon(
                  onPressed: () async {
                    final ok = await launchUrl(ref.read(apiProvider).compareFiguresUri(ids));
                    if (!ok && context.mounted) showSnack(context, 'Could not open the download', error: true);
                  },
                  icon: const Icon(Icons.insert_chart_outlined, size: 16),
                  label: const Text('Comparison figures'),
                ),
              ],
            ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final r in completed.take(24))
                FilterChip(
                  label: Text('${runLabel(r.seq)} · ${methodName(r.method)}'),
                  selected: ids.contains(r.id),
                  selectedColor: AppColors.navActive,
                  checkmarkColor: AppColors.purple,
                  onSelected: (_) {
                    final sel = ref.read(compareSelectionProvider.notifier);
                    sel.set(ids.toSet());
                    sel.toggle(r.id);
                  },
                ),
            ],
          ),
          const SizedBox(height: 16),
          if (completed.length < 2)
            const EmptyState('Complete at least two runs to compare them.', icon: Icons.compare_arrows_rounded)
          else
            AsyncView(
              value: cmp,
              builder: (c) {
                if (c == null) return const EmptyState('Pick at least two runs.');
                final rows = asJsonList(c['runs']);
                final best = <String, num>{};
                for (final col in _cols) {
                  final vals = rows.map((r) => asJson(r['metrics'])[col.$2]).whereType<num>();
                  if (vals.isNotEmpty) {
                    best[col.$2] = col.$4 ? vals.reduce((a, b) => a > b ? a : b) : vals.reduce((a, b) => a < b ? a : b);
                  }
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _FairnessBanner(c),
                    const SizedBox(height: 12),
                    if (asJsonList(c['aggregates']).any((a) => (a['n'] as int) > 1)) ...[
                      _Aggregates(asJsonList(c['aggregates'])),
                      const SizedBox(height: 18),
                      Text('INDIVIDUAL RUNS', style: TextStyles.label),
                      const SizedBox(height: 8),
                    ],
                    SentinelTable(
                      columns: [
                        const TableCol('Run'),
                        const TableCol('Method', flex: 2),
                        for (final col in _cols) TableCol(col.$1),
                        const TableCol('Runtime'),
                      ],
                      onTap: (i) => ref.read(selectedRunIdProvider.notifier).select(rows[i]['run_id'] as String),
                      rows: [
                        for (final r in rows)
                          [
                            Text(runLabel(byId[r['run_id']]?.seq), style: const TextStyle(fontWeight: FontWeight.w700)),
                            Text(methodName(r['method'] as String?)),
                            for (final col in _cols)
                              Builder(
                                builder: (_) {
                                  final v = asJson(r['metrics'])[col.$2] as num?;
                                  final isBest = v != null && v == best[col.$2] && rows.length > 1;
                                  return Text(
                                    col.$3(v),
                                    style: TextStyle(
                                      color: isBest ? AppColors.green : AppColors.text,
                                      fontWeight: isBest ? FontWeight.w800 : FontWeight.w400,
                                    ),
                                  );
                                },
                              ),
                            Text(() {
                              final rt = byId[r['run_id']]?.runtime;
                              return rt == null ? '—' : fmtSeconds(rt.inMilliseconds / 1000);
                            }()),
                          ],
                      ],
                    ),
                  ],
                );
              },
            ),
        ],
      ),
    );
  }
}

class _FairnessBanner extends StatelessWidget {
  const _FairnessBanner(this.c);
  final Json c;

  @override
  Widget build(BuildContext context) {
    final fair = c['fair'] == true;
    final diffs = asJson(c['differences']).keys.toList();
    final mixed = c['mixed_data_origin'] == true;
    final color = fair && !mixed ? AppColors.green : AppColors.orange;
    final text = [
      if (fair) 'Fair comparison: same dataset hash, split, seed, model, open-world, drift and label policy.',
      if (!fair) 'Not directly comparable — these settings differ: ${diffs.join(', ')}.',
      if (mixed) 'DEMO and real-data runs are mixed; never report them together.',
    ].join(' ');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(fair && !mixed ? Icons.verified_outlined : Icons.warning_amber_rounded, color: color, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text, style: TextStyle(color: color, fontSize: 12.5)),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- exports

class _Exports extends ConsumerWidget {
  const _Exports();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final run = ref.watch(currentRunProvider);
    final api = ref.watch(apiProvider);
    Future<void> open(String format, {String? kind}) async {
      if (run == null) return;
      final ok = await launchUrl(api.exportUri(run.id, format, kind: kind));
      ref.invalidate(reportStatsProvider);
      if (!ok && context.mounted) showSnack(context, 'Could not open the download', error: true);
    }

    final items = [
      (
        'Paper-ready summary',
        'Metrics, windows, events, definitions and provenance (JSON)',
        Icons.summarize_outlined,
        () => open('json'),
      ),
      (
        'Prediction log',
        'Flow-level outputs with run ID and dataset hash on every row (CSV)',
        Icons.table_rows_outlined,
        () => open('csv', kind: 'predictions'),
      ),
      (
        'Per-window metrics',
        'One row per replay window incl. drift scores (CSV)',
        Icons.stacked_line_chart,
        () => open('csv', kind: 'windows'),
      ),
      (
        'Experiment manifest',
        'Config, seed, provenance, all CSVs and the run log (ZIP)',
        Icons.inventory_2_outlined,
        () => open('zip'),
      ),
    ];
    return Panel(
      title: 'Export report',
      subtitle: run == null ? 'No run selected' : 'For ${runLabel(run.seq)} · ${run.name}',
      child: Column(
        children: [
          for (final (title, sub, icon, onTap) in items) _ExportRow(title, sub, icon, run == null ? null : onTap),
          _ExportRow(
            'Figure bundle',
            'Paper-ready plots as PNG + PDF, each footed with run ID and config hash (ZIP)',
            Icons.image_outlined,
            run == null ? null : () => open('figures'),
          ),
          if (run?.isDemo == true)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'DEMO run: exported files are prefixed DEMO_ and every CSV row is marked DEMO.',
                style: TextStyle(color: AppColors.orange, fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

class _ExportRow extends StatelessWidget {
  const _ExportRow(this.title, this.subtitle, this.icon, this.onTap);
  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: AppColors.isGlass ? const Color(0x40FFFFFF) : AppColors.panelRaised,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
    ),
    child: Row(
      children: [
        Icon(icon, size: 20, color: AppColors.textSecondary),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5)),
              const SizedBox(height: 2),
              Text(subtitle, style: TextStyles.secondary),
            ],
          ),
        ),
        const SizedBox(width: 12),
        FilledButton.icon(
          onPressed: onTap,
          icon: Icon(onTap == null ? Icons.schedule : Icons.download_rounded, size: 16),
          label: Text(onTap == null ? 'Planned' : 'Download'),
        ),
      ],
    ),
  );
}

// ---------------------------------------------------------------- reproducibility

class _Checklist extends ConsumerWidget {
  const _Checklist();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final m = ref.watch(metricsProvider).value;
    final run = ref.watch(currentRunProvider);
    final p = m?.provenance ?? const <String, dynamic>{};
    final integ = asJson(p['integrity']);
    final split = asJson(p['split']);
    final libs = asJson(p['libraries']).values.whereType<String>().length;
    final sha = p['dataset_sha256'] as String?;
    final checks = <(String, bool?, String)>[
      ('Dataset version / hash', sha == null ? null : true, sha == null ? 'not recorded' : '${sha.substring(0, 12)}…'),
      (
        'Chronological split',
        integ['chronological_split'] as bool?,
        integ.isEmpty ? '—' : 'train ends before stream starts',
      ),
      ('Random seed', p['seed'] == null ? null : true, p['seed'] == null ? '—' : 'seed ${p['seed']}'),
      (
        'Preprocessing fit scope',
        integ['preprocessor_fitted_rows'] == null ? null : integ['preprocessor_fitted_rows'] == split['train_rows'],
        integ['preprocessor_fitted_rows'] == null
            ? '—'
            : 'fit on ${fmtInt(integ['preprocessor_fitted_rows'] as num)} training rows only',
      ),
      (
        'Config hash',
        p['config_hash'] == null ? null : true,
        p['config_hash'] == null ? '—' : '${(p['config_hash'] as String).substring(0, 12)}…',
      ),
      ('Package versions', libs == 0 ? null : true, '$libs libraries recorded'),
      ('Label access', integ['adaptation_label_access'] == null ? null : true, 'label oracle (delay + budget)'),
    ];
    return Panel(
      title: 'Reproducibility checklist',
      subtitle: run == null ? null : 'For ${runLabel(run.seq)}',
      child: run == null || run.status != 'completed'
          ? const EmptyState('Select a completed run.', icon: Icons.fact_check_outlined)
          : Column(
              children: [
                for (final (label, ok, detail) in checks)
                  KeyValueRow(
                    label,
                    '',
                    labelWidth: 190,
                    trailing: Row(
                      children: [
                        switch (ok) {
                          true => Pill('Verified', color: AppColors.green, icon: Icons.check_rounded),
                          false => Pill('Check', color: AppColors.orange, icon: Icons.priority_high_rounded),
                          null => Pill('Missing', color: AppColors.red, icon: Icons.close_rounded),
                        },
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(detail, overflow: TextOverflow.ellipsis, style: TextStyles.secondary),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }
}

/// Mean ± std per method over seeds (multi-seed batches).
class _Aggregates extends StatelessWidget {
  const _Aggregates(this.groups);
  final List<Json> groups;

  @override
  Widget build(BuildContext context) {
    String cell(Json g, (String, String, String Function(num?), bool) col) {
      final m = asJson(asJson(g['metrics'])[col.$2]);
      if (m.isEmpty) return '—';
      final std = (m['std'] as num?) ?? 0;
      return std == 0 ? col.$3(m['mean'] as num?) : '${col.$3(m['mean'] as num?)} ± ${col.$3(std)}';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('MEAN ± STD OVER SEEDS', style: TextStyles.label),
        const SizedBox(height: 8),
        SentinelTable(
          columns: [
            const TableCol('Method', flex: 2),
            const TableCol('Seeds'),
            for (final col in _cols) TableCol(col.$1),
          ],
          rows: [
            for (final g in groups)
              [
                Text(methodName(g['method'] as String?), style: const TextStyle(fontWeight: FontWeight.w700)),
                Text('n=${g['n']}  (${(g['seeds'] as List).join(', ')})', overflow: TextOverflow.ellipsis),
                for (final col in _cols) Text(cell(g, col), overflow: TextOverflow.ellipsis),
              ],
          ],
        ),
      ],
    );
  }
}
