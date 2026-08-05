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
