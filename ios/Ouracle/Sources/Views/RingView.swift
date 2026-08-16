import SwiftUI

/// Direct-to-ring screen: battery, device info, and the auth key.
/// Everything here talks to the ring over Bluetooth — no server, no cloud.
struct RingView: View {
    @EnvironmentObject var store: AppStore
    @State private var historyState: OuracleClient.RingSyncState?
    @State private var coverage: RingCoverage?
    @State private var historyStatus: String?
    @State private var syncing = false
    @State private var battery: RingBattery?
    @State private var info: RingInfo?
    @State private var status: String?
    @State private var busy = false
    @State private var features: [(name: String, on: Bool)] = []
    @State private var diagnostics: [String] = []
    @State private var keyDraft = ""
    @State private var keySaved = Keychain.has(account: "ring-auth-key")

    var body: some View {
        List {
            batterySection
            if let status {
                Section {
                    Text(status)
                        .font(.footnote)
                        .foregroundStyle(status.hasPrefix("Error") ? .red : .secondary)
                }
            }
            historySection
            deviceSection
            keySection
        }
        .navigationTitle("Ring")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            historyState = try? await store.client?.ringSyncState()
            coverage = try? await store.client?.ringCoverage()
            if keySaved, battery == nil { await refreshBattery() }
        }
    }

    // MARK: - Battery

    private var batterySection: some View {
        Section {
            HStack(spacing: 16) {
                ZStack {
                    Circle()
                        .stroke(.quaternary, lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: CGFloat(battery?.percent ?? 0) / 100)
                        .stroke(batteryColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.easeOut(duration: 0.5), value: battery?.percent)
                    VStack(spacing: 0) {
                        Text(battery.map { "\($0.percent)" } ?? "–")
                            .font(.title2.weight(.semibold))
                            .monospacedDigit()
                        Text("%").font(.caption2).foregroundStyle(.secondary)
                    }
                }
                .frame(width: 78, height: 78)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Ring battery").font(.headline)
                    if let battery {
                        Text(battery.charging ? "Charging" : "Not charging")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    } else {
                        Text(keySaved ? "Tap refresh to read" : "Add the auth key below")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Button {
                        Task { await refreshBattery() }
                    } label: {
                        Label("Refresh", systemImage: "arrow.clockwise")
                            .font(.subheadline)
                    }
                    .buttonStyle(.bordered)
                    .disabled(busy || !keySaved)
                }
                Spacer()
            }
            .padding(.vertical, 4)
        }
    }

    private var batteryColor: Color {
        switch battery?.percent ?? 0 {
        case 50...: return .green
        case 20..<50: return .orange
        default: return .red
        }
    }

    /// Server timestamps are naive UTC (no offset), so parse them as such.
    static func parseServerDate(_ text: String) -> Date? {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: text) { return date }
        let plain = DateFormatter()
        plain.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        plain.timeZone = TimeZone(identifier: "UTC")
        return plain.date(from: String(text.prefix(19)))
    }

    // MARK: - History

    private var historySection: some View {
        Section("Ring history") {
            if let historyState {
                LabeledContent("Events stored", value: historyState.storedEvents.formatted())
                if let attempt = historyState.lastAttemptAt,
                   let when = Self.parseServerDate(attempt)
                {
                    LabeledContent("Last attempt") {
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(when.formatted(.relative(presentation: .named)))
                            if let status = historyState.lastStatus {
                                Text(status)
                                    .font(.caption2)
                                    .foregroundStyle(status.contains("failed") ? .red : .secondary)
                            }
                        }
                    }
                }
            }
            if let coverage {
                LabeledContent("Nights covered") {
                    HStack(spacing: 6) {
                        Image(systemName: coverage.isHealthy
                            ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(coverage.isHealthy ? .green : .orange)
                        Text(coverage.message)
                            .multilineTextAlignment(.trailing)
                    }
                    .font(.footnote)
                }
                if !coverage.missingSessions.isEmpty {
                    Text("Missing: \(coverage.missingSessions.joined(separator: ", "))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            if let historyStatus {
                Text(historyStatus)
                    .font(.footnote)
                    .foregroundStyle(historyStatus.hasPrefix("Error") ? .red : .secondary)
            }
            Button(syncing ? "Syncing…" : "Sync now") {
                Task { await syncHistory() }
            }
            .disabled(busy || syncing || !keySaved)

            Toggle("Sync automatically", isOn: $store.ringSyncEnabled)

            Text("Pulls the ring's own recorded events — sleep stages, HRV, temperature, motion — straight over Bluetooth. Stored raw on your server, independent of Oura's cloud. Runs quietly when you open the app: every couple of minutes while the ring has a backlog to hand over, then at most every 30 minutes once it's caught up.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Device / key

    @ViewBuilder
    private var deviceSection: some View {
        Section("Device") {
            if let info {
                LabeledContent("Firmware", value: info.firmware)
                LabeledContent("Bluetooth", value: info.btStack)
                LabeledContent("MAC", value: info.macAddress)
            } else {
                Button("Read device info") {
                    Task {
                        busy = true
                        status = nil
                        do { info = try await RingBLEClient().readInfo() }
                        catch { status = "Error: \(error.localizedDescription)" }
                        busy = false
                    }
                }
                .disabled(busy)
            }

            ForEach(features, id: \.name) { feature in
                LabeledContent(feature.name) {
                    Label(
                        feature.on ? "On" : "Off",
                        systemImage: feature.on ? "checkmark.circle.fill" : "circle"
                    )
                    .foregroundStyle(feature.on ? .green : .secondary)
                    .labelStyle(.titleAndIcon)
                }
            }
            if !diagnostics.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(diagnostics, id: \.self) { line in
                        Text(line)
                            .font(.system(.caption2, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
            }
            Button("Run connection diagnostic") {
                Task {
                    busy = true
                    diagnostics = ["running…"]
                    diagnostics = await RingBLEClient().diagnose()
                    busy = false
                }
            }
            .disabled(busy)

            Button("Reset ring mode") {
                Task {
                    busy = true
                    diagnostics = ["resetting…"]
                    diagnostics = await RingBLEClient().resetAndVerify()
                    busy = false
                }
            }
            .disabled(busy)

            Button("Check measurement features") {
                Task {
                    busy = true
                    status = nil
                    do { features = try await RingBLEClient().featureReport() }
                    catch { status = "Error: \(error.localizedDescription)" }
                    busy = false
                }
            }
            .disabled(busy || !keySaved)
        }
    }

    @ViewBuilder
    private var keySection: some View {
        Section("Auth key") {
            if keySaved {
                Label("Saved in Keychain", systemImage: "checkmark.seal.fill")
                    .foregroundStyle(.green)
                Button("Replace key", role: .destructive) {
                    keySaved = false
                    Keychain.delete(account: "ring-auth-key")
                }
            } else {
                SecureField("32 hex characters", text: $keyDraft)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Button("Save key") {
                    let clean = keyDraft.filter { !$0.isWhitespace }
                    if Data(hexString: clean)?.count == 16 {
                        Keychain.save(clean, account: "ring-auth-key")
                        keySaved = true
                        keyDraft = ""
                        status = nil
                    } else {
                        status = "Error: key must be 32 hex characters."
                    }
                }
                .disabled(keyDraft.isEmpty)
                Text("From the Oura app's database — needed to read the ring.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Actions

    /// Resumes from the server's cursor, drains the ring, uploads raw frames.
    private func syncHistory() async {
        guard let client = store.client else {
            historyStatus = "Error: set the server URL and token first."
            return
        }
        syncing = true
        historyStatus = "Connecting to ring…"
        do {
            let state = try await client.ringSyncState()
            historyStatus = "Draining from cursor \(state.cursor)…"

            // Longer budget than the background drain: the user is watching
            // this one and can see it working.
            let result = try await RingBLEClient().syncHistory(
                from: state.cursor,
                timeBudget: 600,
                onProgress: { count, left in
                    Task { @MainActor in
                        historyStatus = "\(count) events… (\(left) bytes left on ring)"
                    }
                }
            ) { events, nextCursor in
                historyState = try await client.uploadRingEvents(
                    events.map {
                        .init(tag: Int($0.tag), timestamp: $0.timestamp, body: $0.body.hexString)
                    },
                    nextCursor: nextCursor,
                    status: "manual: ok"
                )
            }

            store.ringBacklog = !result.caughtUp
            if result.uploaded == 0 {
                historyStatus = "Ring had nothing new."
                historyState = try? await client.uploadRingEvents(
                    [], nextCursor: nil, status: "manual: nothing new",
                    bytesLeft: result.bytesLeft
                )
            } else if result.caughtUp {
                historyState = try? await client.uploadRingEvents(
                    [], nextCursor: nil, status: "manual: ok, caught up",
                    bytesLeft: 0
                )
                historyStatus = "Synced \(result.uploaded) events — ring is caught up."
            } else {
                historyState = try? await client.uploadRingEvents(
                    [], nextCursor: nil, status: "manual: ok, more to collect",
                    bytesLeft: result.bytesLeft
                )
                historyStatus =
                    "Synced \(result.uploaded) events. \(result.bytesLeft) bytes still on the ring — sync again to continue."
            }
        } catch {
            historyStatus = "Error: \(error.localizedDescription)"
        }
        syncing = false
    }

    private func refreshBattery() async {
        busy = true
        status = nil
        do { battery = try await RingBLEClient().readBattery() }
        catch { status = "Error: \(error.localizedDescription)" }
        busy = false
    }

}
