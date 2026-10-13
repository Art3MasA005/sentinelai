import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/dialogs.dart';
import '../../core/format.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import 'experiments_page.dart' show activePolicyProvider, compareSelectionProvider;

/// One-click test run from anywhere in the app: pick a dataset and a size, press Start, and the run is
/// created, started and shown live on the Dashboard. Everything else uses the defaults and the active policy.
Future<void> showQuickTest(BuildContext context) =>
    showFrostedDialog<void>(context: context, builder: (_) => const _QuickTestDialog());

/// Replay sizes offered in the dialog: label, flows, hint.
const _sizes = [('Fast', 40000, '≈ 2–4 min'), ('Standard', 120000, '≈ 5–10 min'), ('Paper', 400000, '≈ 15–30 min')];

class _QuickTestDialog extends ConsumerStatefulWidget {
  const _QuickTestDialog();

  @override
  ConsumerState<_QuickTestDialog> createState() => _QuickTestDialogState();
}

class _QuickTestDialogState extends ConsumerState<_QuickTestDialog> {
  String? _dataset;
  int _size = 0;
  String _method = 'nova';
  bool _compare = false;
  String? _busy;

  String? _defaultDataset(List<Dataset> list) {
    if (list.isEmpty) return null;
    return (list.where((d) => d.id == 'CIC-IDS2017').firstOrNull ?? list.first).id;
  }

