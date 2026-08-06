// APNs registration: permission prompt, device-token receipt, and upload
// to the server so wake reports arrive as native notifications.

import SwiftUI
import UIKit
import UserNotifications

final class PushDelegate: NSObject, UIApplicationDelegate {
    static let shared = PushDelegate()

    /// Set by the store so the delegate can upload the token on arrival.
    var onToken: ((String) -> Void)?

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        onToken?(hex)
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        NSLog("APNs registration failed: %@", error.localizedDescription)
    }
}

extension AppStore {
    /// Settings toggle: ask permission, register, upload the token.
    func enablePushNotifications() async -> String {
        let center = UNUserNotificationCenter.current()
        do {
            let granted = try await center.requestAuthorization(
                options: [.alert, .sound, .badge]
            )
            guard granted else {
                return "Notifications denied — enable in iOS Settings."
            }
        } catch {
            return "Permission error: \(error.localizedDescription)"
        }

        PushDelegate.shared.onToken = { [weak self] token in
            Task { @MainActor in
                await self?.uploadPushToken(token)
            }
        }
        await MainActor.run {
            UIApplication.shared.registerForRemoteNotifications()
        }
        return "Requesting device token…"
    }

    func uploadPushToken(_ token: String) async {
        guard let client else { return }
        do {
            try await client.registerPushToken(
                token, deviceName: UIDevice.current.name
            )
            pushRegistered = true
        } catch {
            lastError = "Push registration: \(error.localizedDescription)"
        }
    }
}
