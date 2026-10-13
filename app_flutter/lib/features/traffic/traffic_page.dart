import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/charts.dart';
import '../../core/flow_detail.dart';
import '../../core/format.dart';
import '../../core/run_guard.dart';
import '../../core/shell.dart';
import '../../core/state.dart';
import '../../core/status.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../core/dialogs.dart';
import '../dashboard/dashboard_page.dart';

class FlowQuery {
  const FlowQuery({this.decision, this.window, this.review, this.page = 1});
  final String? decision;
  final int? window;
  final bool? review; // true = only UNKNOWN, false = only non-UNKNOWN
  final int page;
}

class FlowQueryNotifier extends Notifier<FlowQuery> {
  @override
  FlowQuery build() {
    ref.watch(currentRunIdProvider);
    return const FlowQuery();
  }

  void set(FlowQuery q) => state = q;
}

final flowQueryProvider = NotifierProvider<FlowQueryNotifier, FlowQuery>(FlowQueryNotifier.new);

final flowsPageProvider = FutureProvider<PageOf<NetFlow>?>((ref) {
  ref.watch(refreshTickProvider);
  final id = ref.watch(currentRunIdProvider);
  final q = ref.watch(flowQueryProvider);
  if (id == null) return Future.value(null);
  return ref.watch(apiProvider).flows(id, {
    'decision': q.decision,
    'window': q.window,
    'is_unknown': q.review,
    'page': q.page,
    'page_size': 15,
    'sort': 'flow_id',
    'desc': true,
  });
});

class TrafficPage extends ConsumerStatefulWidget {
  const TrafficPage({super.key});

  @override
  ConsumerState<TrafficPage> createState() => _TrafficPageState();
}

class _TrafficPageState extends ConsumerState<TrafficPage> {
  /// Opens a flow requested from the global search (or `?flow=`) once the current run is known.
  void _openRequestedFlow() {
    final fid = ref.read(trafficSearchProvider);
    if (fid == null || ref.read(currentRunIdProvider) == null) return;
    ref.read(trafficSearchProvider.notifier).set(null);
    _openFlow(fid);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _openRequestedFlow());
  }

  Future<void> _openFlow(int flowId) async {
    final runId = ref.read(currentRunIdProvider);
    if (runId == null) return;
    final utc = ref.read(settingsProvider).utc;
    try {
      final flow = await ref.read(apiProvider).flow(runId, flowId);
      if (!mounted) return;
      await showFrostedDialog<void>(
        context: context,
        builder: (_) => Dialog(
          insetPadding: const EdgeInsets.all(40),
          backgroundColor: Colors.transparent,
          elevation: 0,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1200),
            child: Glass(
              radius: 20,
              blur: 36,
              color: AppColors.isGlass ? const Color(0xC7FFFFFF) : AppColors.panel,
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Text('Flow FL-${flow.flowId.toString().padLeft(5, '0')}', style: TextStyles.panelTitle),
                        const Spacer(),
                        IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close)),
                      ],
                    ),
                    const SizedBox(height: 12),
                    FlowEvidence(flow: flow, utc: utc),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    } catch (e) {
      if (mounted) showSnack(context, '$e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(
      currentRunIdProvider,
      (_, _) => WidgetsBinding.instance.addPostFrameCallback((_) => _openRequestedFlow()),
    );
    ref.listen(
      trafficSearchProvider,
      (_, _) => WidgetsBinding.instance.addPostFrameCallback((_) => _openRequestedFlow()),
    );
    return RunGuard(
      title: 'Traffic Monitor',
      subtitle: 'Explore replayed network flows and feature-level model outputs',
      builder: (run) {
        final d = asJson(ref.watch(classDistributionProvider).value?['decision']);
        num sum(bool Function(String) f) =>
            d.entries.where((e) => f(e.key)).fold<num>(0, (a, e) => a + (e.value as num));
        final total = sum((_) => true);
        final benign = sum(isBenignLabel);
        final unknown = sum((k) => k == 'UNKNOWN');
        final attack = total - benign - unknown;
        String share(num n) => total == 0 ? '—' : fmtPct(n / total);
        return [
          StatRow(
            cards: [
              StatCard(label: 'Total flows', value: fmtInt(total), caption: '${runLabel(run.seq)} · replayed'),
              StatCard(label: 'Benign', value: fmtInt(benign), caption: share(benign), color: AppColors.green),
              StatCard(
                label: 'Attack predictions',
                value: fmtInt(attack),
                caption: share(attack),
                color: AppColors.red,
              ),
              StatCard(
                label: 'Unknown / review',
                value: fmtInt(unknown),
                caption: share(unknown),
                color: AppColors.orange,
              ),
            ],
          ),
          const _VolumePanel(),
          _Explorer(onOpen: _openFlow),
        ];
      },
    );
  }
}