  Future<void> _start() async {
    final list = ref.read(datasetsProvider).value ?? const <Dataset>[];
    final ds = list.where((d) => d.id == (_dataset ?? _defaultDataset(list))).firstOrNull;
    if (ds == null) return;
    final api = ref.read(apiProvider);
    try {
      if (!ds.isValidated) {
        setState(() => _busy = 'Validating ${ds.name} (once per dataset, may take a few minutes)…');
        final report = await api.withTimeout(const Duration(minutes: 15)).validateDataset(ds.id);
        ref.invalidate(datasetsProvider);
        if (report['valid'] != true) throw Exception('${ds.name} did not pass validation; see Experiments');
      }
      setState(() => _busy = 'Starting…');
      final policy = await ref.read(activePolicyProvider.future);
      final (label, rows, _) = _sizes[_size];
      final config = {
        'dataset_id': ds.id,
        'seed': 42,
        'model': {'kind': 'hist_gb'},
        'adaptation': {'method': _method},
        'policy_version': policy['version'],
        'split': {'max_rows': rows},
      };
      final List<Run> runs;
      if (_compare) {
        // The method and the strongest baseline on the same data and seed.
        final res = await api.createBatch({
          'base': {...config, 'name': 'Quick test · $label · ${ds.name}'},
          'methods': [_method, if (_method != 'cbrs_replay') 'cbrs_replay' else 'nova'],
          'seeds': [42],
          'start': true,
        });
        runs = asJsonList(res['runs']).map(Run.new).toList();
        ref.read(compareSelectionProvider.notifier).set({for (final r in runs) r.id});
      } else {
        final run = await api.createRun({
          ...config,
          'name': 'Quick test · ${methodName(_method)} · $label · ${ds.name}',
        });
        runs = [await api.startRun(run.id)];
      }
      ref.read(selectedRunIdProvider.notifier).select(runs.first.id);
      ref.read(refreshTickProvider.notifier).bump();
      ref.read(navProvider.notifier).go(AppPage.dashboard);
      if (!mounted) return;
      final nav = Navigator.of(context);
      final msg = runs.length == 1
          ? '${runLabel(runs.first.seq)} started · watch it live on the Dashboard'
          : '${runs.length} runs started · compare them in Reports when they finish';
      showSnack(context, msg);
      nav.pop();
    } catch (e) {
      if (mounted) {
        setState(() => _busy = null);
        showSnack(context, '$e', error: true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final datasets = ref.watch(datasetsProvider);
    final list = datasets.value ?? const <Dataset>[];
    final selected = _dataset ?? _defaultDataset(list);
    final label = TextStyle(color: AppColors.textSecondary, fontSize: 12, fontWeight: FontWeight.w600);
    return Center(
      child: Material(
        type: MaterialType.transparency,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Glass(
              radius: 20,
              blur: 36,
              color: AppColors.isGlass ? const Color(0xE6FFFFFF) : AppColors.panel,
              padding: const EdgeInsets.fromLTRB(24, 20, 16, 22),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 34,
                        height: 34,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: AppColors.blue.withValues(alpha: 0.14),
                        ),
                        child: Icon(Icons.bolt_rounded, size: 20, color: AppColors.blue),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Quick test', style: TextStyles.panelTitle),
                            Text(
                              'Replay a dataset with one click; the run appears live on the Dashboard.',
                              style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: 'Close',
                        onPressed: _busy == null ? () => Navigator.pop(context) : null,
                        icon: const Icon(Icons.close_rounded, size: 20),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Text('DATASET', style: label),
                  const SizedBox(height: 8),
                  if (datasets.isLoading && list.isEmpty)
                    const LinearProgressIndicator(minHeight: 2)
                  else if (list.isEmpty)
                    Text(
                      'No dataset yet. Import one or create the demo dataset on the Experiments page.',
                      style: TextStyle(fontSize: 13, color: AppColors.orange),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final d in list)
                          _Choice(
                            label: d.name,
                            trailing: d.isValidated ? Icons.check_rounded : null,
                            selected: d.id == selected,
                            onTap: _busy == null ? () => setState(() => _dataset = d.id) : null,
                          ),
                      ],
                    ),
                  const SizedBox(height: 18),
                  Text('SIZE', style: label),
                  const SizedBox(height: 8),
                  IntrinsicHeight(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        for (var i = 0; i < _sizes.length; i++) ...[
                          if (i > 0) const SizedBox(width: 8),
                          Expanded(
                            child: _SizeCard(
                              title: _sizes[i].$1,
                              flows: '${fmtInt(_sizes[i].$2)} flows',
                              hint: _sizes[i].$3,
                              selected: _size == i,
                              onTap: _busy == null ? () => setState(() => _size = i) : null,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  Text('METHOD', style: label),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final m in const ['nova', 'cbrs_replay', 'static'])
                        _Choice(
                          label: methodName(m),
                          selected: _method == m,
                          onTap: _busy == null ? () => setState(() => _method = m) : null,
                        ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: _busy == null ? () => setState(() => _compare = !_compare) : null,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        children: [
                          Checkbox(
                            value: _compare,
                            visualDensity: VisualDensity.compact,
                            onChanged: _busy == null ? (v) => setState(() => _compare = v ?? false) : null,
                          ),
                          Expanded(
                            child: Text(
                              _method == 'cbrs_replay'
                                  ? 'Also run ${methodName('nova')} on the same data (side-by-side comparison)'
                                  : 'Also run ${methodName('cbrs_replay')} on the same data (side-by-side comparison)',
                              style: TextStyle(fontSize: 13, color: AppColors.text),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 18),
                  Row(
                    children: [
                      Expanded(
                        child: AnimatedSwitcher(
                          duration: const Duration(milliseconds: 200),
                          child: _busy == null
                              ? Text(
                                  'Seed 42 · active policy · gradient boosting',
                                  key: const ValueKey('hint'),
                                  style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                                )
                              : Row(
                                  key: const ValueKey('busy'),
                                  children: [
                                    SizedBox(
                                      width: 14,
                                      height: 14,
                                      child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.blue),
                                    ),
                                    const SizedBox(width: 10),
                                    Flexible(
                                      child: Text(
                                        _busy!,
                                        style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
                                      ),
                                    ),
                                  ],
                                ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      FilledButton.icon(
                        onPressed: _busy == null && selected != null ? _start : null,
                        style: FilledButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        icon: const Icon(Icons.play_arrow_rounded, size: 20),
                        label: const Text('Start test', style: TextStyle(fontWeight: FontWeight.w600)),
                      ),
                    ],
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

class _Choice extends StatelessWidget {
  const _Choice({required this.label, required this.selected, required this.onTap, this.trailing});
  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final IconData? trailing;

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(20),
    onTap: onTap,
    child: AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        color: selected ? AppColors.blue.withValues(alpha: 0.14) : Colors.transparent,
        border: Border.all(color: selected ? AppColors.blue : AppColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
              color: selected ? AppColors.text : AppColors.textSecondary,
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 6), Icon(trailing, size: 14, color: AppColors.green)],
        ],
      ),
    ),
  );
}

class _SizeCard extends StatelessWidget {
  const _SizeCard({
    required this.title,
    required this.flows,
    required this.hint,
    required this.selected,
    required this.onTap,
  });
  final String title, flows, hint;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(12),
    onTap: onTap,
    child: AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: selected ? AppColors.blue.withValues(alpha: 0.12) : Colors.transparent,
        border: Border.all(color: selected ? AppColors.blue : AppColors.border, width: selected ? 1.5 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text),
          ),
          const SizedBox(height: 2),
          Text(flows, style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          const SizedBox(height: 2),
          Text(hint, style: TextStyle(fontSize: 11.5, color: AppColors.textSecondary)),
        ],
      ),
    ),
  );
}
