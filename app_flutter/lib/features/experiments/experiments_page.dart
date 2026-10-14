import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/format.dart';
import '../../core/glass_menu.dart';
import '../../core/state.dart';
import '../../core/status.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../core/dialogs.dart';

/// Runs ticked for comparison; consumed by the Reports page.
class CompareSelection extends Notifier<Set<String>> {
  @override
  Set<String> build() => {};

  void toggle(String id) => state = state.contains(id) ? ({...state}..remove(id)) : {...state, id};
  void set(Set<String> ids) => state = ids;
}

final compareSelectionProvider = NotifierProvider<CompareSelection, Set<String>>(CompareSelection.new);

/// Page of the runs table (25 runs per page).
class _RunsPage extends Notifier<int> {
  @override
  int build() => 1;

  void set(int page) => state = page;
}

final _runsPageProvider = NotifierProvider<_RunsPage, int>(_RunsPage.new);

final activePolicyProvider = FutureProvider<Json>((ref) => ref.watch(apiProvider).activePolicy());

const _modelKinds = {
  'hist_gb': 'HistGradientBoosting',
  'lightgbm': 'LightGBM',
  'random_forest': 'Random forest',
  'logreg': 'Logistic regression',
  'mlp': 'Neural net (PyTorch MLP)',
};

/// "42" or "42, 43, 44" -> [42, 43, 44]; null when anything is not a whole number.
List<int>? parseSeeds(String text) {
  final parts = text.split(RegExp(r'[,\s]+')).where((p) => p.isNotEmpty).toList();
  if (parts.isEmpty) return null;
  final seeds = parts.map(int.tryParse).toList();
  if (seeds.any((s) => s == null)) return null;
  return seeds.cast<int>().toSet().toList();
}

class ExperimentsPage extends ConsumerWidget {
  const ExperimentsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(runsProvider);
    final list = runs.value ?? const <Run>[];
    int n(bool Function(Run) f) => list.where(f).length;
    return PageScaffold(
      title: 'Experiments',
      subtitle: 'Create reproducible runs, compare baselines, and track experiment progress',
      children: [
        StatRow(
          cards: [
            StatCard(label: 'Total runs', value: fmtInt(list.length), caption: 'Saved locally'),
            StatCard(
              label: 'Completed',
              value: fmtInt(n((r) => r.status == 'completed')),
              caption: 'Ready to compare',
              color: AppColors.green,
            ),
            StatCard(
              label: 'Running',
              value: fmtInt(n((r) => r.isActive)),
              caption: n((r) => r.status == 'queued') > 0
                  ? '${n((r) => r.status == 'queued')} more queued'
                  : 'Replay in progress',
              color: AppColors.orange,
            ),
            StatCard(
              label: 'Failed',
              value: fmtInt(n((r) => r.status == 'failed')),
              caption: 'See logs',
              color: AppColors.red,
            ),
          ],
        ),
        const _NewExperiment(),
        if (runs.hasError && !runs.hasValue) Panel(child: ErrorNote(runs.error!)) else _RunsTable(runs: list),
      ],
    );
  }
}

// ---------------------------------------------------------------- new experiment form

class _NewExperiment extends ConsumerStatefulWidget {
  const _NewExperiment();

  @override
  ConsumerState<_NewExperiment> createState() => _NewExperimentState();
}

