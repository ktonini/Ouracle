// Direct BLE link to the Oura ring from the phone.
//
// iOS keeps a single system-level Bluetooth central shared by all apps, so
// `retrieveConnectedPeripherals` hands us the ring while the official Oura
// app still holds it — no scanning, no disconnecting, no interference.
//
// Protocol per github.com/Th0rgal/open_oura (Ring 3/4/5 share the layout):
//   service   98ed0001-…  write 98ed0002-…  notify 98ed0003-…
//   framing   <tag> <length> <payload…>, little-endian integers
//
// Phase 1 implements only unauthenticated reads (firmware, serial). Battery
// and live HR additionally require the ring's 16-byte app-auth key.

import CommonCrypto
import CoreBluetooth
import Foundation

extension Data {
    var hexString: String { map { String(format: "%02x", $0) }.joined() }
}

struct RingInfo: Equatable {
    var apiVersion: String
    var firmware: String
    var bootloader: String
    var btStack: String
    var macAddress: String
}

struct RingBattery: Equatable {
    var percent: Int
    var charging: Bool
}

struct RingReading: Equatable {
    var bpm: Int?
    var spo2Percent: Int?
    /// Ring-reported measurement state; non-zero means it is actively sampling.
    var measuring: Bool = false
    var timestamp: Date = .now
}

enum RingBLEError: LocalizedError {
    case unavailable(String)
    case notFound
    case timeout(String)
    case badResponse(String)
    case noAuthKey
    case authFailed
    case featuresOff

    var errorDescription: String? {
        switch self {
        case .unavailable(let state): return "Bluetooth unavailable (\(state))."
        case .notFound:
            return "Ring not found. Make sure it's worn or charging and the Oura app has connected to it recently."
        case .timeout(let step): return "Timed out during \(step)."
        case .badResponse(let detail): return "Unexpected ring response: \(detail)."
        case .noAuthKey: return "No ring auth key set. Add it in Settings."
        case .authFailed: return "Ring rejected the auth key."
        case .featuresOff:
            return "The ring's heart-rate features are switched off. Enable Daytime Heart Rate (and/or SpO2) in the Oura app, then try again."
        }
    }
}

final class RingBLEClient: NSObject {
    static let serviceUUID = CBUUID(string: "98ED0001-A541-11E4-B6A0-0002A5D5C51B")
    static let writeUUID = CBUUID(string: "98ED0002-A541-11E4-B6A0-0002A5D5C51B")
    static let notifyUUID = CBUUID(string: "98ED0003-A541-11E4-B6A0-0002A5D5C51B")

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var writeChar: CBCharacteristic?

    private var powerOnContinuation: CheckedContinuation<Void, Error>?
    private var connectContinuation: CheckedContinuation<Void, Error>?
    private var responseContinuation: CheckedContinuation<Data, Error>?
    private var expectedTag: UInt8?
    private var pendingSubscriptions = 0
    /// Ties each timeout timer to the request that scheduled it.
    private var requestGeneration: UInt64 = 0
    private var capturing = false
    private var captureLog: [String] = []
    /// Subscribe only to the primary notify characteristic (Ring 3 behaviour).
    var subscribePrimaryOnly = false
    private var discoveryContinuation: CheckedContinuation<CBPeripheral, Error>?

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    // MARK: - Public API

    /// Reads firmware/serial-level device info. Requires no auth key.
    func readInfo() async throws -> RingInfo {
        try await waitForPowerOn()
        let ring = try await findRing()
        try await connect(ring)
        defer { disconnect() }

        // 0x08 "get firmware": tag 08, len 03, payload 00 00 00
        let response = try await send(Data([0x08, 0x03, 0x00, 0x00, 0x00]), label: "device info")
        return try Self.parseFirmware(response)
    }

