// Exports Ouracle data into Apple Health:
// - sleep sessions as HKCategorySample sleepAnalysis with stages, rebuilt
//   from the 5-minute phase string
// - nightly HRV (SDNN) and resting heart rate summary samples
//
// Every sample carries HKMetadataKeySyncIdentifier derived from the Oura
// session/day id, so re-exports replace rather than duplicate.

import Foundation
import HealthKit

final class HealthKitExporter {
    static let shared = HealthKitExporter()

    private let store = HKHealthStore()

    private var sleepType: HKCategoryType {
        HKCategoryType(.sleepAnalysis)
    }
    private var hrvType: HKQuantityType {
        HKQuantityType(.heartRateVariabilitySDNN)
    }
    private var restingHRType: HKQuantityType {
        HKQuantityType(.restingHeartRate)
    }

    var isAvailable: Bool {
        HKHealthStore.isHealthDataAvailable()
    }

    func requestAuthorization() async throws {
        try await store.requestAuthorization(
            toShare: [sleepType, hrvType, restingHRType], read: []
        )
    }

    /// Exports one day's sleep sessions + nightly summaries. Idempotent.
    func export(sessions: [SleepSessionDetail], day: DailySummary) async throws {
        var samples: [HKSample] = []

        for session in sessions {
            samples.append(contentsOf: stageSamples(for: session))

            if let end = parse(session.bedtimeEnd) {
                if let hrv = session.averageHrv {
                    samples.append(quantitySample(
                        type: hrvType,
                        value: Double(hrv),
                        unit: .secondUnit(with: .milli),
                        date: end,
                        syncId: "ouracle-hrv-\(session.id)"
                    ))
                }
                if let rhr = session.lowestHeartRate {
                    samples.append(quantitySample(
                        type: restingHRType,
                        value: Double(rhr),
                        unit: HKUnit.count().unitDivided(by: .minute()),
                        date: end,
                        syncId: "ouracle-rhr-\(session.id)"
                    ))
                }
            }
        }

        guard !samples.isEmpty else { return }
        try await store.save(samples)
    }

    // MARK: - Sleep stages

    private func stageSamples(for session: SleepSessionDetail) -> [HKSample] {
        guard
            let start = parse(session.bedtimeStart),
            let phases = session.sleepPhase5Min, !phases.isEmpty
        else { return [] }

        // Collapse consecutive identical phases into one sample each.
        var samples: [HKSample] = []
        var runStart = 0
        let characters = Array(phases)
        for index in 1...characters.count {
            if index == characters.count || characters[index] != characters[runStart] {
                if let stage = SleepStage(phaseCharacter: characters[runStart]) {
                    let sampleStart = start.addingTimeInterval(Double(runStart) * 300)
                    let sampleEnd = start.addingTimeInterval(Double(index) * 300)
                    samples.append(HKCategorySample(
                        type: sleepType,
                        value: stage.healthKitValue.rawValue,
                        start: sampleStart,
                        end: sampleEnd,
                        metadata: [
                            HKMetadataKeySyncIdentifier: "ouracle-sleep-\(session.id)-\(runStart)",
                            HKMetadataKeySyncVersion: 1,
                        ]
                    ))
                }
                runStart = index
            }
        }
        return samples
    }

    private func quantitySample(
        type: HKQuantityType, value: Double, unit: HKUnit,
        date: Date, syncId: String
    ) -> HKQuantitySample {
        HKQuantitySample(
            type: type,
            quantity: HKQuantity(unit: unit, doubleValue: value),
            start: date, end: date,
            metadata: [
                HKMetadataKeySyncIdentifier: syncId,
                HKMetadataKeySyncVersion: 1,
            ]
        )
    }

    private func parse(_ string: String?) -> Date? {
        guard let string else { return nil }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        if let date = iso.date(from: string) { return date }
        let plain = DateFormatter()
        plain.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return plain.date(from: string)
    }
}

extension SleepStage {
    var healthKitValue: HKCategoryValueSleepAnalysis {
        switch self {
        case .deep: return .asleepDeep
        case .light: return .asleepCore
        case .rem: return .asleepREM
        case .awake: return .awake
        }
    }
}
