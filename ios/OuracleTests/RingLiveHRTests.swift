import XCTest
@testable import Ouracle

final class RingLiveHRTests: XCTestCase {
    /// Captured idle response from open_oura's Ring 3 notes: status 17,
    /// state measuring, but IBI zero — i.e. no usable beat yet.
    func testIdleLatestHeartRateHasNoBpm() {
        let hex = "2f1025020011020000000003000000990c7f"
        let reading = RingBLEClient.parseLatestHeartRate(Data(hex: hex))
        XCTAssertNil(reading.bpm)
        XCTAssertTrue(reading.measuring)  // state byte = 0x02
    }

    /// IBI 1000 ms -> 60 bpm. Header is 9 bytes before feature data.
    func testDecodesBpmFromInterBeatInterval() {
        // 2f <len> 25 02 <result> <status> <state> <counter x2> <ibi LE> …
        let hex = "2f0c250200110200" + "00" + "e803" + "0000"
        let reading = RingBLEClient.parseLatestHeartRate(Data(hex: hex))
        XCTAssertEqual(reading.bpm, 60)
    }

    func testDecodes750msIntervalAs80Bpm() {
        let hex = "2f0c250200110200" + "00" + "ee02" + "0000"
        XCTAssertEqual(RingBLEClient.parseLatestHeartRate(Data(hex: hex)).bpm, 80)
    }

    /// A stale/garbage interval must not surface an absurd heart rate.
    func testRejectsImplausibleRate() {
        let hex = "2f0c250200110200" + "00" + "6400" + "0000"  // 100 ms -> 600 bpm
        XCTAssertNil(RingBLEClient.parseLatestHeartRate(Data(hex: hex)).bpm)
    }

    func testWrongFeatureIsNotDecoded() {
        // Feature 0x04 payload must not be read as daytime HR (0x02).
        let hex = "2f0c250400110200" + "00" + "e803" + "0000"
        XCTAssertNil(RingBLEClient.parseLatestHeartRate(Data(hex: hex)).bpm)
    }

    func testDecodesSpO2AndBpm() throws {
        // data[3] = SpO2 %, data[4] = bpm
        let hex = "2f0e250400110200" + "00" + "000000" + "61" + "40"
        let reading = try RingBLEClient.parseLatestSpO2(Data(hex: hex))
        XCTAssertEqual(reading.spo2Percent, 97)
        XCTAssertEqual(reading.bpm, 64)
    }

    func testLatestRequiresAuth() {
        XCTAssertThrowsError(
            try RingBLEClient.latestPayload(Data(hex: "2f022f01"), feature: 0x02)
        ) { error in
            XCTAssertEqual(error as? RingBLEError, .authFailed)
        }
    }
}

extension RingLiveHRTests {
    /// Feature status: `2f 06 21 <feature> <mode> <status> <state> <sub>`.
    func testFeatureModeOffIsDetected() {
        // Captured "daytime HR off" shape: mode byte 0.
        let hex = "2f06210200000000"
        XCTAssertEqual(RingBLEClient.parseFeatureMode(Data(hex: hex), feature: 0x02), 0)
    }

    func testFeatureModeAutomaticIsDetected() {
        // Captured resting-HR row from the protocol notes: mode 1.
        let hex = "2f06210801000000"
        XCTAssertEqual(RingBLEClient.parseFeatureMode(Data(hex: hex), feature: 0x08), 1)
    }

    func testFeatureModeIgnoresMismatchedFeature() {
        let hex = "2f06210201000000"
        XCTAssertNil(RingBLEClient.parseFeatureMode(Data(hex: hex), feature: 0x04))
    }

    func testExerciseHeartRateDecodesBpmDirectly() throws {
        let hex = "2f0e250300110200" + "00" + "00000000" + "48"
        let reading = try RingBLEClient.parseLatestExerciseHR(Data(hex: hex))
        XCTAssertEqual(reading.bpm, 72)
    }
}
