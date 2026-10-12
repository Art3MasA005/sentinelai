import 'dart:ui';

import 'package:flutter/material.dart';

/// One complete colour set. `dark` is sampled from the design mockups; `light` is the
/// Apple-style frosted-glass variant (translucent surfaces over a soft colour field).
class Palette {
  const Palette({
    required this.brightness,
    required this.glass,
    required this.background,
    required this.sidebar,
    required this.panel,
    required this.panelRaised,
    required this.tableHeader,
    required this.rowAlt,
    required this.border,
    required this.glassEdge,
    required this.track,
    required this.text,
    required this.textSecondary,
    required this.textMuted,
    required this.blue,
    required this.purple,
    required this.green,
    required this.orange,
    required this.red,
    required this.cyan,
    required this.yellow,
    required this.navActive,
    required this.navActiveBorder,
    required this.okSurface,
    required this.okBorder,
    required this.offlineSurface,
    required this.demoSurface,
    required this.shadow,
  });

  final Brightness brightness;

  /// Surfaces are translucent and blur what is behind them.
  final bool glass;
  final Color background, sidebar, panel, panelRaised, tableHeader, rowAlt, border, glassEdge, track;
  final Color text, textSecondary, textMuted;
  final Color blue, purple, green, orange, red, cyan, yellow;
  final Color navActive, navActiveBorder, okSurface, okBorder, offlineSurface, demoSurface, shadow;

  static const dark = Palette(
    brightness: Brightness.dark,
    glass: false,
    background: Color(0xFF070B12),
    sidebar: Color(0xFF0A111D),
    panel: Color(0xFF0D1522),
    panelRaised: Color(0xFF111C2C),
    tableHeader: Color(0xFF111B2A),
    rowAlt: Color(0xFF0B121E),
    border: Color(0xFF1B2839),
    glassEdge: Color(0xFF1B2839),
    track: Color(0xFF1A2738),
    text: Color(0xFFE8EEF8),
    textSecondary: Color(0xFF8291A8),
    textMuted: Color(0xFF596A82),
    blue: Color(0xFF4B9BFF),
    purple: Color(0xFF8257E8),
    green: Color(0xFF31C779),
    orange: Color(0xFFF4A623),
    red: Color(0xFFF04E5E),
    cyan: Color(0xFF38D9F5),
    yellow: Color(0xFFF2CC4A),
    navActive: Color(0xFF211B46),
    navActiveBorder: Color(0xFF4A3A9A),
    okSurface: Color(0xFF102B27),
    okBorder: Color(0xFF1E6C49),
    offlineSurface: Color(0xFF2B1218),
    demoSurface: Color(0xFF2E2210),
    shadow: Color(0x00000000),
  );

  static const light = Palette(
    brightness: Brightness.light,
    glass: true,
    background: Color(0xFFEEF2F8),
    sidebar: Color(0x8CFFFFFF),
    panel: Color(0x99FFFFFF),
    panelRaised: Color(0xCCFFFFFF),
    tableHeader: Color(0x0F0F172A),
    rowAlt: Color(0x080F172A),
    border: Color(0x1A0F172A),
    glassEdge: Color(0xB3FFFFFF),
    track: Color(0x1A0F172A),
    text: Color(0xFF0F172A),
    textSecondary: Color(0xFF475569),
    textMuted: Color(0xFF8A97AB),
    blue: Color(0xFF2563EB),
    purple: Color(0xFF7C3AED),
    green: Color(0xFF16A34A),
    orange: Color(0xFFD97706),
    red: Color(0xFFDC2626),
    cyan: Color(0xFF0891B2),
    yellow: Color(0xFFCA8A04),
    navActive: Color(0x2E7C3AED),
    navActiveBorder: Color(0x667C3AED),
    okSurface: Color(0x2616A34A),
    okBorder: Color(0x6616A34A),
    offlineSurface: Color(0x1FDC2626),
    demoSurface: Color(0x26D97706),
    shadow: Color(0x1A1E293B),
  );
}

/// Theme-aware colours. `current` is switched by the app when the theme changes and the
/// whole widget tree is rebuilt, so widgets can read these like constants.
abstract final class AppColors {
  static Palette current = Palette.dark;

  static bool get isGlass => current.glass;
  static Color get background => current.background;
  static Color get sidebar => current.sidebar;
  static Color get panel => current.panel;
  static Color get panelRaised => current.panelRaised;
  static Color get tableHeader => current.tableHeader;
  static Color get rowAlt => current.rowAlt;
  static Color get border => current.border;
  static Color get glassEdge => current.glassEdge;
  static Color get track => current.track;
  static Color get text => current.text;
  static Color get textSecondary => current.textSecondary;
  static Color get textMuted => current.textMuted;
  static Color get blue => current.blue;
  static Color get purple => current.purple;
  static Color get green => current.green;
  static Color get orange => current.orange;
  static Color get red => current.red;
  static Color get cyan => current.cyan;
  static Color get yellow => current.yellow;
  static Color get navActive => current.navActive;
  static Color get navActiveBorder => current.navActiveBorder;
  static Color get okSurface => current.okSurface;
  static Color get okBorder => current.okBorder;
  static Color get offlineSurface => current.offlineSurface;
  static Color get demoSurface => current.demoSurface;
  static Color get shadow => current.shadow;
}

