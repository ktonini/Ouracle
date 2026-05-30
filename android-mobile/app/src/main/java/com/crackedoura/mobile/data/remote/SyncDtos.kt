package com.crackedoura.mobile.data.remote

import com.crackedoura.mobile.data.local.DailySummaryEntity
import com.crackedoura.mobile.data.local.WorkoutEntity
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class MobileServerStatusDto(
    val status: String,
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("latest_day") val latestDay: String? = null,
    @SerialName("default_window_days") val defaultWindowDays: Int,
    @SerialName("server_version") val serverVersion: String,
)

@Serializable
data class MobileSyncResponseDto(
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("latest_day") val latestDay: String? = null,
    @SerialName("window_days") val windowDays: Int,
    @SerialName("available_start_day") val availableStartDay: String? = null,
    val days: List<DailySummaryDto> = emptyList(),
    val workouts: List<WorkoutDto> = emptyList(),
    @SerialName("today_insights") val todayInsights: TodayInsightsDto? = null,
    @SerialName("sync_freshness") val syncFreshness: SyncFreshnessDto? = null,
)

@Serializable
data class ContributorSummaryDto(
    val domain: String,
    val key: String,
    val label: String,
    val status: String,
    val value: Int? = null,
    val unit: String,
    val explanation: String,
    @SerialName("source_path") val sourcePath: String,
)

@Serializable
data class BaselineDeltaDto(
    val metric: String,
    val label: String,
    val unit: String,
    val current: Float? = null,
    @SerialName("baseline_7d") val baseline7d: Float? = null,
    @SerialName("baseline_14d") val baseline14d: Float? = null,
    @SerialName("baseline_30d") val baseline30d: Float? = null,
    @SerialName("delta_7d") val delta7d: Float? = null,
    @SerialName("delta_14d") val delta14d: Float? = null,
    @SerialName("delta_30d") val delta30d: Float? = null,
    val direction: String? = null,
    @SerialName("sample_count_7d") val sampleCount7d: Int = 0,
    @SerialName("sample_count_14d") val sampleCount14d: Int = 0,
    @SerialName("sample_count_30d") val sampleCount30d: Int = 0,
    val preferred: String? = null,
)

@Serializable
data class ActionEvidenceDto(
    val metric: String,
    val day: String? = null,
    @SerialName("source_path") val sourcePath: String,
)

@Serializable
data class ActionCardDto(
    val id: String,
    val day: String,
    val severity: String,
    val category: String,
    val title: String,
    val reason: String,
    val recommendation: String,
    val evidence: List<ActionEvidenceDto> = emptyList(),
    val dismissible: Boolean = true,
)

@Serializable
data class DailyGuidanceDto(
    val day: String,
    val headline: String,
    val body: List<String> = emptyList(),
)

@Serializable
data class TodayInsightsDto(
    val day: String? = null,
    @SerialName("contributors_sleep") val contributorsSleep: List<ContributorSummaryDto> = emptyList(),
    @SerialName("contributors_readiness") val contributorsReadiness: List<ContributorSummaryDto> = emptyList(),
    @SerialName("contributors_activity") val contributorsActivity: List<ContributorSummaryDto> = emptyList(),
    val baselines: List<BaselineDeltaDto> = emptyList(),
    @SerialName("action_cards") val actionCards: List<ActionCardDto> = emptyList(),
    val guidance: DailyGuidanceDto? = null,
)

@Serializable
data class SyncFreshnessDto(
    @SerialName("latest_day") val latestDay: String? = null,
    @SerialName("expected_latest_day") val expectedLatestDay: String? = null,
    @SerialName("last_ingest_at") val lastIngestAt: String? = null,
    @SerialName("last_export_request_at") val lastExportRequestAt: String? = null,
    val status: String,
    val message: String? = null,
    @SerialName("mobile_server_enabled") val mobileServerEnabled: Boolean = false,
    @SerialName("mobile_server_status") val mobileServerStatus: String? = null,
    @SerialName("automation_status") val automationStatus: String? = null,
    @SerialName("next_run") val nextRun: String? = null,
    @SerialName("days_behind") val daysBehind: Int? = null,
)