    /// Reads the ring's battery level. Requires the 16-byte app-auth key.
    func readBattery() async throws -> RingBattery {
        guard let key = Self.storedAuthKey() else { throw RingBLEError.noAuthKey }
        try await waitForPowerOn()
        let ring = try await findRing()
        try await connect(ring)
        defer { disconnect() }

        try await authenticate(key: key)
        // 0x0C "get battery"
        let response = try await send(Data([0x0C, 0x00]), expectTag: 0x0D, label: "battery read")
        return try Self.parseBattery(response)
    }

    /// Streams heart-rate readings for `seconds`, polling the ring's latest
    /// cached measurement over a single authenticated connection.
    ///
    /// Note this is a poll, not a push: the ring measures on its own schedule,
    /// so readings repeat until it takes a new one. Values only appear while
    /// the ring is worn.
    /// - Parameter fastMode: asks the ring to measure continuously (what the
    ///   Oura app's "Live Heart Rate" does). Without it the ring samples for
    ///   one minute every five, only when still, so a reading can be up to
    ///   ~30 minutes stale. Normal mode is always restored on exit.
    func streamHeartRate(
        seconds: TimeInterval = 600,
        pollInterval: TimeInterval = 10,
        fastMode: Bool = false
    ) -> AsyncThrowingStream<RingReading, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    guard let key = Self.storedAuthKey() else {
                        throw RingBLEError.noAuthKey
                    }
                    try await waitForPowerOn()
                    let ring = try await findRing()
                    try await connect(ring)
                    try await authenticate(key: key)

                    // Which HR features will actually answer? A disabled
                    // feature stays silent, which otherwise looks like a
                    // connection timeout.
                    let daytimeOn = (try? await featureEnabled(0x02)) ?? false
                    let exerciseOn = (try? await featureEnabled(0x03)) ?? false
                    let spo2On = (try? await featureEnabled(0x04)) ?? false
                    guard daytimeOn || exerciseOn || spo2On else {
                        throw RingBLEError.featuresOff
                    }

                    // State-changing: ask the ring to measure continuously.
                    if fastMode { await setFastMode(true) }

