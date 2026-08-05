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
