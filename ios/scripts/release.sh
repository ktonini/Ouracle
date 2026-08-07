#!/bin/bash
# Ship a TestFlight build: bump build number, regenerate the project,
# archive, export + upload.
#
# Signing: manual, using the stored distribution identity and App Store
# profiles (CI imports them from secrets). Cloud signing is deliberately
# NOT used — it mints a new Apple certificate per run and trips the
# per-account cap. Locally, run with CLOUD_SIGNING=1 to fall back to
# -allowProvisioningUpdates.
set -euo pipefail

cd "$(dirname "$0")/.."

KEY_ID="${KEY_ID:-Y9PQ9VX2S2}"
ISSUER_ID="${ISSUER_ID:-90c08fce-2fe1-43bd-a8cc-83c076f3a78d}"
KEY_PATH="${KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8}"

# Build number = epoch minutes: monotonically increasing, no state to track.
BUILD_NUMBER=$(( $(date +%s) / 60 ))
sed -i '' "s/CURRENT_PROJECT_VERSION: \"[0-9]*\"/CURRENT_PROJECT_VERSION: \"$BUILD_NUMBER\"/" project.yml
echo "Build number: $BUILD_NUMBER"

xcodegen generate

ARCHIVE="build/Ouracle.xcarchive"
rm -rf "$ARCHIVE"

SIGNING_ARGS=(
  -authenticationKeyID "$KEY_ID"
  -authenticationKeyIssuerID "$ISSUER_ID"
  -authenticationKeyPath "$KEY_PATH"
)
# Release configuration pins manual signing per target in project.yml.
if [ "${CLOUD_SIGNING:-0}" = "1" ]; then
  SIGNING_ARGS+=(-allowProvisioningUpdates)
fi

xcodebuild -project Ouracle.xcodeproj -scheme Ouracle \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE" \
  "${SIGNING_ARGS[@]}" \
  archive | grep -E "error:|ARCHIVE" || true

test -d "$ARCHIVE" || { echo "Archive failed"; exit 1; }

xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export \
  -authenticationKeyID "$KEY_ID" \
  -authenticationKeyIssuerID "$ISSUER_ID" \
  -authenticationKeyPath "$KEY_PATH" \
  | grep -E "error:|EXPORT|Upload" || true

echo "Uploaded build $BUILD_NUMBER — App Store Connect will process it (~5-15 min)."
