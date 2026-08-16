// HTTP client for the Ouracle server. Bearer-token auth, async/await.

import Foundation

extension Error {
    /// Task/URLSession cancellation — never worth showing to the user.
    var isCancellation: Bool {
        if self is CancellationError { return true }
        if let urlError = self as? URLError, urlError.code == .cancelled { return true }
        if let ouracleError = self as? OuracleError,
           case .network(let inner) = ouracleError {
            return inner.isCancellation
        }
        return false
    }
}

enum OuracleError: LocalizedError {
    case notConfigured
    case unauthorized
    case server(Int, String)
    case network(Error)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Server URL or token not set. Open Settings."
        case .unauthorized:
            return "Server rejected the token. Check it in Settings."
        case .server(let code, let detail):
            return "Server error \(code): \(detail)"
        case .network(let error):
            return "Network error: \(error.localizedDescription)"
        case .decoding(let error):
            return "Unexpected response format: \(error.localizedDescription)"
        }
    }
}

struct OuracleClient {
    let baseURL: URL
    let token: String
    var session: URLSession = .shared

    func ping() async throws -> ServerStatus {
        try await get("api/mobile/ping")
    }

    func sync(windowDays: Int? = nil) async throws -> SyncResponse {
        var query: [URLQueryItem] = []
        if let windowDays {
            query.append(URLQueryItem(name: "window_days", value: String(windowDays)))
        }
        return try await get("api/mobile/sync", query: query)
    }

    func insights(day: String) async throws -> TodayInsights {
        try await get("api/mobile/insights/\(day)")
    }

    func sleepSessions(day: String) async throws -> [SleepSessionDetail] {
        try await get("api/mobile/sleep/\(day)")
    }

    struct RingSyncState: Codable {
        let cursor: UInt32
        let storedEvents: Int
        let latestEventAt: UInt32?
        let lastAttemptAt: String?
        let lastStatus: String?
        let lastAdded: Int?
        let bytesLeft: UInt32?
        let caughtUp: Bool?

        enum CodingKeys: String, CodingKey {
            case cursor
            case storedEvents = "stored_events"
            case latestEventAt = "latest_event_at"
            case lastAttemptAt = "last_attempt_at"
            case lastStatus = "last_status"
            case lastAdded = "last_added"
            case bytesLeft = "bytes_left"
            case caughtUp = "caught_up"
        }
    }

    /// A night rebuilt from ring events — available even when the cloud
    /// hasn't scored the night.
    func ringNight(day: String) async throws -> RingNight {
        try await get("api/mobile/ring-night/\(day)")
    }

    func ringSyncState() async throws -> RingSyncState {
        try await get("api/mobile/ring-events/state")
    }

    /// A history frame ready for upload. Deliberately independent of the BLE
    /// client so the widget extension (which shares this file) needn't
    /// compile CoreBluetooth code.
    struct RingEventPayload: Encodable {
        let tag: Int
        let timestamp: UInt32
        let body: String
    }

    /// Uploads raw history frames; the server decodes them later.
    ///
    /// `status` is reported even for empty or failed attempts so background
    /// syncing leaves a trace rather than being invisible.
    func uploadRingEvents(
        _ events: [RingEventPayload], nextCursor: UInt32?, status: String,
        bytesLeft: UInt32? = nil
    ) async throws -> RingSyncState {
        struct Body: Encodable {
            let events: [RingEventPayload]
            let next_cursor: UInt32?
            let status: String
            let bytes_left: UInt32?
        }
        return try await post(
            "api/mobile/ring-events",
            body: Body(
                events: events, next_cursor: nextCursor, status: status,
                bytes_left: bytesLeft
            )
        )
    }

    /// Nightly ring figures across a window, beside the cloud's.
    func ringTrends(days: Int = 30) async throws -> RingTrends {
        try await get(
            "api/mobile/ring-trends",
            query: [URLQueryItem(name: "days", value: String(days))]
        )
    }

    /// Whether every night Oura scored actually has ring data behind it.
    func ringCoverage() async throws -> RingCoverage {
        try await get("api/mobile/ring-coverage")
    }

    func registerPushToken(_ token: String, deviceName: String) async throws {
        struct Body: Encodable {
            let token: String
            let device_name: String
        }
        struct Response: Decodable { let status: String }
        let _: Response = try await post(
            "api/mobile/push-token", body: Body(token: token, device_name: deviceName)
        )
    }

    private func post<B: Encodable, T: Decodable>(
        _ path: String, body: B
    ) async throws -> T {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        request.timeoutInterval = 20

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw OuracleError.network(error)
        }
        let http = response as! HTTPURLResponse
        switch http.statusCode {
        case 200:
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw OuracleError.decoding(error)
            }
        case 401, 403:
            throw OuracleError.unauthorized
        default:
            let detail = String(data: data, encoding: .utf8) ?? ""
            throw OuracleError.server(http.statusCode, String(detail.prefix(200)))
        }
    }

    private func get<T: Decodable>(
        _ path: String, query: [URLQueryItem] = []
    ) async throws -> T {
        var components = URLComponents(
            url: baseURL.appending(path: path), resolvingAgainstBaseURL: false
        )!
        if !query.isEmpty {
            components.queryItems = query
        }
        var request = URLRequest(url: components.url!)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 20

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw OuracleError.network(error)
        }

        let http = response as! HTTPURLResponse
        switch http.statusCode {
        case 200:
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw OuracleError.decoding(error)
            }
        case 401, 403:
            throw OuracleError.unauthorized
        default:
            let detail = String(data: data, encoding: .utf8) ?? ""
            throw OuracleError.server(http.statusCode, String(detail.prefix(200)))
        }
    }
}