@Serializable
data class DailySummaryDto(
    val day: String,
    @SerialName("sleep_score") val sleepScore: Int? = null,
    @SerialName("sleep_contributors") val sleepContributors: JsonObject? = null,
    @SerialName("sleep_status") val sleepStatus: String? = null,
    @SerialName("sleep_recommendation") val sleepRecommendation: String? = null,
    @SerialName("average_spo2") val averageSpo2: Float? = null,
    @SerialName("breathing_disturbance_index") val breathingDisturbanceIndex: Int? = null,
    @SerialName("activity_score") val activityScore: Int? = null,
    val steps: Int? = null,
    @SerialName("total_calories") val totalCalories: Int? = null,
    @SerialName("active_calories") val activeCalories: Int? = null,
    @SerialName("average_met") val averageMet: Float? = null,
    @SerialName("equivalent_walking_distance") val equivalentWalkingDistance: Int? = null,
    @SerialName("target_calories") val targetCalories: Int? = null,
    @SerialName("target_meters") val targetMeters: Int? = null,
    @SerialName("meters_to_target") val metersToTarget: Int? = null,
    @SerialName("inactivity_alerts") val inactivityAlerts: Int? = null,
    @SerialName("resting_time") val restingTime: Int? = null,
    @SerialName("sedentary_time") val sedentaryTime: Int? = null,
    @SerialName("low_activity_time") val lowActivityTime: Int? = null,
    @SerialName("medium_activity_time") val mediumActivityTime: Int? = null,
    @SerialName("high_activity_time") val highActivityTime: Int? = null,
    @SerialName("activity_contributors") val activityContributors: JsonObject? = null,
    @SerialName("readiness_score") val readinessScore: Int? = null,
    @SerialName("readiness_contributors") val readinessContributors: JsonObject? = null,
    @SerialName("temperature_deviation") val temperatureDeviation: Float? = null,
    @SerialName("temperature_trend_deviation") val temperatureTrendDeviation: Float? = null,
    @SerialName("stress_high") val stressHigh: Int? = null,
    @SerialName("recovery_high") val recoveryHigh: Int? = null,
    @SerialName("day_summary") val daySummary: String? = null,
    @SerialName("resilience_level") val resilienceLevel: String? = null,
    @SerialName("resilience_sleep_recovery") val resilienceSleepRecovery: Float? = null,
    @SerialName("resilience_daytime_recovery") val resilienceDaytimeRecovery: Float? = null,
    @SerialName("resilience_stress") val resilienceStress: Float? = null,
    @SerialName("vascular_age") val vascularAge: Int? = null,
    @SerialName("sleep_type") val sleepType: String? = null,
    @SerialName("sleep_start_time") val sleepStartTime: String? = null,
    @SerialName("sleep_end_time") val sleepEndTime: String? = null,
    @SerialName("bedtime_start") val bedtimeStart: String? = null,
    @SerialName("bedtime_end") val bedtimeEnd: String? = null,
    @SerialName("sleep_efficiency") val sleepEfficiency: Int? = null,
    @SerialName("total_sleep_duration") val totalSleepDuration: Int? = null,
    @SerialName("deep_sleep_duration") val deepSleepDuration: Int? = null,
    @SerialName("rem_sleep_duration") val remSleepDuration: Int? = null,
    @SerialName("light_sleep_duration") val lightSleepDuration: Int? = null,
    @SerialName("awake_time") val awakeTime: Int? = null,
    @SerialName("average_heart_rate") val averageHeartRate: Float? = null,
    @SerialName("average_hrv") val averageHrv: Int? = null,
    @SerialName("lowest_heart_rate") val lowestHeartRate: Int? = null,
    @SerialName("readiness_score_delta") val readinessScoreDelta: Float? = null,
    @SerialName("sleep_score_delta") val sleepScoreDelta: Int? = null,
    @SerialName("time_in_bed") val timeInBed: Int? = null,
    @SerialName("total_sleep_duration_all_sessions") val totalSleepDurationAllSessions: Int? = null,
    @SerialName("nap_sleep_duration") val napSleepDuration: Int? = null,
    @SerialName("sleep_session_count") val sleepSessionCount: Int? = null,
)

