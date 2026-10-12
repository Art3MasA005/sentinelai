import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentinelai/core/glass_menu.dart';
import 'package:sentinelai/core/theme.dart';

Widget _app(Palette palette, Widget child) {
  AppColors.current = palette;
  return MaterialApp(
    theme: buildTheme(palette),
    home: Scaffold(
      body: Stack(
        children: [
          const Positioned.fill(child: AppBackground()),
          Align(alignment: const Alignment(0.6, -0.9), child: child),
        ],
      ),
    ),
  );
}

void main() {
  for (final palette in [Palette.light, Palette.dark]) {
    final name = palette.glass ? 'light' : 'dark';

    testWidgets('menu with long rows opens without overflow ($name)', (tester) async {
      tester.view.physicalSize = const Size(900, 600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      String? picked;
      await tester.pumpWidget(
        _app(
          palette,
          GlassMenu<String>(
            header: 'Experiment runs',
            selected: 'b',
            minWidth: 340,
            onSelected: (v) => picked = v,
            items: [
              for (final (id, label) in [('a', 'RUN-003   Selective adaptation'), ('b', 'RUN-002   Static baseline')])
                GlassMenuItem(
                  value: id,
                  icon: Icons.science_outlined,
                  label: Text(label),
                  trailing: const Text('completed   DEMO'),
                ),
            ],
            builder: (context, c) => TextButton(onPressed: c.open, child: const Text('open')),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(find.text('RUN-003   Selective adaptation'), findsOneWidget);
      expect(tester.takeException(), isNull); // a RenderFlex overflow would surface here
      await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/glass_menu_$name.png'));
      await tester.tap(find.text('RUN-003   Selective adaptation'));
      await tester.pumpAndSettle();
      expect(picked, 'a');
      expect(find.text('RUN-002   Static baseline'), findsNothing); // menu closed
    });
  }

  testWidgets('GlassSelect shows label and changes value', (tester) async {
    var value = 'open';
    await tester.pumpWidget(
      _app(
        Palette.light,
        StatefulBuilder(
          builder: (context, setState) => GlassSelect<String>(
            label: 'Status',
            value: value,
            options: const {'open': 'Open', 'resolved': 'Resolved'},
            onChanged: (v) => setState(() => value = v),
          ),
        ),
      ),
    );
    expect(find.text('Status: '), findsOneWidget);
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Resolved').last);
    await tester.pumpAndSettle();
    expect(value, 'resolved');
  });
}
