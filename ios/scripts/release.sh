#!/bin/bash
# Ship a TestFlight build: bump build number, regenerate the project,
# archive with App Store Connect cloud signing, export + upload.
#
# Requires the ASC API key at ~/.appstoreconnect/private_keys/AuthKey_<ID>.p8
set -euo pipefail

cd "$(dirname "$0")/.."

# Overridable for CI (GitHub Actions passes these from repo secrets).
KEY_ID="${KEY_ID:-Y9PQ9VX2S2}"
ISSUER_ID="${ISSUER_ID:-90c08fce-2fe1-43bd-a8cc-83c076f3a78d}"
KEY_PATH="${KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8}"

# Build number = seconds-truncated epoch: monotonically increasing, no state.
BUILD_NUMBER=$(( $(date +%s) / 60 ))
sed -i '' "s/CURRENT_PROJECT_VERSION: \"[0-9]*\"/CURRENT_PROJECT_VERSION: \"$BUILD_NUMBER\"/" project.yml
echo "Build number: $BUILD_NUMBER"

xcodegen generate

ARCHIVE="build/Ouracle.xcarchive"
rm -rf "$ARCHIVE"

xcodebuild -project Ouracle.xcodeproj -scheme Ouracle \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates \
  -authenticationKeyID "$KEY_ID" \
  -authenticationKeyIssuerID "$ISSUER_ID" \
  -authenticationKeyPath "$KEY_PATH" \
  archive | grep -E "error:|warning: .*[Ss]ign|ARCHIVE" || true

test -d "$ARCHIVE" || { echo "Archive failed"; exit 1; }

xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export \
  -allowProvisioningUpdates \
  -authenticationKeyID "$KEY_ID" \
  -authenticationKeyIssuerID "$ISSUER_ID" \
  -authenticationKeyPath "$KEY_PATH" \
  | grep -E "error:|EXPORT|Upload" || true

echo "Uploaded build $BUILD_NUMBER — App Store Connect will process it (~5-15 min)."
