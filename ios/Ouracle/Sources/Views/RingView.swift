import SwiftUI

/// Direct-to-ring screen: battery, live heart rate, device info, and the
/// auth key. Everything here talks to the ring over Bluetooth — no server,
/// no cloud.
struct RingView: View {
    @State private var battery: RingBattery?
    @State private var info: RingInfo?
    @State private var reading: RingReading?
    @State private var history: [Int] = []
    @State private var status: String?
    @State private var busy = false
    @State private var streaming = false
    @State private var streamTask: Task<Void, Never>?
    @State private var keyDraft = ""
    @State private var keySaved = Keychain.has(account: "ring-auth-key")

    var body: some View {
        List {
            batterySection
            heartRateSection
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
        .onDisappear { stopStream() }
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
                    .disabled(busy || streaming || !keySaved)
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

    // MARK: - Live heart rate

    private var heartRateSection: some View {
        Section("Live heart rate") {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "heart.fill")
                    .foregroundStyle(.red)
                    .symbolEffect(.pulse, isActive: streaming)
                Text(reading?.bpm.map(String.init) ?? "–")
                    .font(.system(size: 44, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                Text("bpm").foregroundStyle(.secondary)
                Spacer()
                if let spo2 = reading?.spo2Percent {
                    VStack(alignment: .trailing) {
                        Text("\(spo2)%").font(.headline).monospacedDigit()
                        Text("SpO₂").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }

            if history.count > 1 {
                HeartRateSparkline(values: history)
                    .frame(height: 38)
            }

            Button {
                streaming ? stopStream() : startStream()
            } label: {
                Label(
                    streaming ? "Stop" : "Start live reading",
                    systemImage: streaming ? "stop.fill" : "play.fill"
                )
            }
            .disabled(busy || !keySaved)

            Text("The ring measures on its own schedule, so a value appears once it takes a reading — wear it and keep still for best results.")
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
                .disabled(busy || streaming)
            }
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
                Text("From the Oura app's database — needed for battery and heart rate.")
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

    private func startStream() {
        streaming = true
        status = "Connecting to ring…"
        history = []
        streamTask = Task {
            do {
                for try await value in RingBLEClient().streamHeartRate(seconds: 120) {
                    reading = value
                    if let bpm = value.bpm {
                        history.append(bpm)
                        if history.count > 60 { history.removeFirst() }
                        status = nil
                    } else {
                        status = value.measuring
                            ? "Ring is measuring — waiting for a value…"
                            : "No recent reading. Make sure the ring is worn."
                    }
                }
            } catch {
                status = "Error: \(error.localizedDescription)"
            }
            streaming = false
        }
    }

    private func stopStream() {
        streamTask?.cancel()
        streamTask = nil
        streaming = false
    }
}

/// Minimal line chart of recent BPM values.
struct HeartRateSparkline: View {
    let values: [Int]

    var body: some View {
        GeometryReader { geo in
            let lo = values.min() ?? 0
            let hi = values.max() ?? 1
            let span = max(hi - lo, 1)
            Path { path in
                for (index, value) in values.enumerated() {
                    let x = geo.size.width * CGFloat(index) / CGFloat(max(values.count - 1, 1))
                    let y = geo.size.height * (1 - CGFloat(value - lo) / CGFloat(span))
                    index == 0 ? path.move(to: .init(x: x, y: y))
                               : path.addLine(to: .init(x: x, y: y))
                }
            }
            .stroke(.red, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        }
    }
}