ThemeData buildTheme(Palette p) {
  final scheme = ColorScheme.fromSeed(seedColor: p.blue, brightness: p.brightness).copyWith(
    surface: p.glass ? const Color(0xFFF8FAFD) : p.panel,
    primary: p.blue,
    secondary: p.purple,
    error: p.red,
    onSurface: p.text,
    onPrimary: Colors.white,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: p.brightness);
  final menuColor = p.glass ? const Color(0xF2FFFFFF) : p.panelRaised;
  return base.copyWith(
    scaffoldBackgroundColor: p.background,
    canvasColor: menuColor,
    dividerColor: p.border,
    textTheme: base.textTheme.apply(bodyColor: p.text, displayColor: p.text),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: p.glass ? const Color(0xF21E293B) : p.panelRaised,
        borderRadius: const BorderRadius.all(Radius.circular(6)),
      ),
      textStyle: TextStyle(color: p.glass ? Colors.white : p.text, fontSize: 12),
    ),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      filled: true,
      fillColor: p.panelRaised,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      hintStyle: TextStyle(color: p.textMuted, fontSize: 13),
      labelStyle: TextStyle(color: p.textSecondary, fontSize: 13),
      border: OutlineInputBorder(borderSide: BorderSide(color: p.border)),
      enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: p.border)),
      focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: p.blue)),
    ),
    dialogTheme: DialogThemeData(backgroundColor: p.glass ? const Color(0xF5FFFFFF) : p.panel),
    popupMenuTheme: PopupMenuThemeData(color: menuColor),
    chipTheme: ChipThemeData(
      backgroundColor: p.panelRaised,
      labelStyle: TextStyle(color: p.text, fontSize: 12.5),
      side: BorderSide(color: p.border),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.glass ? const Color(0xF21E293B) : p.panelRaised,
      contentTextStyle: TextStyle(color: p.glass ? Colors.white : p.text),
      behavior: SnackBarBehavior.floating,
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.all(Colors.white),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.disabled)
            ? p.track
            : s.contains(WidgetState.selected)
            ? p.green
            : p.red,
      ),
      trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: p.blue,
        foregroundColor: Colors.white,
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(p.glass ? 10 : 6)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.text,
        backgroundColor: p.glass ? const Color(0x80FFFFFF) : null,
        side: BorderSide(color: p.glass ? p.glassEdge : p.border),
        textStyle: const TextStyle(fontSize: 13),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(p.glass ? 10 : 6)),
      ),
    ),
  );
}

abstract final class TextStyles {
  static TextStyle get pageTitle => TextStyle(fontSize: 30, fontWeight: FontWeight.w700, color: AppColors.text);
  static TextStyle get pageSubtitle => TextStyle(fontSize: 14, color: AppColors.textSecondary);
  static TextStyle get panelTitle => TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.text);
  static TextStyle get label =>
      TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: AppColors.textSecondary);
  static TextStyle get body => TextStyle(fontSize: 13, color: AppColors.text);
  static TextStyle get secondary => TextStyle(fontSize: 12, color: AppColors.textSecondary);
  static TextStyle get mono =>
      TextStyle(fontSize: 12.5, color: AppColors.text, fontFeatures: const [FontFeature.tabularFigures()]);
}

/// Frosted-glass surface in the light theme; a plain bordered panel in the dark theme.
class Glass extends StatelessWidget {
  const Glass({super.key, required this.child, this.radius = 12, this.padding, this.color, this.blur = 24});
  final Widget child;
  final double radius;
  final EdgeInsetsGeometry? padding;
  final Color? color;
  final double blur;

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radius);
    if (!AppColors.isGlass) {
      return Container(
        padding: padding,
        decoration: BoxDecoration(
          color: color ?? AppColors.panel,
          borderRadius: r,
          border: Border.all(color: AppColors.border),
        ),
        child: child,
      );
    }
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: r,
        boxShadow: [BoxShadow(color: AppColors.shadow, blurRadius: 30, offset: const Offset(0, 10))],
      ),
      child: ClipRRect(
        borderRadius: r,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
          child: Container(
            padding: padding,
            decoration: BoxDecoration(
              borderRadius: r,
              color: color ?? AppColors.panel,
              border: Border.all(color: AppColors.glassEdge),
              // Subtle top highlight, like light catching the edge of glass.
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Colors.white.withValues(alpha: 0.35), Colors.white.withValues(alpha: 0.05)],
              ),
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// Soft colour field behind glass surfaces (light theme); a flat colour in the dark theme.
class AppBackground extends StatelessWidget {
  const AppBackground({super.key});

  @override
  Widget build(BuildContext context) {
    if (!AppColors.isGlass) return ColoredBox(color: AppColors.background);
    Widget blob(Alignment a, double size, Color c) => Align(
      alignment: a,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(colors: [c, c.withValues(alpha: 0)]),
        ),
      ),
    );
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFE9EEFB), Color(0xFFF3EEF9), Color(0xFFEAF5F4)],
        ),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          blob(const Alignment(-1.1, -1.0), 760, const Color(0x668BA8FF)),
          blob(const Alignment(1.05, -0.85), 680, const Color(0x55C4A1FF)),
          blob(const Alignment(0.2, 0.25), 620, const Color(0x3D7FD8E6)),
          blob(const Alignment(-0.7, 1.15), 700, const Color(0x45FFB4C8)),
          blob(const Alignment(1.1, 1.1), 640, const Color(0x45A5E3C0)),
        ],
      ),
    );
  }
}