class _VolumePanel extends ConsumerWidget {
  const _VolumePanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final m = ref.watch(metricsProvider);
    return Panel(
      title: 'Flow volume by replay window',
      trailing: Legend([('Flows', AppColors.blue), ('Unknown / review', AppColors.orange)]),
      child: AsyncView(
        value: m,
        builder: (m) {
          final windows = m?.windows ?? const <Json>[];
          final (_, _, u) = decisionSeries(windows);
          return TrendChart(
            height: 120,
            minY: 0,
            yFormat: (v) => v.toStringAsFixed(0),
            series: [
              Series('Flows', AppColors.blue, [for (final w in windows) (w['n_flows'] as num).toDouble()]),
              Series('Unknown / review', AppColors.orange, u),
            ],
          );
        },
      ),
    );
  }
}

class _Explorer extends ConsumerWidget {
  const _Explorer({required this.onOpen});
  final void Function(int flowId) onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final q = ref.watch(flowQueryProvider);
    final set = ref.read(flowQueryProvider.notifier).set;
    final page = ref.watch(flowsPageProvider);
    final run = ref.watch(currentRunProvider);
    final utc = ref.watch(settingsProvider).utc;
    final classes = asJson(ref.watch(classDistributionProvider).value?['decision']).keys.toList()..sort();
    return Panel(
      title: 'Flow explorer',
      subtitle: 'Click a row for features and class probabilities',
      trailing: Wrap(
        spacing: 12,
        children: [
          DropdownFilter<String?>(
            label: 'Prediction',
            value: q.decision,
            options: {null: 'All', for (final c in classes) c: decisionText(c)},
            onChanged: (v) => set(FlowQuery(decision: v, window: q.window, review: q.review)),
          ),
          DropdownFilter<int?>(
            label: 'Window',
            value: q.window,
            options: {null: 'All', for (var i = 0; i < (run?.totalWindows ?? 0); i++) i: 'W$i'},
            onChanged: (v) => set(FlowQuery(decision: q.decision, window: v, review: q.review)),
            width: 120,
          ),
          DropdownFilter<bool?>(
            label: 'Review',
            value: q.review,
            options: const {null: 'Any', true: 'Needs review', false: 'Decided'},
            onChanged: (v) => set(FlowQuery(decision: q.decision, window: q.window, review: v)),
            width: 150,
          ),
        ],
      ),
      child: AsyncView(
        value: page,
        builder: (p) {
          final items = p?.items ?? const <NetFlow>[];
          return Column(
            children: [
              SentinelTable(
                columns: const [
                  TableCol('Timestamp'),
                  TableCol('Flow ID'),
                  TableCol('Source', flex: 2),
                  TableCol('Destination', flex: 2),
                  TableCol('Protocol'),
                  TableCol('Prediction', flex: 2),
                  TableCol('Score'),
                  TableCol('Review'),
                ],
                emptyText: 'No flows match these filters',
                onTap: (i) => onOpen(items[i].flowId),
                rows: [
                  for (final f in items)
                    [
                      Text(fmtTime(f.timestamp, utc: utc)),
                      Text('FL-${f.flowId.toString().padLeft(5, '0')}'),
                      Text(f.src ?? '—', overflow: TextOverflow.ellipsis),
                      Text(f.dst ?? '—', overflow: TextOverflow.ellipsis),
                      Text(f.protocol ?? '—'),
                      decisionLabel(f.decision),
                      Text(fmtNum(f.confidence, 4)),
                      reviewLabel(f.decision),
                    ],
                ],
              ),
              if (p != null)
                Pager(
                  page: p.page,
                  pages: p.pages,
                  total: p.total,
                  onPage: (n) => set(FlowQuery(decision: q.decision, window: q.window, review: q.review, page: n)),
                ),
            ],
          );
        },
      ),
    );
  }
}
