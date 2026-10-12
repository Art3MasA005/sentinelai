import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import 'theme.dart';

class Series {
  const Series(this.name, this.color, this.values, {this.dashed = false});
  final String name;
  final Color color;
  final List<double?> values; // one per x position; null = gap
  final bool dashed;
}

class Legend extends StatelessWidget {
  const Legend(this.items, {super.key});
  final List<(String, Color)> items;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 16,
    runSpacing: 6,
    children: [
      for (final (name, color) in items)
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
            Text(name, style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
          ],
        ),
    ],
  );
}

/// Multi-series line chart over replay windows (x = window index).
class TrendChart extends StatelessWidget {
  const TrendChart({
    super.key,
    required this.series,
    this.height = 220,
    this.minY,
    this.maxY,
    this.xLabel = 'W',
    this.yFormat,
    this.showDots = true,
    this.markers = const [],
  });

  final List<Series> series;
  final double height;
  final double? minY;
  final double? maxY;
  final String xLabel;
  final String Function(double)? yFormat;
  final bool showDots;
  final List<int> markers; // x positions to highlight (e.g. drift events)

  @override
  Widget build(BuildContext context) {
    final n = series.fold<int>(0, (m, s) => math.max(m, s.values.length));
    if (n == 0) {
      return SizedBox(
        height: height,
        child: Center(child: Text('No windows yet', style: TextStyles.secondary)),
      );
    }
    final all = [for (final s in series) ...s.values.whereType<double>()];
    final lo = minY ?? (all.isEmpty ? 0 : all.reduce(math.min));
    var hi = maxY ?? (all.isEmpty ? 1 : all.reduce(math.max));
    if (hi <= lo) hi = lo + 1;
    // Round axis steps to 1/2/2.5/5 x 10^k so labels read 0, 250, 500… instead of 0, 270, 540.
    final interval = niceStep((hi - lo) / 4);
    final top = maxY ?? lo + ((hi - lo) / interval).ceil() * interval;
    final step = math.max(1, (n / 8).ceil());
    return SizedBox(
      height: height,
      child: LineChart(
        LineChartData(
          minX: 0,
          maxX: math.max(1, n - 1).toDouble(),
          minY: lo,
          maxY: top,
          gridData: FlGridData(
            drawVerticalLine: false,
            horizontalInterval: interval,
            getDrawingHorizontalLine: (_) => FlLine(color: AppColors.border, strokeWidth: 1),
          ),
          borderData: FlBorderData(show: false),
          extraLinesData: ExtraLinesData(
            verticalLines: [
              for (final m in markers)
                VerticalLine(
                  x: m.toDouble(),
                  color: AppColors.purple.withValues(alpha: 0.35),
                  strokeWidth: 1,
                  dashArray: [3, 3],
                ),
            ],
          ),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: yFormat != null,
                reservedSize: 44,
                interval: interval,
                // Skip the padded top edge so it never collides with the last grid label.
                getTitlesWidget: (v, meta) => SideTitleWidget(
                  meta: meta,
                  child: Text(yFormat?.call(v) ?? '', style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: step.toDouble(),
                reservedSize: 24,
                getTitlesWidget: (v, meta) => v % 1 != 0
                    ? const SizedBox()
                    : SideTitleWidget(
                        meta: meta,
                        child: Text('$xLabel${v.toInt()}', style: TextStyle(color: AppColors.textMuted, fontSize: 10)),
                      ),
              ),
            ),
          ),
          lineTouchData: LineTouchData(
            touchTooltipData: LineTouchTooltipData(
              getTooltipColor: (_) => AppColors.panelRaised,
              getTooltipItems: (spots) => [
                for (final s in spots)
                  LineTooltipItem(
                    '${series[s.barIndex].name}: ${yFormat?.call(s.y) ?? s.y.toStringAsFixed(3)}',
                    TextStyle(color: series[s.barIndex].color, fontSize: 11, fontWeight: FontWeight.w600),
                  ),
              ],
            ),
          ),
          lineBarsData: [
            for (final s in series)
              LineChartBarData(
                spots: [for (final (i, v) in s.values.indexed) v == null ? FlSpot.nullSpot : FlSpot(i.toDouble(), v)],
                color: s.color,
                barWidth: 2,
                isCurved: true,
                curveSmoothness: 0.2,
                preventCurveOverShooting: true,
                dashArray: s.dashed ? [6, 4] : null,
                dotData: FlDotData(
                  show: showDots && !s.dashed && n <= 40, // reference lines (thresholds) stay clean
                  getDotPainter: (spot, _, _, _) => FlDotCirclePainter(radius: 2.6, color: s.color, strokeWidth: 0),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

double niceStep(double raw) {
  if (raw <= 0 || !raw.isFinite) return 1;
  final exp = math.pow(10, (math.log(raw) / math.ln10).floor()).toDouble();
  final f = raw / exp;
  final nice = f <= 1
      ? 1.0
      : f <= 2
      ? 2.0
      : f <= 2.5
      ? 2.5
      : f <= 5
      ? 5.0
      : 10.0;
  return nice * exp;
}

class DonutChart extends StatelessWidget {
  const DonutChart({super.key, required this.slices, required this.centerTop, required this.centerBottom});
  final List<(String, double, Color)> slices;
  final String centerTop;
  final String centerBottom;

  @override
  Widget build(BuildContext context) {
    final total = slices.fold<double>(0, (a, s) => a + s.$2);
    return Row(
      children: [
        SizedBox(
          width: 190,
          height: 190,
          child: Stack(
            alignment: Alignment.center,
            children: [
              PieChart(
                PieChartData(
                  sectionsSpace: 0,
                  centerSpaceRadius: 50,
                  startDegreeOffset: -90,
                  sections: [
                    for (final (_, v, c) in slices)
                      if (v > 0) PieChartSectionData(value: v, color: c, radius: 40, showTitle: false),
                    if (total == 0) PieChartSectionData(value: 1, color: AppColors.track, radius: 40, showTitle: false),
                  ],
                ),
              ),
              Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(centerTop, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
                  Text(centerBottom, style: TextStyles.secondary),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(width: 28),
        Expanded(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final (name, v, c) in slices)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  child: Row(
                    children: [
                      Container(
                        width: 11,
                        height: 11,
                        decoration: BoxDecoration(color: c, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 10),
                      Expanded(child: Text(name, style: const TextStyle(fontSize: 13.5))),
                      Text(total == 0 ? '—' : '${(100 * v / total).round()}%', style: TextStyles.secondary),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
