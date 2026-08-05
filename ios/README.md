# Ouracle iOS

SwiftUI companion app for the Ouracle server. Three tabs: **Today** (score
rings, metric grid, guidance/action cards, workouts), **History** (daily score
list), **Settings** (server URL + device token, connection test).

## Project generation

The Xcode project is generated — do not edit `Ouracle.xcodeproj` by hand:

```bash
brew install xcodegen   # once
cd ios && xcodegen generate
```

Re-run after adding/removing source files or editing `project.yml`.

## Build & run

1. `open ios/Ouracle.xcodeproj`
2. Signing & Capabilities → select your personal team (bundle id
   `com.ktonini.ouracle`)
3. Run on your iPhone (or any simulator).

First launch: open Settings in the app, confirm the server URL
(`https://oura.cmd.link`), paste your device token (the `ios-keith` entry in
`~/pods/ouracle/env` on cmd), hit **Test connection**, then **Save**.

The token is stored in the iOS Keychain; the URL in UserDefaults.

## CLI build (no signing)

```bash
cd ios
xcodebuild -project Ouracle.xcodeproj -scheme Ouracle \
  -destination "generic/platform=iOS Simulator" build CODE_SIGNING_ALLOWED=NO
xcodebuild -project Ouracle.xcodeproj -scheme Ouracle \
  -destination "platform=iOS Simulator,name=iPhone 16" test
```

Requires the iOS platform runtime (`xcodebuild -downloadPlatform iOS`).

## API contract

Models in `Sources/Models/SyncModels.swift` mirror
`backend/src/api/mobile.py` response schemas (ported from the Android
client's `SyncDtos.kt`). Auth is `Authorization: Bearer <device token>` —
per-device tokens come from `OURACLE_MOBILE_TOKENS` on the server.
