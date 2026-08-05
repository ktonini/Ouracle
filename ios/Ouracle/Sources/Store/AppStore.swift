// App state: connection settings + the latest sync payload.

import Foundation
import SwiftUI
import WidgetKit

@MainActor
final class AppStore: ObservableObject {
    @AppStorage("serverURL") var serverURLString: String = "https://oura.cmd.link"
    @AppStorage("healthExportEnabled") var healthExportEnabled: Bool = false
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
        guard !isLoading else { return }
        isLoading = true
        lastError = nil
        do {
            // Unstructured Task: SwiftUI cancels .refreshable/.task closures
            // on view updates, which would abort the URLSession request
            // ("Network error: cancelled"). The inner task is immune, and
            // awaiting .value is not a cancellation point.
            sync = try await Task { try await client.sync(windowDays: windowDays) }.value
            lastRefreshed = Date()
            publishWidgetSnapshot()
            await exportToHealthIfEnabled()
        } catch {
            if !error.isCancellation {
                lastError = error.localizedDescription
            }
        }
        isLoading = false
    }

    /// Pushes the latest day's sleep into Apple Health (idempotent via
    /// sync identifiers). Failures are logged to lastError but don't block.
    private func exportToHealthIfEnabled() async {
        guard healthExportEnabled, HealthKitExporter.shared.isAvailable,
              let client, let day = today
        else { return }
        do {
            let sessions = try await client.sleepSessions(day: day.day)
            guard !sessions.isEmpty else { return }
            try await HealthKitExporter.shared.export(sessions: sessions, day: day)
        } catch {
            lastError = "Health export: \(error.localizedDescription)"
        }
    }

    /// Settings toggle handler: request HealthKit authorization on enable.
    func setHealthExport(enabled: Bool) async {
        if enabled {
            do {
                try await HealthKitExporter.shared.requestAuthorization()
                healthExportEnabled = true
                await exportToHealthIfEnabled()
            } catch {
                healthExportEnabled = false
                lastError = "Health access: \(error.localizedDescription)"
            }
        } else {
            healthExportEnabled = false
        }
    }

    /// Hands the widget its config and latest scores, then asks WidgetKit
    /// to redraw.
    private func publishWidgetSnapshot() {
        SharedStore.save(serverURL: serverURLString)
        if let day = today {
            SharedStore.save(snapshot: .init(
                day: day.day,
                sleep: day.sleepScore,
                readiness: day.readinessScore,
                activity: day.activityScore,
                steps: day.steps,
                updatedAt: Date()
            ))
        }
        WidgetCenter.shared.reloadAllTimelines()
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
