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

@MainActor
final class RingRadioAccessTests: XCTestCase {
    /// The ring's auth handshake is a stateful challenge, so two overlapping
    /// conversations leave one waiting for a nonce the other consumed —
    /// which is what "Timed out during auth nonce" was. Operations must queue.
    func testExclusiveAccessNeverOverlaps() async {
        var active = 0
        var maxActive = 0

        await withTaskGroup(of: Void.self) { group in
            for _ in 0 ..< 8 {
                group.addTask { @MainActor in
                    await RingBLEClient.exclusive {
                        active += 1
                        maxActive = max(maxActive, active)
                        // Suspend inside the critical section: without a lock
                        // this is exactly where the next caller would barge in.
                        try? await Task.sleep(nanoseconds: 1_000_000)
                        active -= 1
                    }
                }
            }
        }

        XCTAssertEqual(maxActive, 1)
        XCTAssertEqual(active, 0)
    }

    func testExclusiveAccessReleasesAfterAThrow() async {
        struct Boom: Error {}
        do {
            try await RingBLEClient.exclusive { throw Boom() }
            XCTFail("should have rethrown")
        } catch {
            // A failed operation must not wedge the radio for everyone else.
        }
        let ran = await RingBLEClient.exclusive { true }
        XCTAssertTrue(ran)
    }
}

final class RingCursorTests: XCTestCase {
    private func events(_ stamps: [UInt32]) -> [RingBLEClient.RawRingEvent] {
        stamps.map { .init(tag: 0x60, timestamp: $0, body: Data()) }
    }

    func testCursorAdvancesPastTheBatch() {
        let next = RingBLEClient.nextCursor(after: 1000, events: events([1000, 1200, 1100]))
        XCTAssertEqual(next, 1201)
    }

    /// Regression: the ring records while we're connected, so a batch can carry
    /// an event stamped with the current clock. Taking the maximum let one of
    /// those leap the cursor over 4.6 days of history that was never re-read.
    func testLiveEventDoesNotLeapTheCursor() {
        let now: UInt32 = 7_343_695          // "right now" on the ring's clock
        let history: [UInt32] = [2_655_604, 2_655_605, 2_655_700]
        let next = RingBLEClient.nextCursor(after: 2_655_600, events: events(history + [now]))
        XCTAssertEqual(next, 2_655_701, "must resume just after the history, not after the live event")
    }

    /// A real gap in the ring's history must still be crossed, or the drain
    /// would stall forever at the edge of a day it wasn't worn.
    func testGenuineGapStillAdvances() {
        let start: UInt32 = 1000
        let afterGap: UInt32 = 1000 + 48 * 60 * 60 * 10   // two days later
        let next = RingBLEClient.nextCursor(after: start, events: events([afterGap]))
        XCTAssertEqual(next, afterGap + 1)
    }

    func testEmptyBatchLeavesTheCursorAlone() {
        XCTAssertEqual(RingBLEClient.nextCursor(after: 1000, events: []), 1000)
    }
}