class _NewExperimentState extends ConsumerState<_NewExperiment> {
  final _name = TextEditingController();
  final _seed = TextEditingController(text: '42');
  final _maxRows = TextEditingController();
  String? _dataset;
  String _method = 'nova';
  String _model = 'hist_gb';
  bool _allMethods = false;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _seed.dispose();
    _maxRows.dispose();
    super.dispose();
  }

  Future<void> _submit({required bool start}) async {
    final api = ref.read(apiProvider);
    final datasets = ref.read(datasetsProvider).value ?? const <Dataset>[];
    final ds = datasets.where((d) => d.id == _dataset).firstOrNull;
    final seeds = parseSeeds(_seed.text);
    if (ds == null) return showSnack(context, 'Choose a dataset first', error: true);
    if (seeds == null) return showSnack(context, 'Seeds must be whole numbers, e.g. 42 or 42, 43, 44', error: true);
    if (seeds.length > 20) return showSnack(context, 'At most 20 seeds per batch', error: true);
    final maxRowsText = _maxRows.text.replaceAll(RegExp(r'[,_\s]'), '');
    final maxRows = maxRowsText.isEmpty ? null : int.tryParse(maxRowsText);
    if (maxRowsText.isNotEmpty && (maxRows == null || maxRows < 100)) {
      return showSnack(context, 'Max rows must be a whole number of at least 100 (or empty for all rows)', error: true);
    }
    setState(() => _busy = true);
    try {
      // Validation is mandatory before a run (PRD); do it here so the user sees problems up front.
      if (start && !ds.isValidated) {
        final report = await api.withTimeout(const Duration(minutes: 15)).validateDataset(ds.id);
        ref.invalidate(datasetsProvider);
        if (report['valid'] != true) {
          if (mounted) await _showValidation(report);
          return;
        }
      }
      final policy = await ref.read(activePolicyProvider.future);
      final config = {
        'dataset_id': ds.id,
        'seed': seeds.first,
        'model': {'kind': _model},
        'adaptation': {'method': _method},
        'policy_version': policy['version'],
        if (maxRows != null) 'split': {'max_rows': maxRows},
      };
      if (seeds.length > 1 || _allMethods) {
        // Multi-seed / all-methods batch: one run per (method, seed); extra runs wait in the queue.
        final name = _name.text.trim().isEmpty ? ds.name : _name.text.trim();
        final res = await api.createBatch({
          'base': {...config, 'name': name},
          'methods': _allMethods ? methodNames.keys.toList() : null,
          'seeds': seeds,
          'start': start,
        });
        final runs = asJsonList(res['runs']).map(Run.new).toList();
        ref.read(compareSelectionProvider.notifier).set({for (final r in runs) r.id});
        ref.read(selectedRunIdProvider.notifier).select(runs.first.id);
        ref.read(refreshTickProvider.notifier).bump();
        _name.clear();
        if (mounted) {
          showSnack(
            context,
            '${runs.length} runs ${start ? 'started (extra runs queued)' : 'created'} · batch '
            '${runLabel(runs.first.seq)}–${runLabel(runs.last.seq)}',
          );
        }
        return;
      }
      final name = _name.text.trim().isEmpty ? '${methodName(_method)} · ${ds.name}' : _name.text.trim();
      var run = await api.createRun({...config, 'name': name});
      if (start) run = await api.startRun(run.id);
      ref.read(selectedRunIdProvider.notifier).select(run.id);
      ref.read(refreshTickProvider.notifier).bump();
      _name.clear();
      if (mounted) showSnack(context, '${runLabel(run.seq)} ${start ? 'started' : 'created'} · ${run.name}');
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _validateOnly() async {
    if (_dataset == null) return;
    setState(() => _busy = true);
    try {
      final report = await ref.read(apiProvider).withTimeout(const Duration(minutes: 15)).validateDataset(_dataset!);
      ref.invalidate(datasetsProvider);
      if (mounted) await _showValidation(report);
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _showValidation(Json r) => showFrostedDialog<void>(
    context: context,
    builder: (_) => _GlassDialog(
      title: 'Dataset validation · ${r['dataset_id']}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: r['valid'] == true
                ? Pill('Valid · ready to run', color: AppColors.green, icon: Icons.check_circle_outline)
                : Pill('Invalid · fix before running', color: AppColors.red, icon: Icons.error_outline),
          ),
          const SizedBox(height: 12),
          KeyValueRow('Profile', '${r['profile']}'),
          KeyValueRow('Rows', fmtInt(r['rows'] as num?)),
          KeyValueRow('Features', fmtInt((r['feature_columns'] as List?)?.length)),
          KeyValueRow(
            'Time range',
            '${fmtTime(r['timestamp_min'], withDate: true)} → ${fmtTime(r['timestamp_max'], withDate: true)}',
          ),
          KeyValueRow(
            'Labels',
            (asJson(r['label_distribution']).entries.map((e) => '${e.key} ${fmtInt(e.value as num)}')).join(' · '),
          ),
          KeyValueRow('SHA-256', '${r['sha256']}'.substring(0, 16)),
          for (final e in (r['errors'] as List? ?? const []))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('✕ $e', style: TextStyle(color: AppColors.red, fontSize: 13)),
            ),
          for (final w in (r['warnings'] as List? ?? const []))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('! $w', style: TextStyle(color: AppColors.orange, fontSize: 13)),
            ),
        ],
      ),
    ),
  );

  Future<void> _import() async {
    final req = await showFrostedDialog<(String, String, String?)>(
      context: context,
      builder: (_) => const _ImportDialog(),
    );
    if (req == null) return;
    setState(() => _busy = true);
    final slow = ref.read(apiProvider).withTimeout(const Duration(minutes: 15));
    try {
      if (mounted) showSnack(context, 'Importing ${req.$2}… large archives take a few minutes');
      final d = await slow.importDataset(req.$1, req.$2, profile: req.$3);
      ref.invalidate(datasetsProvider);
      setState(() => _dataset = d['id'] as String);
      if (mounted) showSnack(context, 'Imported ${(d['files'] as List).length} CSV file(s). Validating every row…');
      final report = await slow.validateDataset(d['id'] as String);
      ref.invalidate(datasetsProvider);
      if (mounted) await _showValidation(report);
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createDemo() async {
    setState(() => _busy = true);
    try {
      final d = await ref.read(apiProvider).createDemo();
      ref.invalidate(datasetsProvider);
      setState(() => _dataset = d['id'] as String);
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(String label, Widget child, {double width = 240}) => SizedBox(
    width: width,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
        const SizedBox(height: 6),
        child,
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final datasets = ref.watch(datasetsProvider);
    final policy = ref.watch(activePolicyProvider).value;
    final list = datasets.value ?? const <Dataset>[];
    _dataset ??= list.firstOrNull?.id;
    final ds = list.where((d) => d.id == _dataset).firstOrNull;
    return Panel(
      title: 'New experiment',
      subtitle: 'Chronological replay · rules from the active policy (Rules page)',
      trailing: policy == null
          ? null
          : Pill(
              'POL-${(policy['version'] as int).toString().padLeft(3, '0')} · window ${asJson(policy['body'])['window_size']}',
              color: AppColors.cyan,
              icon: Icons.flag_outlined,
            ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (datasets.hasError) ErrorNote(datasets.error!),
          if (datasets.hasValue && list.isEmpty)
            EmptyState(
              'No datasets yet. Import a real IDS dataset (e.g. CIC-IDS2017 GeneratedLabelledFlows.zip), '
              'or generate the synthetic DEMO dataset.',
              icon: Icons.dataset_outlined,
              action: Wrap(
                spacing: 10,
                children: [
                  FilledButton.icon(
                    onPressed: _busy ? null : _import,
                    icon: const Icon(Icons.file_download_outlined),
                    label: const Text('Import dataset…'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _createDemo,
                    icon: const Icon(Icons.science_outlined),
                    label: const Text('Generate DEMO dataset'),
                  ),
                ],
              ),
            )
          else
            Wrap(
              spacing: 18,
              runSpacing: 16,
              crossAxisAlignment: WrapCrossAlignment.end,
              children: [
                _field(
                  'Dataset',
                  GlassSelect<String?>(
                    label: '',
                    value: _dataset,
                    width: 260,
                    options: {
                      for (final d in list)
                        d.id:
                            '${d.isDemo && !d.name.toUpperCase().startsWith('DEMO') ? 'DEMO · ' : ''}${d.name}'
                            '${d.isValidated ? '  ✓' : ''}',
                    },
                    onChanged: (v) => setState(() => _dataset = v),
                  ),
                  width: 260,
                ),
                _field(
                  'Method',
                  _allMethods
                      ? _ReadOnlyBox('All ${methodNames.length} methods')
                      : GlassSelect<String>(
                          label: '',
                          value: _method,
                          width: 240,
                          options: methodNames,
                          onChanged: (v) => setState(() => _method = v),
                        ),
                ),
                _field(
                  'Model',
                  GlassSelect<String>(
                    label: '',
                    value: _model,
                    width: 240,
                    options: _modelKinds,
                    onChanged: (v) => setState(() => _model = v),
                  ),
                ),
                _field('Split protocol', const _ReadOnlyBox('Chronological windows'), width: 200),
                _field(
                  'Seeds',
                  Tooltip(
                    message: 'One seed, or several separated by commas for a multi-seed batch (mean ± std in Reports)',
                    child: TextField(
                      controller: _seed,
                      style: const TextStyle(fontSize: 13),
                      decoration: const InputDecoration(hintText: '42, 43, 44'),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  width: 150,
                ),
                _field(
                  'Max rows (optional)',
                  Tooltip(
                    message:
                        'Evenly spaced sample over the whole timeline; leave empty to use every row. '
                        'For CIC-IDS2017 (2.8 M rows) 300,000–500,000 keeps memory and time reasonable.',
                    child: TextField(
                      controller: _maxRows,
                      style: const TextStyle(fontSize: 13),
                      decoration: const InputDecoration(hintText: 'all rows'),
                    ),
                  ),
                  width: 150,
                ),
                _field(
                  'Name (optional)',
                  TextField(
                    controller: _name,
                    style: const TextStyle(fontSize: 13),
                    decoration: const InputDecoration(hintText: 'e.g. CIC-2017 ablation A'),
                  ),
                  width: 260,
                ),
              ],
            ),
          const SizedBox(height: 12),
          Row(
            children: [
              SizedBox(
                height: 24,
                child: Checkbox(value: _allMethods, onChanged: (v) => setState(() => _allMethods = v ?? false)),
              ),
              const SizedBox(width: 6),
              Text('Run all methods (baseline comparison)', style: TextStyle(fontSize: 13, color: AppColors.text)),
              const SizedBox(width: 14),
              Builder(
                builder: (_) {
                  final n = (parseSeeds(_seed.text)?.length ?? 1) * (_allMethods ? methodNames.length : 1);
                  return n > 1
                      ? Text(
                          '→ $n runs, same split and policy; up to 2 run at once, the rest queue',
                          style: TextStyles.secondary,
                        )
                      : const SizedBox();
                },
              ),
            ],
          ),
          const SizedBox(height: 14),
          // Wraps onto two lines on narrow windows instead of overflowing.
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 16,
            runSpacing: 12,
            children: [
              if (ds != null)
                ds.isValidated
                    ? Pill('Dataset validated', color: AppColors.green, icon: Icons.verified_outlined)
                    : Pill(
                        'Not validated yet — validated automatically on start',
                        color: AppColors.orange,
                        icon: Icons.info_outline,
                      )
              else
                const SizedBox(),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  if (_busy) const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _import,
                    icon: const Icon(Icons.file_download_outlined, size: 16),
                    label: const Text('Import dataset…'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy || ds == null ? null : _validateOnly,
                    icon: const Icon(Icons.fact_check_outlined, size: 16),
                    label: const Text('Validate dataset'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy || ds == null ? null : () => _submit(start: false),
                    icon: const Icon(Icons.add, size: 16),
                    label: const Text('Create'),
                  ),
                  FilledButton.icon(
                    onPressed: _busy || ds == null ? null : () => _submit(start: true),
                    icon: const Icon(Icons.play_arrow_rounded, size: 18),
                    label: const Text('Create & start'),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ReadOnlyBox extends StatelessWidget {
  const _ReadOnlyBox(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
    decoration: BoxDecoration(
      color: AppColors.isGlass ? const Color(0x40FFFFFF) : AppColors.panelRaised.withValues(alpha: 0.5),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
    ),
    child: Text(text, style: TextStyle(color: AppColors.textSecondary, fontSize: 12.5)),
  );
}

// ---------------------------------------------------------------- runs table

class _RunsTable extends ConsumerWidget {
  const _RunsTable({required this.runs});
  final List<Run> runs;

  Future<void> _control(BuildContext context, WidgetRef ref, Run run, String action) async {
    try {
      if (action == 'start') {
        await ref.read(apiProvider).startRun(run.id);
      } else {
        await ref.read(apiProvider).control(run.id, action);
      }
      ref.read(refreshTickProvider.notifier).bump();
    } catch (e) {
      if (context.mounted) showSnack(context, '$e', error: true);
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref, Run run) async {
    final ok = await showConfirmDialog(
      context,
      title: 'Delete ${runLabel(run.seq)}?',
      message:
          'Removes its predictions, events, alerts, model history and the files in experiments/results/${run.id}. '
          'This cannot be undone.',
      confirmLabel: 'Delete',
      destructive: true,
    );
    if (!ok) return;
    try {
      await ref.read(apiProvider).deleteRun(run.id);
      final sel = ref.read(compareSelectionProvider);
      if (sel.contains(run.id)) ref.read(compareSelectionProvider.notifier).set({...sel}..remove(run.id));
      ref.read(refreshTickProvider.notifier).bump();
      if (context.mounted) showSnack(context, '${runLabel(run.seq)} deleted');
    } catch (e) {
      if (context.mounted) showSnack(context, '$e', error: true);
    }
  }

  Future<void> _logs(BuildContext context, WidgetRef ref, Run run) async {
    try {
      final lines = await ref.read(apiProvider).logs(run.id, tail: 400);
      if (!context.mounted) return;
      await showFrostedDialog<void>(
        context: context,
        builder: (_) => _GlassDialog(
          title: 'Logs · ${runLabel(run.seq)} · ${run.name}',
          child: SizedBox(
            height: 460,
            child: SingleChildScrollView(
              primary: false,
              reverse: true,
              child: SelectableText(
                lines.isEmpty ? 'No log lines yet.' : lines.join('\n'),
                style: TextStyle(fontFamily: 'monospace', fontSize: 12, color: AppColors.text, height: 1.5),
              ),
            ),
          ),
        ),
      );
    } catch (e) {
      if (context.mounted) showSnack(context, '$e', error: true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = ref.watch(currentRunIdProvider);
    final compare = ref.watch(compareSelectionProvider);
    final utc = ref.watch(settingsProvider).utc;
    Widget act(IconData icon, String tip, VoidCallback onTap, {Color? color}) => IconButton(
      tooltip: tip,
      visualDensity: VisualDensity.compact,
      iconSize: 18,
      onPressed: onTap,
      icon: Icon(icon, color: color ?? AppColors.textSecondary),
    );
    const perPage = 25;
    final pages = runs.isEmpty ? 1 : (runs.length + perPage - 1) ~/ perPage;
    final page = ref.watch(_runsPageProvider).clamp(1, pages);
    final shown = runs.skip((page - 1) * perPage).take(perPage).toList();
    return Panel(
      title: 'Experiment runs',
      subtitle: 'Click a row to make it the run shown on every page · tick runs to compare them in Reports',
      trailing: FilledButton.icon(
        onPressed: compare.length < 2 ? null : () => ref.read(navProvider.notifier).go(AppPage.reports),
        icon: const Icon(Icons.compare_arrows_rounded, size: 18),
        label: Text('Compare selected (${compare.length})'),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SentinelTable(
            rowHeight: 52,
            columns: const [
              TableCol('', width: 44),
              TableCol('Run ID', flex: 2),
              TableCol('Method', flex: 2),
              TableCol('Dataset', flex: 2),
              TableCol('Status', flex: 2),
              TableCol('Macro F1'),
              TableCol('Started'),
              TableCol('Actions', flex: 2),
            ],
            emptyText: 'No runs yet — create one above.',
            selected: shown.indexWhere((r) => r.id == current),
            onTap: (i) => ref.read(selectedRunIdProvider.notifier).select(shown[i].id),
            rows: [
              for (final r in shown)
                [
                  Checkbox(
                    value: compare.contains(r.id),
                    onChanged: r.status == 'completed'
                        ? (_) => ref.read(compareSelectionProvider.notifier).toggle(r.id)
                        : null,
                  ),
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          runLabel(r.seq),
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                      if (r.groupId != null) ...[
                        const SizedBox(width: 6),
                        Tooltip(
                          message: 'Batch ${r.groupId} · seed ${r.seed}',
                          child: Icon(Icons.layers_outlined, size: 14, color: AppColors.textSecondary),
                        ),
                      ],
                      if (r.isDemo) ...[const SizedBox(width: 8), const DemoBadge(compact: true)],
                    ],
                  ),
                  Text(methodName(r.method), overflow: TextOverflow.ellipsis),
                  Text(r.datasetId, overflow: TextOverflow.ellipsis),
                  r.isActive
                      ? Row(
                          children: [
                            runStatusLabel(r.status),
                            const SizedBox(width: 10),
                            Expanded(
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(4),
                                child: LinearProgressIndicator(
                                  value: r.totalWindows == 0 ? null : r.window / r.totalWindows,
                                  minHeight: 6,
                                  backgroundColor: AppColors.track,
                                  valueColor: AlwaysStoppedAnimation(runStatusColor(r.status)),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text('${r.window}/${r.totalWindows}', style: TextStyles.secondary),
                          ],
                        )
                      : Tooltip(message: r.error ?? '', child: runStatusLabel(r.status)),
                  Text(fmtNum(r.overall['macro_f1'] as num?)),
                  Text(fmtRelativeDay(r.startedAt ?? r.createdAt, utc: utc)),
                  Row(
                    children: [
                      if (r.status == 'created' || r.status == 'failed' || r.status == 'cancelled')
                        act(
                          Icons.play_arrow_rounded,
                          'Start',
                          () => _control(context, ref, r, 'start'),
                          color: AppColors.green,
                        ),
                      if (r.status == 'running')
                        act(Icons.pause_rounded, 'Pause', () => _control(context, ref, r, 'pause')),
                      if (r.status == 'paused') ...[
                        act(
                          Icons.play_arrow_rounded,
                          'Resume',
                          () => _control(context, ref, r, 'resume'),
                          color: AppColors.green,
                        ),
                        act(Icons.skip_next_rounded, 'Step one window', () => _control(context, ref, r, 'step')),
                      ],
                      if (r.isBusy || r.status == 'created')
                        act(
                          Icons.stop_rounded,
                          'Cancel',
                          () => _control(context, ref, r, 'cancel'),
                          color: AppColors.red,
                        ),
                      act(Icons.article_outlined, 'Logs', () => _logs(context, ref, r)),
                      if (!r.isBusy) act(Icons.delete_outline, 'Delete run', () => _delete(context, ref, r)),
                    ],
                  ),
                ],
            ],
          ),
          if (pages > 1)
            Pager(page: page, pages: pages, total: runs.length, onPage: ref.read(_runsPageProvider.notifier).set),
        ],
      ),
    );
  }
}

/// Frosted-glass dialog shell shared by this page's dialogs.
class _GlassDialog extends StatelessWidget {
  const _GlassDialog({required this.title, required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    elevation: 0,
    insetPadding: const EdgeInsets.all(40),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 820),
      child: Glass(
        radius: 20,
        blur: 36,
        color: AppColors.isGlass ? const Color(0xC7FFFFFF) : AppColors.panel,
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(title, style: TextStyles.panelTitle, overflow: TextOverflow.ellipsis),
                ),
                IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close)),
              ],
            ),
            const SizedBox(height: 12),
            Flexible(child: SingleChildScrollView(primary: false, child: child)),
          ],
        ),
      ),
    ),
  );
}

class _ImportDialog extends StatefulWidget {
  const _ImportDialog();

  @override
  State<_ImportDialog> createState() => _ImportDialogState();
}

class _ImportDialogState extends State<_ImportDialog> {
  final _source = TextEditingController();
  final _name = TextEditingController(text: 'CIC-IDS2017');
  String? _profile;

  @override
  void dispose() {
    _source.dispose();
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _GlassDialog(
      title: 'Import dataset',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'Path of a .zip archive, a folder of CSV files, or one .csv on this PC. Only CSV files are copied into '
            'data\\\\datasets\\\\<name>; CIC day files are ordered Monday → Friday.',
            style: TextStyles.secondary,
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _source,
            autofocus: true,
            style: const TextStyle(fontSize: 13),
            decoration: const InputDecoration(
              labelText: 'Source path',
              hintText: r'C:\\Users\\you\\Downloads\\GeneratedLabelledFlows.zip',
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _name,
                  style: const TextStyle(fontSize: 13),
                  decoration: const InputDecoration(labelText: 'Dataset name'),
                ),
              ),
              const SizedBox(width: 12),
              GlassSelect<String?>(
                label: 'Profile',
                value: _profile,
                width: 230,
                options: const {
                  null: 'Auto-detect',
                  'cicids2017': 'CIC-IDS2017',
                  'cicids2018': 'CSE-CIC-IDS2018',
                  'unswnb15': 'UNSW-NB15 (raw)',
                },
                onChanged: (v) => setState(() => _profile = v),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            'CIC-IDS2017: use GeneratedLabelledFlows.zip (TrafficLabelling, has timestamps), not MachineLearningCSV.zip.',
            style: TextStyle(color: AppColors.orange, fontSize: 12),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: () {
                  final src = _source.text.trim().replaceAll('"', '');
                  final name = _name.text.trim();
                  if (src.isEmpty || name.isEmpty) return;
                  Navigator.pop(context, (src, name, _profile));
                },
                child: const Text('Import'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
