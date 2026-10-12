import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/format.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../experiments/experiments_page.dart';

/// One editable number in the policy body. `path` addresses the JSON (e.g. ['openworld', 'msp_quantile']).
class _Num {
  const _Num(this.path, this.label, this.help, {this.min, this.max, this.isInt = false, this.minExclusive = false});
  final List<String> path;
  final String label;
  final String help;
  final num? min;
  final num? max;
  final bool isInt;
  final bool minExclusive;

  String? check(num v) {
    if (isInt && v != v.roundToDouble()) return 'whole number';
    if (min != null && (minExclusive ? v <= min! : v < min!)) return minExclusive ? '> $min' : '≥ $min';
    if (max != null && v > max!) return '≤ $max';
    return null;
  }
}

const _detection = [
  _Num(
    ['openworld', 'msp_quantile'],
    'False alarm budget',
    'Share of known validation flows allowed below the per-class confidence threshold → review',
    min: 0,
    max: 0.5,
  ),
  _Num(
    ['openworld', 'distance_quantile'],
    'Unknown distance quantile',
    'Flows farther from every known class centroid than this validation quantile → UNKNOWN',
    min: 0.5,
    max: 1,
  ),
  _Num(
    ['drift', 'ks_threshold'],
    'Minimum drift score (KS)',
    'Share of features that must drift (Bonferroni KS)',
    min: 0,
    max: 1,
    minExclusive: true,
  ),
  _Num(
    ['drift', 'psi_threshold'],
    'PSI threshold',
    'Mean population stability index that counts as drift',
    min: 0,
    minExclusive: true,
  ),
  _Num(
    ['drift', 'confidence_threshold'],
    'Confidence-drop threshold',
    'Drop in mean model confidence vs reference',
    min: 0,
    minExclusive: true,
  ),
  _Num(
    ['drift', 'cooldown_windows'],
    'Drift cooldown',
    'Windows to wait before the same detector fires again',
    min: 0,
    isInt: true,
  ),
  _Num(['window_size'], 'Window size', 'Chronological flows per replay window', min: 10, isInt: true),
];

const _adaptationNums = [
  _Num(
    ['labels', 'delay_windows'],
    'Label delay',
    'Windows before ground truth reaches adaptation',
    min: 0,
    isInt: true,
  ),
  _Num(
    ['labels', 'budget'],
    'Label budget',
    'Fraction of each revealed window that gets labels',
    min: 0,
    max: 1,
    minExclusive: true,
  ),
  _Num(['adaptation', 'min_gain'], 'Minimum hold-out gain', 'Candidate must beat the current model by this much'),
  _Num(['adaptation', 'max_forgetting'], 'Maximum forgetting', 'Allowed macro-F1 drop on the reference set', min: 0),
  _Num(
    ['adaptation', 'rollback_margin'],
    'Rollback margin',
    'Previous model must win by this much to roll back',
    min: 0,
  ),
];

Object? _get(Json body, List<String> path) {
  Object? cur = body;
  for (final k in path) {
    cur = (cur as Map)[k];
  }
  return cur;
}

void _set(Json body, List<String> path, Object? value) {
  var cur = body;
  for (final k in path.sublist(0, path.length - 1)) {
    cur = cur[k] as Json;
  }
  cur[path.last] = value;
}

class RulesPage extends ConsumerStatefulWidget {
  const RulesPage({super.key});

  @override
  ConsumerState<RulesPage> createState() => _RulesPageState();
}

class _RulesPageState extends ConsumerState<RulesPage> {
  Json? _base; // active policy body as loaded
  Json? _draft;
  int _formKey = 0; // bump to reset text fields
  final _errors = <String, String>{};
  bool _saving = false;

  Json _copy(Json j) => (jsonDecode(jsonEncode(j)) as Map).cast<String, dynamic>();

  bool get _dirty => _draft != null && jsonEncode(_draft) != jsonEncode(_base);

  void _load(Json policy) {
    _base = _copy(asJson(policy['body']));
    _draft = _copy(_base!);
    _errors.clear();
    _formKey++;
  }

