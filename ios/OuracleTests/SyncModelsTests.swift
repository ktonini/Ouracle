import XCTest
@testable import Ouracle

final class SyncModelsTests: XCTestCase {
    // Shape mirrors an actual /api/mobile/sync response from the server.
    private let fixture = """
    {
      "generated_at": "2026-08-05T05:41:42.445123Z",
      "latest_day": "2026-08-04",
      "window_days": 7,
      "available_start_day": "2026-08-04",
      "days": [
        {
          "day": "2026-08-04",
          "sleep_score": null,
          "sleep_contributors": {"deep_sleep": 90, "efficiency": null},
          "activity_score": 93,
          "steps": 220,
          "stress_high": 0,
          "recovery_high": 0,
          "average_hrv": 55,
          "lowest_heart_rate": 52,
          "temperature_deviation": -0.12,
          "resilience_level": "solid",
          "total_sleep_duration": 27360
        }
      ],
      "workouts": [
        {
          "id": "w-1",
          "day": "2026-08-04",
          "start_time": "2026-08-04T10:00:00",
          "activity": "walking",
          "calories": 120.5
        }
      ],
      "today_insights": {
        "day": "2026-08-04",
        "contributors_sleep": [
          {
            "domain": "sleep", "key": "deep_sleep", "label": "Deep sleep",
            "status": "optimal", "value": 90, "unit": "score",
            "explanation": "Plenty of deep sleep.", "source_path": "sleep.contributors.deep_sleep"
          }
        ],
        "contributors_readiness": [],
        "contributors_activity": [],
        "baselines": [
          {
            "metric": "hrv", "label": "HRV", "unit": "ms",
            "current": 55.0, "baseline_7d": 52.5, "delta_7d": 2.5,
            "direction": "up", "sample_count_7d": 7,
            "sample_count_14d": 14, "sample_count_30d": 30
          }
        ],
        "action_cards": [
          {
            "id": "ac-1", "day": "2026-08-04", "severity": "info",
            "category": "sleep", "title": "Earlier bedtime",
            "reason": "Late nights this week.",
            "recommendation": "Aim for 22:30.",
            "evidence": [
              {"metric": "bedtime_start", "day": "2026-08-04", "source_path": "sleep.bedtime_start"}
            ],
            "dismissible": true
          }
        ],
        "guidance": {
          "day": "2026-08-04",
          "headline": "Solid recovery",
          "body": ["Keep the streak going."],
          "citations": []
        }
      },
      "sync_freshness": {
        "latest_day": "2026-08-04",
        "status": "fresh",
        "message": null,
        "mobile_server_enabled": true,
        "days_behind": 0
      }
    }
    """

    func testDecodesFullSyncPayload() throws {
        let response = try JSONDecoder().decode(
            SyncResponse.self, from: Data(fixture.utf8)
        )
        XCTAssertEqual(response.latestDay, "2026-08-04")
        XCTAssertEqual(response.days.count, 1)

        let day = try XCTUnwrap(response.days.first)
        XCTAssertNil(day.sleepScore)
        XCTAssertEqual(day.activityScore, 93)
        XCTAssertEqual(day.steps, 220)
        XCTAssertEqual(day.sleepContributors?["deep_sleep"], 90)
        XCTAssertEqual(day.resilienceLevel, "solid")

        XCTAssertEqual(response.workouts.first?.calories, 120.5)

        let insights = try XCTUnwrap(response.todayInsights)
        XCTAssertEqual(insights.contributorsSleep.first?.value, 90)
        XCTAssertEqual(insights.baselines.first?.baseline7d, 52.5)
        XCTAssertEqual(insights.actionCards.first?.title, "Earlier bedtime")
        XCTAssertEqual(insights.guidance?.headline, "Solid recovery")
        XCTAssertEqual(response.syncFreshness?.daysBehind, 0)
    }

    func testDecodesMinimalPayload() throws {
        let minimal = """
        {"generated_at": "x", "latest_day": null, "window_days": 7,
         "available_start_day": null, "days": [], "workouts": [],
         "today_insights": null, "sync_freshness": null}
        """
        let response = try JSONDecoder().decode(
            SyncResponse.self, from: Data(minimal.utf8)
        )
        XCTAssertTrue(response.days.isEmpty)
        XCTAssertNil(response.todayInsights)
    }
}

extension SyncModelsTests {
    /// The coverage report is how the app contradicts its own "caught up".
    func testDecodesRingCoverage() throws {
        let json = """
        {"status":"gaps","message":"1 of 10 scored nights have no ring data (1 not worn)",
         "events":275653,"from":"2026-08-05T08:45:38+00:00","to":"2026-08-15T17:08:49+00:00",
         "missing_sessions":["2026-08-12"],"unworn_sessions":["2026-08-15"],
         "unrecoverable_sessions":["2026-08-07"],"largest_gap_hours":22.2,
         "sessions":[{"day":"2026-08-12","start":"2026-08-12T22:00:00+00:00",
                      "end":"2026-08-13T05:00:00+00:00","labels":64,
                      "covered_fraction":0.0,"present_fraction":0.0,
                      "state":"missing","covered":false,"counted":true}]}
        """
        let coverage = try JSONDecoder().decode(RingCoverage.self, from: Data(json.utf8))
        XCTAssertFalse(coverage.isHealthy)
        XCTAssertEqual(coverage.missingSessions, ["2026-08-12"])
        XCTAssertEqual(coverage.unwornSessions, ["2026-08-15"])
        XCTAssertEqual(coverage.unrecoverableSessions, ["2026-08-07"])
        XCTAssertEqual(coverage.largestGapHours, 22.2, accuracy: 0.01)
        XCTAssertEqual(coverage.sessions.first?.state, "missing")
    }

