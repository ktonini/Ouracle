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

import CoreBluetooth
import Foundation

struct RingInfo: Equatable {
    var apiVersion: String
    var firmware: String
    var bootloader: String
    var btStack: String
    var macAddress: String
}

enum RingBLEError: LocalizedError {
    case unavailable(String)
    case notFound
    case timeout(String)
    case badResponse(String)

    var errorDescription: String? {
        switch self {
        case .unavailable(let state): return "Bluetooth unavailable (\(state))."
        case .notFound:
            return "Ring not found. Make sure it's worn or charging and the Oura app has connected to it recently."
        case .timeout(let step): return "Timed out during \(step)."
        case .badResponse(let detail): return "Unexpected ring response: \(detail)."
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
