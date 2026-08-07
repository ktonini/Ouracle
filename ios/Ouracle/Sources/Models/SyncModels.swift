// Codable models for the Ouracle mobile API.
//
// Ported from the Android client's SyncDtos.kt; field names mirror the
// FastAPI response models in backend/src/api/mobile.py. Explicit CodingKeys
// (rather than a key-decoding strategy) because keys like "baseline_7d"
// round-trip ambiguously through snake-case conversion.

import Foundation

extension Data {
    /// Parses hex text (tolerating spaces/newlines); nil if malformed.
    init?(hexString: String) {
        let clean = hexString.filter { !$0.isWhitespace }
        guard clean.count % 2 == 0 else { return nil }
        var bytes = [UInt8]()
        bytes.reserveCapacity(clean.count / 2)
        var index = clean.startIndex
        while index < clean.endIndex {
            let next = clean.index(index, offsetBy: 2)
            guard let byte = UInt8(clean[index..<next], radix: 16) else { return nil }
            bytes.append(byte)
            index = next
        }
        self.init(bytes)
    }
}

struct ServerStatus: Codable, Equatable {
    let status: String
    let generatedAt: String
    let latestDay: String?
    let defaultWindowDays: Int
    let serverVersion: String

    enum CodingKeys: String, CodingKey {
        case status
        case generatedAt = "generated_at"
        case latestDay = "latest_day"
        case defaultWindowDays = "default_window_days"
        case serverVersion = "server_version"
    }
}

struct RingBatteryStatus: Codable, Equatable {
    let level: Int
    let charging: Bool
    let inCharger: Bool
    let timestamp: String

    enum CodingKeys: String, CodingKey {
        case level, charging, timestamp
        case inCharger = "in_charger"
    }
}

struct SyncResponse: Codable, Equatable {
    let generatedAt: String
    let latestDay: String?
    let windowDays: Int
    let availableStartDay: String?
    let days: [DailySummary]
    let workouts: [Workout]
    let todayInsights: TodayInsights?
    let syncFreshness: SyncFreshness?
    let ringBattery: RingBatteryStatus?

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case latestDay = "latest_day"
        case windowDays = "window_days"
        case availableStartDay = "available_start_day"
        case days
        case workouts
        case todayInsights = "today_insights"
        case syncFreshness = "sync_freshness"
        case ringBattery = "ring_battery"
    }
}

struct ContributorSummary: Codable, Equatable, Identifiable {
    let domain: String
    let key: String
    let label: String
    let status: String
    let value: Int?
    let unit: String
    let explanation: String
    let sourcePath: String

    var id: String { "\(domain).\(key)" }

    enum CodingKeys: String, CodingKey {
        case domain, key, label, status, value, unit, explanation
        case sourcePath = "source_path"
    }
}

struct BaselineDelta: Codable, Equatable, Identifiable {
    let metric: String
    let label: String
    let unit: String
    let current: Double?
    let baseline7d: Double?
    let baseline14d: Double?
    let baseline30d: Double?
    let delta7d: Double?
    let delta14d: Double?
    let delta30d: Double?
    let direction: String?
    let preferred: String?

    var id: String { metric }

    enum CodingKeys: String, CodingKey {
        case metric, label, unit, current, direction, preferred
        case baseline7d = "baseline_7d"
        case baseline14d = "baseline_14d"
        case baseline30d = "baseline_30d"
        case delta7d = "delta_7d"
        case delta14d = "delta_14d"
        case delta30d = "delta_30d"
    }
}

struct ActionEvidence: Codable, Equatable {
    let metric: String
    let day: String?
    let sourcePath: String

    enum CodingKeys: String, CodingKey {
        case metric, day
        case sourcePath = "source_path"
    }
}

struct ActionCard: Codable, Equatable, Identifiable {
    let id: String
    let day: String
    let severity: String
    let category: String
    let title: String
    let reason: String
    let recommendation: String
    let evidence: [ActionEvidence]
    let dismissible: Bool
}

struct DailyGuidance: Codable, Equatable {
    let day: String
    let headline: String
    let body: [String]
}

struct TodayInsights: Codable, Equatable {
    let day: String?
    let contributorsSleep: [ContributorSummary]
    let contributorsReadiness: [ContributorSummary]
    let contributorsActivity: [ContributorSummary]
    let baselines: [BaselineDelta]
    let actionCards: [ActionCard]
    let guidance: DailyGuidance?

    enum CodingKeys: String, CodingKey {
        case day, baselines, guidance
        case contributorsSleep = "contributors_sleep"
        case contributorsReadiness = "contributors_readiness"
        case contributorsActivity = "contributors_activity"
        case actionCards = "action_cards"
    }
}

struct SyncFreshness: Codable, Equatable {
    let latestDay: String?
    let expectedLatestDay: String?
    let lastIngestAt: String?
    let status: String
    let message: String?
    let daysBehind: Int?

    enum CodingKeys: String, CodingKey {
        case status, message
        case latestDay = "latest_day"
        case expectedLatestDay = "expected_latest_day"
        case lastIngestAt = "last_ingest_at"
        case daysBehind = "days_behind"
    }
}

struct Workout: Codable, Equatable, Identifiable {
    let id: String
    let day: String
    let startTime: String?
    let endTime: String?
    let activity: String?
    let calories: Double?
    let distance: Double?
    let intensity: String?
    let label: String?
    let source: String?

