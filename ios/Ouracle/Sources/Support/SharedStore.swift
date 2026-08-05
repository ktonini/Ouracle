// Data shared between the app and the widget extension via the App Group:
// connection config (URL + token) and the last-synced score snapshot the
// widget can fall back to when the network is unavailable.

import Foundation

enum SharedStore {
    static let appGroup = "group.com.ktonini.ouracle"

    private static var defaults: UserDefaults? {
        UserDefaults(suiteName: appGroup)
    }

    struct Snapshot: Codable, Equatable {
        let day: String
        let sleep: Int?
        let readiness: Int?
        let activity: Int?
        let steps: Int?
        let updatedAt: Date
    }

    static func save(snapshot: Snapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        defaults?.set(data, forKey: "widget-snapshot")
    }

    static func readSnapshot() -> Snapshot? {
        guard let data = defaults?.data(forKey: "widget-snapshot") else {
            return nil
        }
        return try? JSONDecoder().decode(Snapshot.self, from: data)
    }

    static func save(serverURL: String) {
        defaults?.set(serverURL, forKey: "server-url")
    }

    static func readServerURL() -> String? {
        defaults?.string(forKey: "server-url")
    }
}
