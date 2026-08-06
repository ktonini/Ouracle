import XCTest
@testable import Ouracle

final class RingProtocolTests: XCTestCase {
    /// Ring 5 firmware response from the open_oura Ring 5 notes:
    /// API 2.1.0, firmware 2.1.3, bootloader 1.0.1, BT 9.3.41,
    /// MAC 11:22:33:44:55:66 (little-endian in the payload).
    func testParsesRing5FirmwareResponse() throws {
        let hex = "0912020100020103010001090329665544332211"
        let info = try RingBLEClient.parseFirmware(Data(hex: hex))
        XCTAssertEqual(info.apiVersion, "2.1.0")
        XCTAssertEqual(info.firmware, "2.1.3")
        XCTAssertEqual(info.bootloader, "1.0.1")
        XCTAssertEqual(info.btStack, "9.3.41")
        XCTAssertEqual(info.macAddress, "11:22:33:44:55:66")
    }

    /// Ring 3 Horizon response from the protocol cheatsheet — same layout.
    func testParsesRing3FirmwareResponse() throws {
        let hex = "091202000003040301000105000cffeeddccbbaa"
        let info = try RingBLEClient.parseFirmware(Data(hex: hex))
        XCTAssertEqual(info.apiVersion, "2.0.0")
        XCTAssertEqual(info.firmware, "3.4.3")
        XCTAssertEqual(info.macAddress, "AA:BB:CC:DD:EE:FF")
    }

    func testRejectsWrongTag() {
        XCTAssertThrowsError(
            try RingBLEClient.parseFirmware(Data(hex: "2f022f01"))
        )
    }

    func testRejectsShortPayload() {
        XCTAssertThrowsError(
            try RingBLEClient.parseFirmware(Data(hex: "09020201"))
        )
    }
}

extension Data {
    init(hex: String) {
        var bytes: [UInt8] = []
        var index = hex.startIndex
        while index < hex.endIndex,
              let next = hex.index(index, offsetBy: 2, limitedBy: hex.endIndex) {
            bytes.append(UInt8(hex[index..<next], radix: 16) ?? 0)
            index = next
        }
        self.init(bytes)
    }
}