    enum CodingKeys: String, CodingKey {
        case id, day, activity, calories, distance, intensity, label, source
        case startTime = "start_time"
        case endTime = "end_time"
    }
}

/// A sampled series as stored from Oura: sample interval in seconds plus
/// values (nulls where the ring had no reading).
struct SampledSeries: Codable, Equatable {
    let interval: Double?
    let items: [Double?]?
    let timestamp: String?
}

struct SleepSessionDetail: Codable, Equatable, Identifiable {
    let id: String
    let day: String
    let type: String?
    let bedtimeStart: String?
    let bedtimeEnd: String?
    let efficiency: Int?
    let latency: Int?
    let totalSleepDuration: Int?
    let deepSleepDuration: Int?
    let remSleepDuration: Int?
    let lightSleepDuration: Int?
    let awakeTime: Int?
    let timeInBed: Int?
    let averageHeartRate: Double?
    let averageHrv: Int?
    let lowestHeartRate: Int?
    let averageBreath: Double?
    let restlessPeriods: Int?
    let sleepPhase5Min: String?
    let hrData: SampledSeries?
    let hrvData: SampledSeries?

    enum CodingKeys: String, CodingKey {
        case id, day, type, efficiency, latency
        case bedtimeStart = "bedtime_start"
        case bedtimeEnd = "bedtime_end"
        case totalSleepDuration = "total_sleep_duration"
        case deepSleepDuration = "deep_sleep_duration"
        case remSleepDuration = "rem_sleep_duration"
        case lightSleepDuration = "light_sleep_duration"
        case awakeTime = "awake_time"
        case timeInBed = "time_in_bed"
        case averageHeartRate = "average_heart_rate"
        case averageHrv = "average_hrv"
        case lowestHeartRate = "lowest_heart_rate"
        case averageBreath = "average_breath"
        case restlessPeriods = "restless_periods"
        case sleepPhase5Min = "sleep_phase_5_min"
        case hrData = "hr_data"
        case hrvData = "hrv_data"
    }
}

struct DailySummary: Codable, Hashable, Identifiable {
    let day: String
    let sleepScore: Int?
    let sleepContributors: [String: Double?]?
    let sleepStatus: String?
    let sleepRecommendation: String?
    let averageSpo2: Double?
    let breathingDisturbanceIndex: Int?
    let activityScore: Int?
    let steps: Int?
    let totalCalories: Int?
    let activeCalories: Int?
    let averageMet: Double?
    let inactivityAlerts: Int?
    let activityContributors: [String: Double?]?
    let readinessScore: Int?
    let readinessContributors: [String: Double?]?
    let temperatureDeviation: Double?
    let temperatureTrendDeviation: Double?
    let stressHigh: Int?
    let recoveryHigh: Int?
    let daySummary: String?
    let resilienceLevel: String?
    let vascularAge: Int?
    let sleepType: String?
    let bedtimeStart: String?
    let bedtimeEnd: String?
    let sleepEfficiency: Int?
    let totalSleepDuration: Int?
    let deepSleepDuration: Int?
    let remSleepDuration: Int?
    let lightSleepDuration: Int?
    let awakeTime: Int?
    let averageHeartRate: Double?
    let averageHrv: Int?
    let lowestHeartRate: Int?
    let timeInBed: Int?
    let napSleepDuration: Int?
    let sleepSessionCount: Int?

    var id: String { day }

    enum CodingKeys: String, CodingKey {
        case day, steps
        case sleepScore = "sleep_score"
        case sleepContributors = "sleep_contributors"
        case sleepStatus = "sleep_status"
        case sleepRecommendation = "sleep_recommendation"
        case averageSpo2 = "average_spo2"
        case breathingDisturbanceIndex = "breathing_disturbance_index"
        case activityScore = "activity_score"
        case totalCalories = "total_calories"
        case activeCalories = "active_calories"
        case averageMet = "average_met"
        case inactivityAlerts = "inactivity_alerts"
        case activityContributors = "activity_contributors"
        case readinessScore = "readiness_score"
        case readinessContributors = "readiness_contributors"
        case temperatureDeviation = "temperature_deviation"
        case temperatureTrendDeviation = "temperature_trend_deviation"
        case stressHigh = "stress_high"
        case recoveryHigh = "recovery_high"
        case daySummary = "day_summary"
        case resilienceLevel = "resilience_level"
        case vascularAge = "vascular_age"
        case sleepType = "sleep_type"
        case bedtimeStart = "bedtime_start"
        case bedtimeEnd = "bedtime_end"
        case sleepEfficiency = "sleep_efficiency"
        case totalSleepDuration = "total_sleep_duration"
        case deepSleepDuration = "deep_sleep_duration"
        case remSleepDuration = "rem_sleep_duration"
        case lightSleepDuration = "light_sleep_duration"
        case awakeTime = "awake_time"
        case averageHeartRate = "average_heart_rate"
        case averageHrv = "average_hrv"
        case lowestHeartRate = "lowest_heart_rate"
        case timeInBed = "time_in_bed"
        case napSleepDuration = "nap_sleep_duration"
        case sleepSessionCount = "sleep_session_count"
    }
}