@Serializable
data class WorkoutDto(
    val id: String,
    val day: String,
    @SerialName("start_time") val startTime: String? = null,
    @SerialName("end_time") val endTime: String? = null,
    val activity: String? = null,
    val calories: Float? = null,
    val distance: Float? = null,
    val intensity: String? = null,
    val label: String? = null,
    val source: String? = null,
)

fun DailySummaryDto.toEntity(): DailySummaryEntity {
    return DailySummaryEntity(
        day = day,
        sleepScore = sleepScore,
        sleepContributorsJson = sleepContributors?.toString(),
        sleepStatus = sleepStatus,
        sleepRecommendation = sleepRecommendation,
        averageSpo2 = averageSpo2,
        breathingDisturbanceIndex = breathingDisturbanceIndex,
        activityScore = activityScore,
        steps = steps,
        totalCalories = totalCalories,
        activeCalories = activeCalories,
        averageMet = averageMet,
        equivalentWalkingDistance = equivalentWalkingDistance,
        targetCalories = targetCalories,
        targetMeters = targetMeters,
        metersToTarget = metersToTarget,
        inactivityAlerts = inactivityAlerts,
        restingTime = restingTime,
        sedentaryTime = sedentaryTime,
        lowActivityTime = lowActivityTime,
        mediumActivityTime = mediumActivityTime,
        highActivityTime = highActivityTime,
        activityContributorsJson = activityContributors?.toString(),
        readinessScore = readinessScore,
        readinessContributorsJson = readinessContributors?.toString(),
        temperatureDeviation = temperatureDeviation,
        temperatureTrendDeviation = temperatureTrendDeviation,
        stressHigh = stressHigh,
        recoveryHigh = recoveryHigh,
        readinessDaySummary = daySummary,
        resilienceLevel = resilienceLevel,
        resilienceSleepRecovery = resilienceSleepRecovery,
        resilienceDaytimeRecovery = resilienceDaytimeRecovery,
        resilienceStress = resilienceStress,
        vascularAge = vascularAge,
        sleepType = sleepType,
        sleepStartTime = sleepStartTime,
        sleepEndTime = sleepEndTime,
        bedtimeStart = bedtimeStart,
        bedtimeEnd = bedtimeEnd,
        sleepEfficiency = sleepEfficiency,
        totalSleepDuration = totalSleepDuration,
        deepSleepDuration = deepSleepDuration,
        remSleepDuration = remSleepDuration,
        lightSleepDuration = lightSleepDuration,
        awakeTime = awakeTime,
        averageHeartRate = averageHeartRate,
        averageHrv = averageHrv,
        lowestHeartRate = lowestHeartRate,
        readinessScoreDelta = readinessScoreDelta,
        sleepScoreDelta = sleepScoreDelta,
        timeInBed = timeInBed,
        totalSleepDurationAllSessions = totalSleepDurationAllSessions,
        napSleepDuration = napSleepDuration,
        sleepSessionCount = sleepSessionCount,
    )
}

fun WorkoutDto.toEntity(): WorkoutEntity {
    return WorkoutEntity(
        id = id,
        day = day,
        startTime = startTime,
        endTime = endTime,
        activity = activity,
        calories = calories,
        distance = distance,
        intensity = intensity,
        label = label,
        source = source,
    )
}
