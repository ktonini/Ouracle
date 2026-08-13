import XCTest
@testable import Ouracle

final class RingHistoryTests: XCTestCase {
    private func ingest(_ hex: String, into batch: inout RingBLEClient.EventBatch) {
        RingBLEClient.ingest(Data(hex: hex), into: &batch)
    }

    /// History frames: tag ≥ 0x41, then a little-endian deciseconds timestamp.
    func testParsesHistoryEventFrame() {
        var batch = RingBLEClient.EventBatch()
        // tag 0x55, len 0x06, ts = 0x000003e8 (1000), body aabb
        ingest("5506e8030000aabb", into: &batch)
        XCTAssertEqual(batch.events.count, 1)
        XCTAssertEqual(batch.events[0].tag, 0x55)
        XCTAssertEqual(batch.events[0].timestamp, 1000)
        XCTAssertEqual(batch.events[0].body.hexString, "aabb")
    }

    /// Summary tag 0x11: events_received, sleep_analysis_progress, bytes_left.
    /// Vector from open_oura's tests: 8 events, 3742 bytes left.
    func testParsesBatchSummary() {
        var batch = RingBLEClient.EventBatch()
        ingest("11060800" + "9e0e0000", into: &batch)
        XCTAssertTrue(batch.sawSummary)
        XCTAssertEqual(batch.bytesLeft, 3742)
    }

    func testSummaryEndsBatchWithoutAddingAnEvent() {
        var batch = RingBLEClient.EventBatch()
        ingest("5506e8030000aabb", into: &batch)
        ingest("1106080000000000", into: &batch)
        XCTAssertEqual(batch.events.count, 1)
        XCTAssertTrue(batch.sawSummary)
        XCTAssertEqual(batch.bytesLeft, 0)  // drained
    }

    /// Command responses (tag < 0x41) must never be mistaken for events.
    func testIgnoresCommandResponses() {
        var batch = RingBLEClient.EventBatch()
        ingest("0d065a00000000", into: &batch)   // battery
        ingest("2f022e00", into: &batch)         // auth ok
        XCTAssertTrue(batch.events.isEmpty)
        XCTAssertFalse(batch.sawSummary)
    }

    func testIgnoresTruncatedFrames() {
        var batch = RingBLEClient.EventBatch()
        ingest("5502e803", into: &batch)  // timestamp cut short
        ingest("1102ff", into: &batch)    // summary too short
        XCTAssertTrue(batch.events.isEmpty)
        XCTAssertFalse(batch.sawSummary)
    }

    func testEventWithEmptyBodyIsKept() {
        var batch = RingBLEClient.EventBatch()
        ingest("4104d2040000", into: &batch)  // ts 1234, no body
        XCTAssertEqual(batch.events.count, 1)
        XCTAssertEqual(batch.events[0].timestamp, 1234)
        XCTAssertTrue(batch.events[0].body.isEmpty)
    }

    /// Regression: the ring packs several events into one notification. The
    /// length byte delimits them; ignoring it glued every event after the
    /// first onto the first one's body, so they vanished. 242 stored rows
    /// turned out to be whole runs of events hidden inside a single record.
    func testSplitsSeveralEventsInOnePacket() {
        var batch = RingBLEClient.EventBatch()
        // Two 18-byte frames back to back, as captured from the ring:
        // 0x60 (IBI) then 0x81 (raw PPG), each ts + 14 bytes of body.
        ingest(
            "6012" + "a27d1500" + "696a6a6b7072c8c3bfa3aec04a31"
                + "8112" + "a37d1500" + "02161d211f0f0e09020101038112",
            into: &batch
        )
        XCTAssertEqual(batch.events.count, 2)
        XCTAssertEqual(batch.events.map(\.tag), [0x60, 0x81])
        XCTAssertEqual(batch.events[0].timestamp, 0x00157DA2)
        XCTAssertEqual(batch.events[1].timestamp, 0x00157DA3)
        XCTAssertEqual(batch.events[0].body.hexString, "696a6a6b7072c8c3bfa3aec04a31")
        XCTAssertEqual(batch.events[0].body.count, 14)
        XCTAssertEqual(batch.events[1].body.count, 14)
    }

    /// A packet cut mid-event must drop the fragment, not store it as a whole
    /// event with a short body — that is how bad data becomes plausible data.
    func testStopsAtATruncatedTrailingFrame() {
        var batch = RingBLEClient.EventBatch()
        ingest("5506e8030000aabb" + "6012a27d1500" + "6969", into: &batch)
        XCTAssertEqual(batch.events.count, 1)
        XCTAssertEqual(batch.events[0].tag, 0x55)
    }

    func testSummaryAfterEventsInTheSamePacketKeepsBoth() {
        var batch = RingBLEClient.EventBatch()
        ingest("5506e8030000aabb" + "11060800" + "9e0e0000", into: &batch)
        XCTAssertEqual(batch.events.count, 1)
        XCTAssertTrue(batch.sawSummary)
        XCTAssertEqual(batch.bytesLeft, 3742)
    }

    func testCollectsMultipleEventsInOrder() {
        var batch = RingBLEClient.EventBatch()
        ingest("4104d2040000", into: &batch)
        ingest("5506e8030000aabb", into: &batch)
        ingest("6b04ff000000", into: &batch)
        XCTAssertEqual(batch.events.map(\.tag), [0x41, 0x55, 0x6B])
        XCTAssertEqual(batch.events.map(\.timestamp).max(), 1234)
    }
}

extension RingHistoryTests {
    /// Regression: UInt8(-14) traps, so western time zones crashed the app
    /// as soon as history sync sent the ring's clock-sync command.
    func testTimezoneByteHandlesWesternOffsets() {
        // PDT, UTC-7 -> -14 half hours -> 0xf2 two's complement.
        XCTAssertEqual(RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: -25200), 0xF2)
        // PST, UTC-8 -> -16 -> 0xf0
        XCTAssertEqual(RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: -28800), 0xF0)
    }

    func testTimezoneByteHandlesUTCAndEast() {
        XCTAssertEqual(RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: 0), 0)
        // CEST, UTC+2 -> 4
        XCTAssertEqual(RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: 7200), 4)
        // India, UTC+5:30 -> 11 (half-hour zone)
        XCTAssertEqual(RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: 19800), 11)
    }

    func testTimezoneByteClampsAbsurdOffsets() {
        // Must never trap, whatever the system reports.
        _ = RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: Int.min / 2)
        _ = RingBLEClient.timezoneHalfHoursByte(secondsFromGMT: Int.max / 2)
    }
}