    func testHealthyCoverageReadsAsHealthy() throws {
        let json = """
        {"status":"ok","message":"all 10 scored nights accounted for","events":1,
         "sessions":[],"missing_sessions":[],"unworn_sessions":[],
         "unrecoverable_sessions":[],"largest_gap_hours":0.0}
        """
        let coverage = try JSONDecoder().decode(RingCoverage.self, from: Data(json.utf8))
        XCTAssertTrue(coverage.isHealthy)
    }

    /// A learned model and a set of hand-tuned rules are not the same claim,
    /// and neither is Oura's scoring.
    func testProvenanceDistinguishesTheModelFromTheRules() {
        let model = stagingProvenance("ouracle-model-v1")
        let rules = stagingProvenance("ouracle-local-v1")
        XCTAssertTrue(model.contains("learned"))
        XCTAssertTrue(model.contains("sequence"))
        XCTAssertTrue(rules.contains("fixed rules"))
        XCTAssertNotEqual(model, rules)
        for text in [model, rules] {
            XCTAssertFalse(text.contains("Oura's model"))
        }
    }
}

extension SyncModelsTests {
    /// Both metrics are derived on the server from ring signals; the app must
    /// carry them through, and tolerate a night that has neither.
    func testDecodesBreathingRateAndBloodOxygen() throws {
        let json = """
        {"start":"2026-08-13T12:00:00+00:00","end":"2026-08-13T19:00:00+00:00",
         "heart_rate":[],"movement":[],"temperature":[],"beats":15963,
         "lowest_hr":66,"average_hr":68,"breath_rate":12.1,"spo2_percent":93.1,
         "event_count":8509,"detected_bedtimes":[],"stages":[]}
        """
        let night = try JSONDecoder().decode(RingNight.self, from: Data(json.utf8))
        XCTAssertEqual(night.breathRate ?? 0, 12.1, accuracy: 0.001)
        XCTAssertEqual(night.spo2Percent ?? 0, 93.1, accuracy: 0.001)
    }

    func testANightWithoutThoseMetricsStillDecodes() throws {
        let json = """
        {"start":"2026-08-13T12:00:00+00:00","end":"2026-08-13T19:00:00+00:00",
         "heart_rate":[],"movement":[],"temperature":[],"beats":0,
         "event_count":0,"detected_bedtimes":[],"stages":[]}
        """
        let night = try JSONDecoder().decode(RingNight.self, from: Data(json.utf8))
        XCTAssertNil(night.breathRate)
        XCTAssertNil(night.spo2Percent)
        XCTAssertNil(night.lowestHr)
    }
}

extension SyncModelsTests {
    func testDecodesSaturationCurveAndDesaturations() throws {
        let json = """
        {"start":"2026-08-14T14:00:00+00:00","end":"2026-08-14T18:41:00+00:00",
         "heart_rate":[],"movement":[],"temperature":[],"beats":1,
         "spo2_percent":95.5,"desaturation_index":1.6,"lowest_spo2":92.7,
         "spo2_series":[{"t":"2026-08-14T14:00:00+00:00","value":95.8},
                        {"t":"2026-08-14T14:05:00+00:00","value":95.1}],
         "event_count":1,"detected_bedtimes":[],"stages":[]}
        """
        let night = try JSONDecoder().decode(RingNight.self, from: Data(json.utf8))
        XCTAssertEqual(night.spo2Series.count, 2)
        XCTAssertEqual(night.spo2Series.first?.value ?? 0, 95.8, accuracy: 0.001)
        XCTAssertEqual(night.desaturationIndex ?? 0, 1.6, accuracy: 0.001)
        XCTAssertEqual(night.lowestSpo2 ?? 0, 92.7, accuracy: 0.001)
    }

    /// Nights the ring never ran the oximeter on must decode with the curve
    /// simply absent, not fail.
    func testANightWithoutSaturationDecodes() throws {
        let json = """
        {"start":"2026-08-15T15:23:00+00:00","end":"2026-08-15T22:17:00+00:00",
         "heart_rate":[],"movement":[],"temperature":[],"beats":1,
         "event_count":1,"detected_bedtimes":[],"stages":[]}
        """
        let night = try JSONDecoder().decode(RingNight.self, from: Data(json.utf8))
        XCTAssertTrue(night.spo2Series.isEmpty)
        XCTAssertNil(night.desaturationIndex)
        XCTAssertNil(night.lowestSpo2)
    }
}