                    let deadline = Date().addingTimeInterval(seconds)
                    while Date() < deadline, !Task.isCancelled {
                        var reading = RingReading()

                        // 0x2f/0x24 feature-latest; 0x02 daytime HR.
                        if daytimeOn,
                           let hr = try? await send(Data([0x2F, 0x02, 0x24, 0x02]), expectTag: 0x2F, label: "latest value")
                        {
                            reading = Self.parseLatestHeartRate(hr)
                        }
                        // Exercise HR reports bpm directly.
                        if reading.bpm == nil, exerciseOn,
                           let ex = try? await send(Data([0x2F, 0x02, 0x24, 0x03]), expectTag: 0x2F, label: "latest value"),
                           let parsed = try? Self.parseLatestExerciseHR(ex)
                        {
                            reading.bpm = parsed.bpm
                            reading.measuring = reading.measuring || parsed.measuring
                        }
                        // SpO2 carries a bpm sample alongside saturation.
                        if spo2On,
                           let spo2 = try? await send(Data([0x2F, 0x02, 0x24, 0x04]), expectTag: 0x2F, label: "latest value"),
                           let parsed = try? Self.parseLatestSpO2(spo2)
                        {
                            reading.spo2Percent = parsed.spo2Percent
                            if reading.bpm == nil { reading.bpm = parsed.bpm }
                        }

                        continuation.yield(reading)
                        try await Task.sleep(nanoseconds: UInt64(pollInterval * 1_000_000_000))
                    }
                    // Restore before dropping the link — a disconnected
                    // peripheral can't be told to go back to normal mode.
                    if fastMode { await setFastMode(false) }
                    disconnect()
                    continuation.finish()
                } catch {
                    if fastMode { await setFastMode(false) }
                    disconnect()
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    /// Runs the probe twice — subscribing only to the primary characteristic,
    /// then to all of them — to settle whether the extra Ring 5 channels are
    /// what stops the ring answering.
    static func compareSubscriptionModes() async -> [String] {
        var log = ["=== A: primary characteristic only ==="]
        let minimal = RingBLEClient()
        minimal.subscribePrimaryOnly = true
        log += await minimal.probe()

        try? await Task.sleep(nanoseconds: 3_000_000_000)

        log.append("=== B: all notify characteristics ===")
        let full = RingBLEClient()
        log += await full.probe()
        return log
    }

    /// Clears leftover ring modes and reports whether auth works afterwards.
    func resetAndVerify() async -> [String] {
        var log: [String] = []
        do {
            try await waitForPowerOn()
            let ring = try await findRing()
            try await connect(ring)
            await resetRingMode()
            log.append("ring mode reset sent")

            let nonce = try await send(Data([0x2F, 0x01, 0x2B]), timeout: 8, label: "nonce")
            log.append("nonce reply: \(nonce.prefix(8).hexString)")
            if nonce.first == 0x2F {
                log.append("✅ ring is issuing nonces again")
            } else {
                log.append("❌ still not a nonce — ring remains in an odd state")
            }
            disconnect()
        } catch {
            log.append("failed: \(error.localizedDescription)")
            disconnect()
        }
        return log
    }

    /// Minimal connect-and-ask used by the A/B comparison.
    func probe() async -> [String] {
        var log: [String] = []
        captureLog = []
        capturing = true
        defer { capturing = false }
        do {
            try await waitForPowerOn()
            let ring = try await findRing()
            try await connect(ring)
            log.append("connected: \(peripheral?.state == .connected ? "yes" : "no")")
            if let info = try? await send(Data([0x08, 0x03, 0x00, 0x00, 0x00]), timeout: 6, label: "info") {
                log.append("firmware: \(info.prefix(6).hexString)…  ✅")
            } else {
                log.append("firmware: NO REPLY ❌")
            }
            if let nonce = try? await send(Data([0x2F, 0x01, 0x2B]), timeout: 6, label: "nonce") {
                log.append("nonce: \(nonce.prefix(6).hexString)…  ✅")
            } else {
                log.append("nonce: NO REPLY ❌")
            }
            disconnect()
        } catch {
            log.append("failed: \(error.localizedDescription)")
            disconnect()
        }
        log += captureLog.isEmpty ? ["(no notifications)"] : captureLog
        return log
    }

    /// Connects and narrates every step, capturing raw notifications from all
    /// characteristics. For diagnosing why a command goes unanswered.
    func diagnose() async -> [String] {
        var log: [String] = []
        captureLog = []
        capturing = true
        defer { capturing = false }

        do {
            try await waitForPowerOn()
            log.append("bluetooth: on")
            let ring = try await findRing()
            log.append("found: \(ring.name ?? "unnamed") \(ring.identifier.uuidString.prefix(8))")
            log.append("state: \(ring.state == .connected ? "already connected" : "connecting")")
            try await connect(ring)
            log.append("connected: \(peripheral?.state == .connected ? "yes" : "NO")")

            // A plain read forces iOS to establish link encryption if the
            // ring demands it — writes are silently dropped until then.
            if let readable = peripheral?.services?
                .first(where: { $0.uuid == Self.serviceUUID })?
                .characteristics?.first(where: { $0.properties.contains(.read) })
            {
                peripheral?.readValue(for: readable)
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                log.append("read probe \(readable.uuid.uuidString.prefix(8)): \(readable.value?.hexString ?? "nil")")
            }

            if let service = peripheral?.services?.first(where: { $0.uuid == Self.serviceUUID }) {
                for characteristic in service.characteristics ?? [] {
                    var props: [String] = []
                    if characteristic.properties.contains(.write) { props.append("write") }
                    if characteristic.properties.contains(.writeWithoutResponse) { props.append("writeNR") }
                    if characteristic.properties.contains(.notify) { props.append("notify") }
                    if characteristic.properties.contains(.indicate) { props.append("indicate") }
                    if characteristic.properties.contains(.read) { props.append("read") }
                    let subscribed = characteristic.isNotifying ? " [subscribed]" : ""
                    log.append("char \(characteristic.uuid.uuidString.prefix(8)): \(props.joined(separator: ","))\(subscribed)")
                }
            }

            // Order matters? readBattery sends the nonce first and works;
            // the previous diagnostic sent firmware first and the nonce went
            // unanswered. Test all three positions in one session.
            if let nonce = try? await send(Data([0x2F, 0x01, 0x2B]), timeout: 8, label: "nonce") {
                log.append("1. nonce FIRST: \(nonce.prefix(20).hexString)")
            } else {
                log.append("1. nonce FIRST: NO REPLY")
            }

            if let info = try? await send(Data([0x08, 0x03, 0x00, 0x00, 0x00]), timeout: 6, label: "info") {
                log.append("2. firmware: \(info.prefix(8).hexString)")
            } else {
                log.append("2. firmware: NO REPLY")
            }

            if let nonce2 = try? await send(Data([0x2F, 0x01, 0x2B]), timeout: 8, label: "nonce2") {
                log.append("3. nonce AFTER: \(nonce2.prefix(20).hexString)")
            } else {
                log.append("3. nonce AFTER: NO REPLY")
            }

            disconnect()
        } catch {
            log.append("failed: \(error.localizedDescription)")
            disconnect()
        }

        log.append("--- all notifications seen ---")
        log.append(contentsOf: captureLog.isEmpty ? ["(none)"] : captureLog)
        return log
    }

    /// Puts the ring into (or out of) continuous-measurement mode — the same
    /// thing the Oura app's "Live Heart Rate" screen does. Best-effort: the
    /// ring also reverts to normal on its own once the connection drops.
    private func setFastMode(_ on: Bool) async {
        let flag: UInt8 = on ? 0x01 : 0x00
        // Short timeouts: the ring-mode command's ack shape isn't documented,
        // so a missing reply must not stall the session.
        _ = try? await send(Data([0x16, 0x01, flag]), expectTag: 0x17, timeout: 4, label: "ble mode")
        _ = try? await send(Data([0x31, 0x04, flag, 0x00, 0x00, 0x00]), timeout: 4, label: "ring mode")
    }

    /// Reports each measurement feature's mode, so "no heart rate" can be
    /// distinguished from "feature switched off" without guessing.
    func featureReport() async throws -> [(name: String, on: Bool)] {
        guard let key = Self.storedAuthKey() else { throw RingBLEError.noAuthKey }
        try await waitForPowerOn()
        let ring = try await findRing()
        try await connect(ring)
        defer { disconnect() }
        try await authenticate(key: key)

        var report: [(String, Bool)] = []
        for (name, id) in [("Daytime HR", UInt8(0x02)), ("Exercise HR", 0x03),
                           ("SpO2", 0x04), ("Resting HR", 0x08)] {
            let on = (try? await featureEnabled(id)) ?? false
            report.append((name, on))
        }
        return report
    }

    /// Clears any leftover fast-HR/BLE mode before authenticating.
    ///
    /// A live-HR session that dies mid-way can leave the ring in fast mode
    /// (its restore never runs, or runs after disconnect). In that state the
    /// ring answers the auth-nonce request with `17 01 02` — an 0x16 BLE-mode
    /// ack — instead of issuing a nonce, so every subsequent authenticated
    /// command fails until the mode is cleared.
    func resetRingMode() async {
        _ = try? await send(Data([0x16, 0x01, 0x00]), timeout: 4, label: "ble mode reset")
        _ = try? await send(
            Data([0x31, 0x04, 0x00, 0x00, 0x00, 0x00]), timeout: 4, label: "ring mode reset"
        )
    }

    /// App auth is session-scoped: nonce challenge, AES-ECB encrypted with
    /// the ring's key, sent back for verification.
    private func authenticate(key: Data) async throws {
        // One retry: the ring occasionally ignores the first request on a
        // freshly established link.
        // No expectTag here: filtering on 0x2f made auth start timing out on
        // the real ring, though it had worked when any reply was accepted.
        // parseNonce validates the shape instead.
        var nonceResponse = try await send(Data([0x2F, 0x01, 0x2B]), label: "auth nonce")

        // `17 01 xx` means the ring is in a leftover BLE/fast mode rather than
        // issuing a nonce. Clear it and ask once more.
        if nonceResponse.first == 0x17 {
            await resetRingMode()
            nonceResponse = try await send(Data([0x2F, 0x01, 0x2B]), label: "auth nonce")
        }
        let nonce = try Self.parseNonce(nonceResponse)
        let encrypted = try Self.aesECBEncrypt(nonce, key: key)

        var request = Data([0x2F, UInt8(encrypted.count + 1), 0x2D])
        request.append(encrypted)
        let result = try await send(request, label: "auth verify")

        // 2f022e00 = success, 2f022e01 = wrong key
        guard result.count >= 4, result[2] == 0x2E else {
            throw RingBLEError.badResponse(result.map { String(format: "%02x", $0) }.joined())
        }
        if result[3] != 0x00 { throw RingBLEError.authFailed }
    }

    static func storedAuthKey() -> Data? {
        guard let hex = Keychain.read(account: "ring-auth-key"), !hex.isEmpty else {
            return nil
        }
        return Data(hexString: hex)
    }

    // MARK: - Crypto

    /// AES-128-ECB with PKCS7 padding (PKCS5 in the protocol docs — same
    /// thing for 16-byte blocks).
    static func aesECBEncrypt(_ plaintext: Data, key: Data) throws -> Data {
        let capacity = plaintext.count + kCCBlockSizeAES128
        var output = Data(count: capacity)
        var moved = 0
        let status = output.withUnsafeMutableBytes { outBytes in
            plaintext.withUnsafeBytes { inBytes in
                key.withUnsafeBytes { keyBytes in
                    CCCrypt(
                        CCOperation(kCCEncrypt),
                        CCAlgorithm(kCCAlgorithmAES),
                        CCOptions(kCCOptionECBMode | kCCOptionPKCS7Padding),
                        keyBytes.baseAddress, key.count,
                        nil,
                        inBytes.baseAddress, plaintext.count,
                        outBytes.baseAddress, capacity,
                        &moved
                    )
                }
            }
        }
        guard status == kCCSuccess else {
            throw RingBLEError.badResponse("AES failed (\(status))")
        }
        return output.prefix(moved)
    }

    // MARK: - Response parsing

    /// Payload layout: api(3) firmware(3) bootloader(3) btStack(3) mac(6, reversed)
    static func parseFirmware(_ response: Data) throws -> RingInfo {
        guard response.count >= 2, response[0] == 0x09 else {
            throw RingBLEError.badResponse("tag \(response.first.map { String($0, radix: 16) } ?? "none")")
        }
        let payload = response.dropFirst(2)
        guard payload.count >= 18 else {
            throw RingBLEError.badResponse("short payload (\(payload.count) bytes)")
        }
        let bytes = [UInt8](payload)
        func version(_ offset: Int) -> String {
            "\(bytes[offset]).\(bytes[offset + 1]).\(bytes[offset + 2])"
        }
        let mac = bytes[12..<18].reversed()
            .map { String(format: "%02X", $0) }
            .joined(separator: ":")
        return RingInfo(
            apiVersion: version(0),
            firmware: version(3),
            bootloader: version(6),
            btStack: version(9),
            macAddress: mac
        )
    }

    /// Nonce response: `2f 10 2c <15-byte nonce>`
    static func parseNonce(_ response: Data) throws -> Data {
        guard response.count >= 3, response[0] == 0x2F, response[2] == 0x2C else {
            throw RingBLEError.badResponse(
                "nonce " + response.prefix(4).map { String(format: "%02x", $0) }.joined()
            )
        }
        let nonce = response.dropFirst(3)
        guard nonce.count == 15 else {
            throw RingBLEError.badResponse("nonce length \(nonce.count)")
        }
        return Data(nonce)
    }

    /// Feature status (`2f 02 20 <feature>`) → `2f 06 21 <feature> <mode>
    /// <status> <state> <subscription>`. Mode 0 means the feature is off, so
    /// the ring will never answer a latest-value request for it.
    private func featureEnabled(_ feature: UInt8) async throws -> Bool {
        let response = try await send(Data([0x2F, 0x02, 0x20, feature]), expectTag: 0x2F, label: "feature status")
        return Self.parseFeatureMode(response, feature: feature).map { $0 != 0 } ?? false
    }

    static func parseFeatureMode(_ response: Data, feature: UInt8) -> UInt8? {
        guard response.count >= 5, response[0] == 0x2F, response[2] == 0x21,
              response[3] == feature
        else { return nil }
        return response[4]
    }

    /// Exercise HR: bpm sits at data[4] rather than being derived from an
    /// inter-beat interval.
    static func parseLatestExerciseHR(_ response: Data) throws -> RingReading {
        let (data, state) = try latestPayload(response, feature: 0x03)
        guard data.count >= 5 else { return RingReading() }
        let bpm = Int(data[4])
        return RingReading(
            bpm: (30...220).contains(bpm) ? bpm : nil,
            measuring: state != 0
        )
    }

    /// Feature-latest response: `2f <len> 25 <feature> <result> <status>
    /// <state> <counter:2> <data…>` — so feature data starts at byte 9.
    static func latestPayload(_ response: Data, feature: UInt8) throws -> (data: Data, state: UInt8) {
        if response.count >= 4, response[0] == 0x2F, response[2] == 0x2F {
            throw RingBLEError.authFailed  // 2f022f01 = auth required
        }
        guard response.count >= 9, response[0] == 0x2F, response[2] == 0x25,
              response[3] == feature
        else {
            throw RingBLEError.badResponse(
                "latest " + response.prefix(5).map { String(format: "%02x", $0) }.joined()
            )
        }
        return (Data(response.dropFirst(9)), response[6])
    }

    /// Daytime HR: first two data bytes are the RR-corrected inter-beat
    /// interval in ms; bpm = 60000 / ibi. Zero means "no recent measurement".
    static func parseLatestHeartRate(_ response: Data) -> RingReading {
        guard let (data, state) = try? latestPayload(response, feature: 0x02),
              data.count >= 2
        else { return RingReading() }
        let ibi = Int(data[0]) | (Int(data[1]) << 8)
        let bpm = ibi > 0 ? 60_000 / ibi : nil
        // Plausibility guard: reject nonsense from a stale/garbage interval.
        let sane = bpm.flatMap { (30...220).contains($0) ? $0 : nil }
        return RingReading(bpm: sane, measuring: state != 0)
    }

    /// SpO2 feature: data[3] = SpO2 %, data[4] = bpm.
    static func parseLatestSpO2(_ response: Data) throws -> RingReading {
        let (data, state) = try latestPayload(response, feature: 0x04)
        guard data.count >= 5 else { return RingReading() }
        let spo2 = Int(data[3])
        let bpm = Int(data[4])
        return RingReading(
            bpm: (30...220).contains(bpm) ? bpm : nil,
            spo2Percent: (70...100).contains(spo2) ? spo2 : nil,
            measuring: state != 0
        )
    }

    /// Battery response: `0d <len> <percent> <charging progress> …`
    static func parseBattery(_ response: Data) throws -> RingBattery {
        // Auth-gated refusal comes back as 2f022f01.
        if response.count >= 4, response[0] == 0x2F, response[2] == 0x2F {
            throw RingBLEError.authFailed
        }
        guard response.count >= 4, response[0] == 0x0D else {
            throw RingBLEError.badResponse(
                "battery " + response.prefix(4).map { String(format: "%02x", $0) }.joined()
            )
        }
        let payload = response.dropFirst(2)
        let percent = Int(payload[payload.startIndex])
        let chargingProgress = Int(payload[payload.startIndex + 1])
        return RingBattery(percent: percent, charging: chargingProgress > 0)
    }

    // MARK: - Connection plumbing

    private func waitForPowerOn() async throws {
        if central.state == .poweredOn { return }
        try await withCheckedThrowingContinuation { continuation in
            powerOnContinuation = continuation
            // Give CoreBluetooth a moment to report state before giving up.
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                guard let self, let pending = self.powerOnContinuation else { return }
                self.powerOnContinuation = nil
                pending.resume(throwing: RingBLEError.unavailable(self.stateDescription))
            }
        }
    }

    private func findRing() async throws -> CBPeripheral {
        // Preferred: the ring the Oura app already has connected.
        if let existing = central
            .retrieveConnectedPeripherals(withServices: [Self.serviceUUID])
            .first
        {
            return existing
        }
        // Fallback: a short scan (the ring advertises when not connected).
        return try await withCheckedThrowingContinuation { continuation in
            discoveryContinuation = continuation
            central.scanForPeripherals(withServices: [Self.serviceUUID])
            DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
                guard let self, let pending = self.discoveryContinuation else { return }
                self.discoveryContinuation = nil
                self.central.stopScan()
                pending.resume(throwing: RingBLEError.notFound)
            }
        }
    }

    private func connect(_ ring: CBPeripheral) async throws {
        peripheral = ring
        ring.delegate = self
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connectContinuation = continuation
            central.connect(ring)
            DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
                guard let self, let pending = self.connectContinuation else { return }
                self.connectContinuation = nil
                pending.resume(throwing: RingBLEError.timeout("connect"))
            }
        }
    }

    /// Writes a request and waits for the matching reply. `expectTag` filters
    /// out unrelated notifications (the ring pushes its own packets, and
    /// several characteristics are subscribed).
    private func send(
        _ packet: Data, expectTag: UInt8? = nil, timeout: TimeInterval = 12,
        label: String = "response"
    ) async throws -> Data {
        guard let peripheral, let writeChar else {
            throw RingBLEError.timeout("characteristic discovery")
        }
        expectedTag = expectTag
        requestGeneration &+= 1
        let generation = requestGeneration
        let writeType: CBCharacteristicWriteType =
            writeChar.properties.contains(.write) ? .withResponse : .withoutResponse
        return try await withCheckedThrowingContinuation { continuation in
            responseContinuation = continuation
            peripheral.writeValue(packet, for: writeChar, type: writeType)
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak self] in
                // Only time out the request this timer belongs to. Without
                // the generation check, a finished request's timer fires
                // later and cancels whatever is in flight then — reporting
                // the wrong step, and breaking any multi-command session.
                guard let self, self.requestGeneration == generation,
                      let pending = self.responseContinuation
                else { return }
                self.responseContinuation = nil
                self.expectedTag = nil
                pending.resume(throwing: RingBLEError.timeout(label))
            }
        }
    }

    private func disconnect() {
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        }
        peripheral = nil
        writeChar = nil
    }

    private var stateDescription: String {
        switch central.state {
        case .poweredOff: return "powered off"
        case .unauthorized: return "permission denied"
        case .unsupported: return "unsupported"
        case .resetting: return "resetting"
        case .unknown: return "unknown"
        case .poweredOn: return "on"
        @unknown default: return "unknown"
        }
    }
}

