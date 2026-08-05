// Minimal Keychain wrapper for the API token. The server URL is plain
// preference data; the token is the only secret.

import Foundation
import Security

enum Keychain {
    private static let service = "com.ktonini.ouracle"

    /// Items live in the App Group access group so the widget extension can
    /// read the token too. (App Group IDs double as keychain access groups.)
    /// The simulator ignores access groups, so it is omitted there.
    private static var accessGroup: String? {
        #if targetEnvironment(simulator)
        return nil
        #else
        return SharedStore.appGroup
        #endif
    }

    private static func baseQuery(account: String, shared: Bool) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if shared, let accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }

    static func save(_ value: String, account: String) {
        let query = baseQuery(account: account, shared: true)
        SecItemDelete(query as CFDictionary)
        var attributes = query
        attributes[kSecValueData as String] = Data(value.utf8)
        SecItemAdd(attributes as CFDictionary, nil)
    }

    static func read(account: String) -> String? {
        if let value = read(account: account, shared: true) {
            return value
        }
        // Migration path: token saved before the App Group existed.
        if let legacy = read(account: account, shared: false) {
            save(legacy, account: account)
            return legacy
        }
        return nil
    }

    private static func read(account: String, shared: Bool) -> String? {
        var query = baseQuery(account: account, shared: shared)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(account: String) {
        SecItemDelete(baseQuery(account: account, shared: true) as CFDictionary)
        SecItemDelete(baseQuery(account: account, shared: false) as CFDictionary)
    }
}
