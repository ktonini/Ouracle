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

    var errorDescription: String? {
        switch self {
        case .unavailable(let state): return "Bluetooth unavailable (\(state))."
        case .notFound:
            return "Ring not found. Make sure it's worn or charging and the Oura app has connected to it recently."
        case .timeout(let step): return "Timed out during \(step)."
        case .badResponse(let detail): return "Unexpected ring response: \(detail)."
        case .noAuthKey: return "No ring auth key set. Add it in Settings."
        case .authFailed: return "Ring rejected the auth key."
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
        let response = try await send(Data([0x08, 0x03, 0x00, 0x00, 0x00]))
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
        let response = try await send(Data([0x0C, 0x00]))
        return try Self.parseBattery(response)
    }

    /// Streams heart-rate readings for `seconds`, polling the ring's latest
    /// cached measurement over a single authenticated connection.
    ///
    /// Note this is a poll, not a push: the ring measures on its own schedule,
    /// so readings repeat until it takes a new one. Values only appear while
    /// the ring is worn.
    func streamHeartRate(
        seconds: TimeInterval = 60,
        pollInterval: TimeInterval = 2
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

                    let deadline = Date().addingTimeInterval(seconds)
                    while Date() < deadline, !Task.isCancelled {
                        // 0x2f/0x24 feature-latest, feature 0x02 = daytime HR.
                        let hr = try await send(Data([0x2F, 0x02, 0x24, 0x02]))
                        var reading = Self.parseLatestHeartRate(hr)

                        // SpO2 (feature 0x04) also carries a bpm sample.
                        if let spo2 = try? await send(Data([0x2F, 0x02, 0x24, 0x04])),
                           let parsed = try? Self.parseLatestSpO2(spo2)
                        {
                            reading.spo2Percent = parsed.spo2Percent
                            if reading.bpm == nil { reading.bpm = parsed.bpm }
                        }

                        continuation.yield(reading)
                        try await Task.sleep(nanoseconds: UInt64(pollInterval * 1_000_000_000))
                    }
                    disconnect()
                    continuation.finish()
                } catch {
                    disconnect()
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    /// App auth is session-scoped: nonce challenge, AES-ECB encrypted with
    /// the ring's key, sent back for verification.
    private func authenticate(key: Data) async throws {
        let nonceResponse = try await send(Data([0x2F, 0x01, 0x2B]))
        let nonce = try Self.parseNonce(nonceResponse)
        let encrypted = try Self.aesECBEncrypt(nonce, key: key)

        var request = Data([0x2F, UInt8(encrypted.count + 1), 0x2D])
        request.append(encrypted)
        let result = try await send(request)

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

    private func send(_ packet: Data) async throws -> Data {
        guard let peripheral, let writeChar else {
            throw RingBLEError.timeout("characteristic discovery")
        }
        return try await withCheckedThrowingContinuation { continuation in
            responseContinuation = continuation
            peripheral.writeValue(packet, for: writeChar, type: .withoutResponse)
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in
                guard let self, let pending = self.responseContinuation else { return }
                self.responseContinuation = nil
                pending.resume(throwing: RingBLEError.timeout("response"))
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
        peripheral.discoverCharacteristics([Self.writeUUID, Self.notifyUUID], for: service)
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
        if let notify = characteristics.first(where: { $0.uuid == Self.notifyUUID }) {
            peripheral.setNotifyValue(true, for: notify)
        }
        // Ready once both directions exist; notify subscription confirms below.
        if writeChar != nil, let pending = connectContinuation {
            connectContinuation = nil
            pending.resume()
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        guard characteristic.uuid == Self.notifyUUID,
              let pending = responseContinuation
        else { return }
        responseContinuation = nil
        if let error {
            pending.resume(throwing: error)
        } else {
            pending.resume(returning: characteristic.value ?? Data())
        }
    }

    private func failConnect(_ error: Error) {
        guard let pending = connectContinuation else { return }
        connectContinuation = nil
        pending.resume(throwing: error)
    }
}
