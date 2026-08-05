import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var store: AppStore
    @State private var urlDraft = ""
    @State private var tokenDraft = ""
    @State private var testResult: String?
    @State private var testing = false

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
