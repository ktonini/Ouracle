import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var store: AppStore
    @State private var urlDraft = ""
    @State private var tokenDraft = ""
    @State private var testResult: String?
    @State private var testing = false
    @State private var pushStatus: String?
    @State private var ringInfo: RingInfo?
    @State private var ringError: String?
    @State private var ringProbing = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("https://oura.cmd.link", text: $urlDraft)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    SecureField("Device token", text: $tokenDraft)
                }

                Section {
                    Button {
                        Task {
                            testing = true
                            testResult = await store.testConnection(
                                urlString: urlDraft, token: tokenDraft
                            )
                            testing = false
                        }
                    } label: {
                        if testing {
                            ProgressView()
                        } else {
                            Text("Test connection")
                        }
                    }
                    if let testResult {
                        Text(testResult)
                            .font(.footnote)
                            .foregroundStyle(
                                testResult.hasPrefix("Connected") ? .green : .red
                            )
                    }
                }

                Section {
                    Button("Save") {
                        store.serverURLString = urlDraft
                        store.saveToken(tokenDraft)
                        store.sync = nil
                        Task { await store.refresh() }
                    }
                    .disabled(urlDraft.isEmpty || tokenDraft.isEmpty)
                }

                Section("Ring (direct Bluetooth)") {
                    Button(ringProbing ? "Reading…" : "Read ring info") {
                        Task {
                            ringProbing = true
                            ringInfo = nil
                            ringError = nil
                            do {
                                ringInfo = try await RingBLEClient().readInfo()
                            } catch {
                                ringError = error.localizedDescription
                            }
                            ringProbing = false
                        }
                    }
                    .disabled(ringProbing)

                    if let ringInfo {
                        LabeledContent("Firmware", value: ringInfo.firmware)
                        LabeledContent("API", value: ringInfo.apiVersion)
                        LabeledContent("Bluetooth", value: ringInfo.btStack)
                        LabeledContent("MAC", value: ringInfo.macAddress)
                    }
                    if let ringError {
                        Text(ringError)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                    Text("Talks to the ring directly, alongside the Oura app. Battery and live heart rate need the ring's auth key (not yet configured).")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Notifications") {
                    if store.pushRegistered {
                        Label("Wake reports enabled on this device", systemImage: "bell.badge.fill")
                            .foregroundStyle(.green)
                    }
                    Button(store.pushRegistered ? "Re-register notifications" : "Enable wake notifications") {
                        Task {
                            pushStatus = await store.enablePushNotifications()
                        }
                    }
                    if let pushStatus {
                        Text(pushStatus)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    Text("A morning notification with last night's sleep, sent by your server.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Apple Health") {
                    Toggle(
                        "Export sleep to Health",
                        isOn: Binding(
                            get: { store.healthExportEnabled },
                            set: { enabled in
                                Task { await store.setHealthExport(enabled: enabled) }
                            }
                        )
                    )
                    Text("Writes sleep stages, nightly HRV, and resting heart rate. Re-exports update rather than duplicate.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if let refreshed = store.lastRefreshed {
                    Section {
                        LabeledContent(
                            "Last refreshed",
                            value: refreshed.formatted(date: .omitted, time: .shortened)
                        )
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                urlDraft = store.serverURLString
                tokenDraft = store.token
            }
        }
    }
}
