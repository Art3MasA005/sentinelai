# SentinelAI — Flutter app

Desktop research console for the SentinelAI backend. It talks to the local FastAPI backend at
`http://127.0.0.1:8765` (change it under **Settings → Backend connection**).

## Run

```powershell
# 1. backend (separate terminal)
cd ..\backend
.\.venv\Scripts\python.exe -m app.cli serve

# 2. app
cd ..\app_flutter
flutter run -d chrome      # or: flutter run -d windows (needs Visual Studio "Desktop development with C++")
```

## Pages

Dashboard · Alerts (triage) · Traffic Monitor · Analysis · Drift Monitor · Adaptation Center ·
Experiments (create / start / pause / step / cancel) · Reports (compare, export, reproducibility) ·
Rules (versioned policies) · System · Settings.

Themes: **Dark · Security console** and **Light · Frosted glass** (top bar ☀/🌙 or Settings).

## Layout

```
lib/
  main.dart              app + theme switching
  core/                  API client, models, state (Riverpod), theme/glass, widgets, charts, menus
  features/<page>/       one folder per screen
test/                    widget tests (fake backend via package:http MockClient) + menu goldens
```

Dev deep links (web): `?page=alerts&theme=light&alert=<flow id>&flow=<flow id>`.

## Checks

```powershell
flutter analyze
flutter test
```
