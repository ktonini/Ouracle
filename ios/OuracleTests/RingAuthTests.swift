import XCTest
@testable import Ouracle

final class RingAuthTests: XCTestCase {
    func testParsesNonceChallenge() throws {
        // Ring 5 nonce response from open_oura's notes.
        let hex = "2f102c490a55be3b8169e3f24aa279f1e55a"
        let nonce = try RingBLEClient.parseNonce(Data(hex: hex))
        XCTAssertEqual(nonce.count, 15)
        XCTAssertEqual(nonce.first, 0x49)
        XCTAssertEqual(nonce.last, 0x5a)
    }

    func testRejectsMalformedNonce() {
        XCTAssertThrowsError(try RingBLEClient.parseNonce(Data(hex: "2f022f01")))
        // Right shape, wrong length.
        XCTAssertThrowsError(try RingBLEClient.parseNonce(Data(hex: "2f102c0102")))
    }

    /// AES-128-ECB/PKCS7 against a NIST FIPS-197 vector: a 16-byte block
    /// encrypts to a known ciphertext (first block; padding adds a second).
    func testAesEcbMatchesKnownVector() throws {
        let key = Data(hex: "000102030405060708090a0b0c0d0e0f")
        let plaintext = Data(hex: "00112233445566778899aabbccddeeff")
        let out = try RingBLEClient.aesECBEncrypt(plaintext, key: key)
        XCTAssertEqual(
            out.prefix(16).map { String(format: "%02x", $0) }.joined(),
            "69c4e0d86a7b0430d8cdb78070b4c55a"
        )
    }

    /// The ring sends a 15-byte nonce; PKCS7 pads it to exactly one block.
    func testFifteenByteNonceEncryptsToSingleBlock() throws {
        let key = Data(hex: "4431967d8bacc2659743142b68391d9a")
        let nonce = Data(hex: "490a55be3b8169e3f24aa279f1e55a")
        XCTAssertEqual(nonce.count, 15)
        let out = try RingBLEClient.aesECBEncrypt(nonce, key: key)
        XCTAssertEqual(out.count, 16)
    }

    func testParsesBatteryResponse() throws {
        // 0d <len> <percent> <charging progress> …
        let battery = try RingBLEClient.parseBattery(Data(hex: "0d065a00000000"))
        XCTAssertEqual(battery.percent, 90)
        XCTAssertFalse(battery.charging)

        let charging = try RingBLEClient.parseBattery(Data(hex: "0d061b2c000000"))
        XCTAssertEqual(charging.percent, 27)
        XCTAssertTrue(charging.charging)
    }

    func testBatteryBeforeAuthSurfacesAuthError() {
        // Ring replies 2f022f01 when a key is installed but not authed.
        XCTAssertThrowsError(
            try RingBLEClient.parseBattery(Data(hex: "2f022f01"))
        ) { error in
            XCTAssertEqual(error as? RingBLEError, .authFailed)
        }
    }
}

extension RingBLEError: Equatable {
    public static func == (lhs: RingBLEError, rhs: RingBLEError) -> Bool {
        String(describing: lhs) == String(describing: rhs)
    }
}
