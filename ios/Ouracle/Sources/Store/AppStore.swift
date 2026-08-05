// App state: connection settings + the latest sync payload.

import Foundation
import SwiftUI

@MainActor
final class AppStore: ObservableObject {
    @AppStorage("serverURL") var serverURLString: String = "https://oura.cmd.link"
    @Published var token: String
    @Published var sync: SyncResponse?
    @Published var isLoading = false
    @Published var lastError: String?
    @Published var lastRefreshed: Date?

    init() {
        // Env override for development (simulator launches, previews):
        // SIMCTL_CHILD_OURACLE_TOKEN=... xcrun simctl launch ...
        let env = ProcessInfo.processInfo.environment
        token = env["OURACLE_TOKEN"] ?? Keychain.read(account: "api-token") ?? ""
        if let url = env["OURACLE_URL"] {
            serverURLString = url
        }
    }

    var isConfigured: Bool {
        URL(string: serverURLString) != nil && !token.isEmpty
    }

    var client: OuracleClient? {
        guard let url = URL(string: serverURLString), !token.isEmpty else {
            return nil
        }
        return OuracleClient(baseURL: url, token: token)
    }

    var today: DailySummary? { sync?.days.last }

    func saveToken(_ newToken: String) {
        token = newToken
        Keychain.save(newToken, account: "api-token")
    }

    func refresh(windowDays: Int = 90) async {
        guard let client else {
            lastError = OuracleError.notConfigured.localizedDescription
            return
        }
        isLoading = true
        lastError = nil
        do {
            sync = try await client.sync(windowDays: windowDays)
            lastRefreshed = Date()
        } catch {
            lastError = error.localizedDescription
        }
        isLoading = false
    }

    /// Settings-screen connection check; returns a human-readable outcome.
    func testConnection(urlString: String, token: String) async -> String {
        guard let url = URL(string: urlString), !token.isEmpty else {
            return "Enter a server URL and token first."
        }
        let probe = OuracleClient(baseURL: url, token: token)
        do {
            let status = try await probe.ping()
            let latest = status.latestDay ?? "no data yet"
            return "Connected — latest day: \(latest)"
        } catch {
            return error.localizedDescription
        }
    }
}
