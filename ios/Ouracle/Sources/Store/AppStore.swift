// App state: connection settings + the latest sync payload.

import Foundation
import SwiftUI
import WidgetKit

@MainActor
final class AppStore: ObservableObject {
    @AppStorage("serverURL") var serverURLString: String = "https://oura.cmd.link"
    @AppStorage("healthExportEnabled") var healthExportEnabled: Bool = false
    @AppStorage("pushRegistered") var pushRegistered: Bool = false
    @AppStorage("ringSyncEnabled") var ringSyncEnabled: Bool = true
    /// The ring still held events we hadn't collected when the last drain
    /// stopped. Persisted, so a cold start still knows to hurry.
    @AppStorage("ringBacklog") var ringBacklog: Bool = false
    @Published var lastRingSyncCount: Int?
    private var ringSyncing = false
    private var lastRingSync: Date?
    /// Don't drain more often than this when opening the app repeatedly.
    private let ringSyncInterval: TimeInterval = 30 * 60
    /// …but while the ring is behind, half an hour between capped runs never
    /// catches up. Drain on almost every foreground until it reports empty.
    private let ringCatchUpInterval: TimeInterval = 2 * 60
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

    /// Server sends days newest-first; normalize ascending so `.last` is
    /// always the most recent day regardless of contract order.
    var days: [DailySummary] {
        (sync?.days ?? []).sorted { $0.day < $1.day }
    }

    var today: DailySummary? { days.last }

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

    /// Drains the ring's history in the background and uploads it.
    ///
    /// Deliberately quiet: the ring is often unreachable (out of range, busy,
    /// or simply ignoring us), and a failed attempt is not worth telling the
    /// user about — the cursor is server-side and idempotent, so the next
    /// attempt simply picks up where this one stopped. Manual sync in the Ring
    /// screen still surfaces errors.
    func syncRingHistoryQuietly() async {
        guard ringSyncEnabled, let client else { return }
        // One attempt per interval; draining is slow and battery-hungry. While
        // the ring still holds a backlog that pacing loses ground — it produces
        // events faster than one capped run per half hour can collect them — so
        // back off only once we know we're caught up.
        let interval = ringBacklog ? ringCatchUpInterval : ringSyncInterval
        if let last = lastRingSync, Date().timeIntervalSince(last) < interval {
            return
        }
        guard !ringSyncing else { return }
        ringSyncing = true
        defer { ringSyncing = false }

        do {
            let state = try await client.ringSyncState()
            var chunks = 0
            let result = try await RingBLEClient().syncHistory(
                from: state.cursor,
                timeBudget: 120
            ) { events, nextCursor in
                chunks += 1
                _ = try await client.uploadRingEvents(
                    events.map {
                        .init(tag: Int($0.tag), timestamp: $0.timestamp, body: $0.body.hexString)
                    },
                    nextCursor: nextCursor,
                    status: "auto: ok (chunk \(chunks))"
                )
            }
            if result.uploaded == 0 {
                _ = try await client.uploadRingEvents(
                    [], nextCursor: nil, status: "auto: nothing new",
                    bytesLeft: result.bytesLeft
                )
            } else {
                // Final status carries the backlog, so the server state shows
                // whether catching up is working without opening the app.
                _ = try await client.uploadRingEvents(
                    [], nextCursor: nil,
                    status: result.caughtUp
                        ? "auto: ok, caught up (\(result.uploaded))"
                        : "auto: ok, \(result.bytesLeft) bytes left (\(result.uploaded))",
                    bytesLeft: result.bytesLeft
                )
            }
            ringBacklog = !result.caughtUp
            lastRingSyncCount = result.uploaded
            lastRingSync = Date()
        } catch {
            // Quiet for the user, but recorded server-side so a run of
            // failures is visible rather than looking like "nothing new".
            NSLog("Background ring sync skipped: %@", error.localizedDescription)
            lastRingSync = Date()
            _ = try? await client.uploadRingEvents(
                [], nextCursor: nil,
                status: "auto failed: \(error.localizedDescription.prefix(120))"
            )
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