extension RingBLEClient: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard let pending = powerOnContinuation else { return }
        powerOnContinuation = nil
        if central.state == .poweredOn {
            pending.resume()
        } else {
            pending.resume(throwing: RingBLEError.unavailable(stateDescription))
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        guard let pending = discoveryContinuation else { return }
        discoveryContinuation = nil
        central.stopScan()
        pending.resume(returning: peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([Self.serviceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        guard let pending = connectContinuation else { return }
        connectContinuation = nil
        pending.resume(throwing: error ?? RingBLEError.timeout("connect"))
    }
}

extension RingBLEClient: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let service = peripheral.services?.first(where: { $0.uuid == Self.serviceUUID })
        else {
            failConnect(error ?? RingBLEError.notFound)
            return
        }
        // Discover everything: Ring 5 exposes extra notify characteristics
        // (…0004/0005/0006) that Ring 3 lacks, and some responses arrive on
        // them. Subscribing only to …0003 makes those replies look like
        // timeouts.
        peripheral.discoverCharacteristics(nil, for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        guard let characteristics = service.characteristics else {
            failConnect(error ?? RingBLEError.notFound)
            return
        }
        writeChar = characteristics.first { $0.uuid == Self.writeUUID }
        let subscribable = characteristics.filter {
            guard $0.properties.contains(.notify) || $0.properties.contains(.indicate)
            else { return false }
            // Subscribing to the extra Ring 5 channels (0004/0005/0006) is
            // suspected of putting the ring into a state where it stops
            // servicing ATT requests; primaryOnly restricts us to 0003.
            return subscribePrimaryOnly ? $0.uuid == Self.notifyUUID : true
        }
        pendingSubscriptions = subscribable.count
        for characteristic in subscribable {
            peripheral.setNotifyValue(true, for: characteristic)
        }
        // Do NOT resume yet: setNotifyValue is asynchronous, and writing a
        // request before the subscriptions are live means the reply is never
        // delivered — which looks exactly like a response timeout.
        if subscribable.isEmpty {
            failConnect(RingBLEError.notFound)
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        pendingSubscriptions = max(pendingSubscriptions - 1, 0)
        guard pendingSubscriptions == 0, let pending = connectContinuation else { return }
        connectContinuation = nil
        if writeChar == nil {
            pending.resume(throwing: RingBLEError.notFound)
        } else {
            pending.resume()
        }
    }

    /// Write acknowledgements. A failed write (commonly "Encryption is
    /// insufficient" when the link isn't secured yet) is otherwise invisible
    /// and looks identical to the ring ignoring us.
    func peripheral(
        _ peripheral: CBPeripheral,
        didWriteValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if capturing {
            captureLog.append(
                "write ack \(characteristic.uuid.uuidString.prefix(8)): \(error.map { "ERROR \($0.localizedDescription)" } ?? "ok")"
            )
        }
        guard let error, let pending = responseContinuation else { return }
        responseContinuation = nil
        expectedTag = nil
        pending.resume(throwing: RingBLEError.badResponse("write failed: \(error.localizedDescription)"))
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        let value = characteristic.value ?? Data()
        // Capture before any filtering, so unsolicited pushes are logged too.
        if capturing {
            captureLog.append(
                // These UUIDs differ in their FIRST block; the tail is shared.
                "\(characteristic.uuid.uuidString.prefix(8)) → \(value.prefix(20).hexString)"
            )
        }
        // Accept replies from any subscribed characteristic in the service.
        guard characteristic.uuid != Self.writeUUID,
              let pending = responseContinuation
        else { return }
        // Ignore unrelated pushes; keep waiting for the expected reply.
        if error == nil, let expectedTag, value.first != expectedTag {
            return
        }
        responseContinuation = nil
        expectedTag = nil
        if let error {
            pending.resume(throwing: error)
        } else {
            pending.resume(returning: value)
        }
    }

    private func failConnect(_ error: Error) {
        guard let pending = connectContinuation else { return }
        connectContinuation = nil
        pending.resume(throwing: error)
    }
}