  Future<void> _save() async {
    if (_errors.isNotEmpty) return showSnack(context, 'Fix the highlighted values first', error: true);
    final note = await showDialog<String>(context: context, builder: (_) => const _NoteDialog());
    if (note == null || note.trim().isEmpty) return;
    setState(() => _saving = true);
    try {
      final p = await ref.read(apiProvider).savePolicy(_draft!, note.trim());
      ref.invalidate(policiesProvider);
      ref.invalidate(activePolicyProvider);
      setState(() => _load(p));
      if (mounted) showSnack(context, '${_pid(p['version'] as int)} is now active');
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  static String _pid(int v) => 'POL-${v.toString().padLeft(3, '0')}';

  Widget _numRow(_Num n) {
    final key = n.path.join('.');
    final value = _get(_draft!, n.path) as num?;
    return _FieldRow(
      label: n.label,
      help: n.help,
      child: SizedBox(
        width: 150,
        child: TextFormField(
          key: ValueKey('$_formKey-$key'),
          initialValue: value == null ? '' : (n.isInt ? '${value.toInt()}' : '$value'),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(n.isInt ? r'[0-9]' : r'[0-9.\-]'))],
          style: TextStyle(color: AppColors.cyan, fontWeight: FontWeight.w700, fontSize: 13),
          decoration: InputDecoration(
            errorText: _errors[key],
            errorStyle: const TextStyle(fontSize: 10.5),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: BorderSide(color: AppColors.isGlass ? AppColors.glassEdge : AppColors.border),
            ),
          ),
          onChanged: (text) => setState(() {
            final v = n.isInt ? int.tryParse(text) : double.tryParse(text);
            final err = v == null ? 'number' : n.check(v);
            if (err == null) {
              _errors.remove(key);
              _set(_draft!, n.path, v);
            } else {
              _errors[key] = err;
            }
          }),
        ),
      ),
    );
  }

  Widget _toggle(String label, String help, List<String> path, {bool invert = false}) {
    final raw = _get(_draft!, path);
    final on = invert ? raw != true : raw == true;
    return _FieldRow(
      label: label,
      help: help,
      child: Switch(value: on, onChanged: (v) => setState(() => _set(_draft!, path, invert ? !v : v))),
    );
  }

  @override
  Widget build(BuildContext context) {
    final active = ref.watch(activePolicyProvider);
    final history = ref.watch(policiesProvider);
    final utc = ref.watch(settingsProvider).utc;
    if (_draft == null && active.hasValue) _load(active.value!);
    final activeVersion = asInt(active.value?['version']);
    return PageScaffold(
      title: 'Rules',
      subtitle: 'Configure drift, uncertainty, and adaptation policies for offline experiments',
      children: [
        if (active.hasError && !active.hasValue) Panel(child: ErrorNote(active.error!)),
        if (_draft != null) ...[
          Glass(
            radius: AppColors.isGlass ? 14 : 10,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(
              children: [
                Pill(
                  activeVersion == null ? '—' : '${_pid(activeVersion)} active',
                  color: AppColors.green,
                  icon: Icons.flag_outlined,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    _dirty
                        ? 'Unsaved changes — saving creates a new policy version. Existing runs keep the version they used.'
                        : 'New experiments take these rules. Edit a value to start a new version.',
                    style: TextStyle(color: _dirty ? AppColors.orange : AppColors.textSecondary, fontSize: 12.5),
                  ),
                ),
                OutlinedButton(
                  onPressed: _dirty && !_saving ? () => setState(() => _load(active.value!)) : null,
                  child: const Text('Discard'),
                ),
                const SizedBox(width: 10),
                FilledButton.icon(
                  onPressed: _dirty && !_saving && _errors.isEmpty ? _save : null,
                  icon: const Icon(Icons.save_outlined, size: 16),
                  label: const Text('Save as new version'),
                ),
              ],
            ),
          ),
          ResponsiveRow(
            children: [
              Panel(
                title: 'Detection & rejection policy',
                child: Column(children: [for (final n in _detection) _numRow(n)]),
              ),
              Panel(
                title: 'Selective adaptation policy',
                subtitle: 'Applies to the guarded selective method; label rules apply to every adaptive method',
                child: Column(
                  children: [
                    _toggle('Candidate validation required', 'Off = auto-accept every candidate (ablation)', [
                      'adaptation',
                      'validation_guard',
                    ]),
                    _toggle('Reference performance check', 'Reject candidates that forget the reference set', [
                      'adaptation',
                      'reference_guard',
                    ]),
                    _toggle(
                      'Rollback on degradation',
                      'Restore the previous model if the new one is worse after deployment',
                      ['adaptation', 'rollback'],
                    ),
                    _FieldRow(
                      label: 'Trigger on novelty spikes',
                      help: 'Also adapt when the UNKNOWN rate jumps, not only on drift',
                      child: Switch(
                        value: _get(_draft!, ['adaptation', 'trigger']) == 'drift_or_novelty',
                        onChanged: (v) =>
                            setState(() => _set(_draft!, ['adaptation', 'trigger'], v ? 'drift_or_novelty' : 'drift')),
                      ),
                    ),
                    for (final n in _adaptationNums) _numRow(n),
                  ],
                ),
              ),
            ],
          ),
        ] else if (!active.hasError)
          const SizedBox(height: 160, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
        Panel(
          title: 'Policy history',
          child: AsyncView(
            value: history,
            builder: (list) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SentinelTable(
                  columns: const [
                    TableCol('Version'),
                    TableCol('Updated'),
                    TableCol('Change', flex: 3),
                    TableCol('Updated by'),
                    TableCol('Status'),
                  ],
                  emptyText: 'No policies yet',
                  rows: [
                    for (final p in list)
                      [
                        Text(_pid(p['version'] as int), style: const TextStyle(fontWeight: FontWeight.w700)),
                        Text(fmtRelativeDay(p['created_at'], utc: utc)),
                        Text(p['note'] as String? ?? '', overflow: TextOverflow.ellipsis),
                        Text(titleCase(p['updated_by'] as String? ?? '')),
                        p['status'] == 'active'
                            ? StatusLabel('Active', color: AppColors.green, icon: Icons.check_circle_outline)
                            : StatusLabel('Superseded', color: AppColors.textSecondary, icon: Icons.history),
                      ],
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  'Policies are applied only to offline experiment runs in MVP.',
                  style: TextStyle(color: AppColors.orange, fontWeight: FontWeight.w700, fontSize: 13),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _FieldRow extends StatelessWidget {
  const _FieldRow({required this.label, required this.help, required this.child});
  final String label;
  final String help;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 9),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5)),
              const SizedBox(height: 3),
              Text(help, style: TextStyles.secondary),
            ],
          ),
        ),
        const SizedBox(width: 16),
        child,
      ],
    ),
  );
}

class _NoteDialog extends StatefulWidget {
  const _NoteDialog();

  @override
  State<_NoteDialog> createState() => _NoteDialogState();
}

class _NoteDialogState extends State<_NoteDialog> {
  final _ctl = TextEditingController();

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    elevation: 0,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 520),
      child: Glass(
        radius: 20,
        blur: 36,
        color: AppColors.isGlass ? const Color(0xC7FFFFFF) : AppColors.panel,
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Save new policy version', style: TextStyles.panelTitle),
            const SizedBox(height: 6),
            Text('Describe the change so the policy history stays traceable.', style: TextStyles.secondary),
            const SizedBox(height: 16),
            TextField(
              controller: _ctl,
              autofocus: true,
              maxLength: 300,
              decoration: const InputDecoration(hintText: 'e.g. Tightened unknown threshold'),
              onSubmitted: (v) => Navigator.pop(context, v),
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
                const SizedBox(width: 8),
                FilledButton(onPressed: () => Navigator.pop(context, _ctl.text), child: const Text('Save')),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
