import SwiftUI

/// Direct-to-ring screen: battery, device info, and the auth key.
/// Everything here talks to the ring over Bluetooth — no server, no cloud.
struct RingView: View {
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
            deviceSection
            keySection
        }
        .navigationTitle("Ring")
        .navigationBarTitleDisplayMode(.inline)
        .task { if keySaved, battery == nil { await refreshBattery() } }
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

    private func refreshBattery() async {
        busy = true
        status = nil
        do { battery = try await RingBLEClient().readBattery() }
        catch { status = "Error: \(error.localizedDescription)" }
        busy = false
    }

}
