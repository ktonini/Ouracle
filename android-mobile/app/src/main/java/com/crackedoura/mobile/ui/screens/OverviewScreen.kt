package com.crackedoura.mobile.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.SwipeRefreshIndicator
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.crackedoura.mobile.ui.ActivityGoalBasis
import com.crackedoura.mobile.ui.DailyInsight
import com.crackedoura.mobile.ui.MainUiState
import com.crackedoura.mobile.ui.formatCompactNumber
import com.crackedoura.mobile.ui.formatDateTimeLabel
import com.crackedoura.mobile.ui.formatDayLabel
import com.crackedoura.mobile.ui.formatDayMonth
import com.crackedoura.mobile.ui.formatDurationHours
import com.crackedoura.mobile.ui.formatDurationSeconds
import com.crackedoura.mobile.ui.formatMeters
import com.crackedoura.mobile.ui.formatPercent
import com.crackedoura.mobile.ui.formatSignedDecimal
import com.crackedoura.mobile.ui.formatSignedDelta
import com.crackedoura.mobile.ui.formatTimeOnly
import com.crackedoura.mobile.ui.showDayPicker
import com.crackedoura.mobile.ui.theme.Coral
import com.crackedoura.mobile.ui.theme.Emerald
import com.crackedoura.mobile.ui.theme.Ocean
import java.time.LocalTime
import kotlinx.coroutines.launch

@Composable
fun OverviewScreen(
    padding: PaddingValues,
    uiState: MainUiState,
    insights: List<DailyInsight>,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    onOpenDayDetail: (String) -> Unit,
    onNavigateToSettings: () -> Unit,
) {
    val hasToken = uiState.settings.token.isNotBlank()
    val hasServer = uiState.settings.localServerUrl.isNotBlank() || uiState.settings.tailscaleServerUrl.isNotBlank()
    val timeline = insights.takeLast(14).reversed()

    val pagerState = rememberPagerState(
        initialPage = (insights.size - 1).coerceAtLeast(0),
    ) { insights.size.coerceAtLeast(1) }
    val scope = rememberCoroutineScope()

    SwipeRefresh(
        state = rememberSwipeRefreshState(isRefreshing),
        onRefresh = onRefresh,
        indicator = { state, trigger ->
            SwipeRefreshIndicator(
                state = state,
                refreshTriggerDistance = trigger,
                backgroundColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary,
            )
        },
    ) {
        if (insights.isEmpty()) {
            LazyColumn(
                modifier = Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            text = getTimeGreeting().uppercase(),
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = "No data synced yet",
                            style = MaterialTheme.typography.headlineMedium,
                            color = Color.White,
                        )
                        Text(
                            text = "Connect to Cracked Oura on your PC, then copy data to this phone.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = 0.45f),
                        )
                    }
                }
                item {
                    DesktopRoleBanner()
                }
                item {
                    SyncFreshnessCard(
                        freshness = uiState.syncFreshness,
                        isPhoneSyncing = uiState.isSyncing,
                    )
                }
                item {
                    SectionCard(
                        title = "Get started",
                        subtitle = "Oura login and export stay on the desktop app.",
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = onNavigateToSettings) { Text("Open Settings") }
                            if (hasServer && hasToken) {
                                Button(
                                    onClick = onRefresh,
                                    enabled = !isRefreshing,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = MaterialTheme.colorScheme.secondary,
                                    ),
                                ) {
                                    Text(if (isRefreshing) "Syncing…" else "Sync from desktop")
                                }
                            }
                        }
                    }
                }
            }
        } else {
            HorizontalPager(
                state = pagerState,
                modifier = Modifier.padding(padding).fillMaxSize(),
            ) { page ->
                val current = insights[page]
                val workouts = current.workouts
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    // Day navigation header
                    item {
                        val context = LocalContext.current
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            // Personalised greeting
                            val userName = uiState.settings.userName.trim()
                            Text(
                                text = if (userName.isNotEmpty()) {
                                    "${getTimeGreeting()}, ${userName.split(" ").first()}."
                                } else {
                                    "${getTimeGreeting()}."
                                },
                                style = MaterialTheme.typography.headlineMedium,
                                fontWeight = FontWeight.Bold,
                                color = Color.White,
                            )
                            // Date navigation row (chevrons + calendar picker)
                            val availableDays = insights.map { it.day }
                            DayNavigatorBar(
                                label = formatDayLabel(current.day),
                                canPrev = page > 0,
                                canNext = page < insights.size - 1,
                                onPrev = { scope.launch { pagerState.animateScrollToPage(page - 1) } },
                                onNext = { scope.launch { pagerState.animateScrollToPage(page + 1) } },
                                onPickDate = {
                                    showDayPicker(context, current.day, availableDays) { day ->
                                        val idx = insights.indexOfFirst { it.day == day }
                                        if (idx >= 0) scope.launch { pagerState.animateScrollToPage(idx) }
                                    }
                                },
                            )
                            // Only show syncing pill — remove the static "N days cached" pill
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                if (uiState.isSyncing) {
                                    StatusPill(label = "Copying from PC…", tone = Color(0xFFFFD166))
                                }
                                SyncFreshnessPill(uiState.syncFreshness)
                            }
                        }
                    }

                    item {
                        SyncFreshnessCard(
                            freshness = uiState.syncFreshness,
                            isPhoneSyncing = uiState.isSyncing,
                        )
                    }

                    // Core scores — vertical list, ring left / info right
                    item {
                        SectionCard(
                            title = "Core Scores",
                            subtitle = "Tap for the full day breakdown",
                            onClick = { onOpenDayDetail(current.day) },
                        ) {
                            Column {
                                ScoreListRow(
                                    label = "Readiness",
                                    score = current.summary.readinessScore,
                                    detail = current.readinessDelta?.let { "${formatSignedDelta(it)} vs 14d avg" }
                                        ?: "Building baseline",
                                    ringColor = Emerald,
                                )
                                HorizontalDivider(color = Color.White.copy(alpha = 0.05f))
                                ScoreListRow(
                                    label = "Sleep",
                                    score = current.summary.sleepScore,
                                    detail = formatDurationSeconds(current.totalSleepSeconds),
                                    ringColor = Ocean,
                                )
                                HorizontalDivider(color = Color.White.copy(alpha = 0.05f))
                                ScoreListRow(
                                    label = "Activity",
                                    score = current.summary.activityScore,
                                    detail = current.summary.steps?.let { "${formatCompactNumber(it)} steps" }
                                        ?: "No step data",
                                    ringColor = Coral,
                                )
                            }
                        }
                    }

                    // Daily Insight (prefer deterministic backend guidance when available for this day)
                    item {
                        val backendGuidance = uiState.todayInsights
                            ?.takeIf { it.day == current.day }
                            ?.guidance
                        if (backendGuidance != null) {
                            GuidanceCard(backendGuidance)
                        } else {
                            val insight = buildDailyInsight(current)
                            SectionCard(title = "Daily Insight") {
                                Text(
                                    text = insight,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Color.White.copy(alpha = 0.80f),
                                )
                            }
                        }
                    }

                    // Backend action cards and contributor breakdowns (only for the day matching the sync payload)
                    val matchedInsights = uiState.todayInsights?.takeIf { it.day == current.day }
                    if (matchedInsights != null) {
                        item { ActionCardsList(matchedInsights.actionCards) }
                        item { ContributorList("Sleep contributors", matchedInsights.contributorsSleep) }
                        item { ContributorList("Readiness contributors", matchedInsights.contributorsReadiness) }
                        item { ContributorList("Activity contributors", matchedInsights.contributorsActivity) }
                    }

                    // At a glance — 2×2 grid, no outer card
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Text(
                                text = "AT A GLANCE",
                                style = MaterialTheme.typography.labelLarge,
                                color = Color.White.copy(alpha = 0.35f),
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                BriefingTile(
                                    title = "Sleep debt",
                                    value = formatDurationHours(current.sleepDebtSeconds),
                                    caption = current.sleepNeedEstimateSeconds
                                        ?.let { "Need est. ${formatDurationHours(it)}" }
                                        ?: "Needs 5 sleep nights",
                                    accent = Color(0xFF6B5BFF),
                                    modifier = Modifier.weight(1f),
                                    onClick = { onOpenDayDetail(current.day) },
                                )
                                BriefingTile(
                                    title = "Activity goal",
                                    value = current.activityGoalProgress?.let { formatPercent(it) } ?: "--",
                                    caption = current.activityGoalLabel(),
                                    accent = Color(0xFFFF8B4A),
                                    modifier = Modifier.weight(1f),
                                    onClick = { onOpenDayDetail(current.day) },
                                )
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                BriefingTile(
                                    title = "HRV vs 14d",
                                    value = formatSignedDelta(current.hrvDelta, "ms"),
                                    caption = current.hrvBaseline?.let { "Baseline ${it.toInt()} ms" }
                                        ?: "Building baseline",
                                    accent = Color(0xFF19B394),
                                    modifier = Modifier.weight(1f),
                                    onClick = { onOpenDayDetail(current.day) },
                                )
                                BriefingTile(
                                    title = "Recovery share",
                                    value = current.recoveryShare?.let { formatPercent(it) } ?: "--",
                                    caption = current.summary.recoveryHigh?.let { r ->
                                        "Recovery $r min vs stress ${current.summary.stressHigh ?: 0} min"
                                    } ?: "--",
                                    accent = Color(0xFFD75A71),
                                    modifier = Modifier.weight(1f),
                                    onClick = { onOpenDayDetail(current.day) },
                                )
                            }
                        }
                    }

                    // Timeline strip
                    item {
                        SectionCard(title = "Recent 14 Days") {
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                items(timeline, key = { it.day }) { insight ->
                                    TimelineDayCard(
                                        insight = insight,
                                        onClick = { onOpenDayDetail(insight.day) },
                                    )
                                }
                            }
                        }
                    }

                    // Workouts
                    item {
                        SectionCard(title = "Workouts · ${formatDayMonth(current.day)}") {
                            if (workouts.isEmpty()) {
                                Text(
                                    text = "No workouts synced for this day.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Color.White.copy(alpha = 0.45f),
                                )
                            } else {
                                workouts.forEach { workout ->
                                    WorkoutSummaryRow(
                                        title = workout.label
                                            ?: workout.activity?.replaceFirstChar { it.uppercase() }
                                            ?: "Workout",
                                        subtitle = "${formatTimeOnly(workout.startTime)} · ${workout.intensity ?: "Unknown intensity"}",
                                        trailing = workout.calories?.toInt()?.let { "$it kcal" } ?: "Tracked",
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun BriefingTile(
    title: String,
    value: String,
    caption: String,
    accent: Color,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    Card(
        modifier = modifier
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        shape = RoundedCornerShape(22.dp),
        colors = CardDefaults.cardColors(containerColor = accent.copy(alpha = 0.10f)),
        border = BorderStroke(1.dp, accent.copy(alpha = 0.20f)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.labelLarge,
                color = accent,
            )
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = Color.White,
            )
            Text(
                text = caption,
                style = MaterialTheme.typography.bodySmall,
                color = Color.White.copy(alpha = 0.4f),
            )
        }
    }
}

@Composable
private fun TimelineDayCard(
    insight: DailyInsight,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .width(120.dp)
            .semantics { contentDescription = "Day ${formatDayMonth(insight.day)}, tap to view details" }
            .background(
                color = Color.White.copy(alpha = 0.04f),
                shape = RoundedCornerShape(20.dp),
            )
            .clickable(onClick = onClick)
            .padding(12.dp),
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = formatDayMonth(insight.day),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = Color.White.copy(alpha = 0.8f),
            )
            TimelineMiniMetric("Sleep", insight.summary.sleepScore, Color(0xFF1479FF))
            TimelineMiniMetric("Ready", insight.summary.readinessScore, Color(0xFF19B394))
            TimelineMiniMetric("Steps", insight.summary.steps?.let { formatCompactNumber(it) }, Color(0xFFFF8B4A))
        }
    }
}

@Composable
private fun TimelineMiniMetric(
    label: String,
    value: Any?,
    color: Color,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, CircleShape),
        )
        Text(
            text = "$label ${value ?: "--"}",
            style = MaterialTheme.typography.bodySmall,
            color = Color.White.copy(alpha = 0.6f),
        )
    }
}

@Composable
private fun WorkoutSummaryRow(
    title: String,
    subtitle: String,
    trailing: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        androidx.compose.foundation.layout.Column(
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            text = trailing,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

private fun DailyInsight.activityGoalLabel(): String {
    return when (activityGoalBasis) {
        ActivityGoalBasis.Calories -> {
            val remaining = activityGoalRemaining?.let { "$it kcal left" } ?: "--"
            val target = activityGoalTarget?.let { "Target $it kcal" } ?: remaining
            "$target · $remaining"
        }

        ActivityGoalBasis.Distance -> {
            val target = activityGoalTarget?.let { formatMeters(it) } ?: "distance target"
            val remaining = activityGoalRemaining?.let { "${formatMeters(it)} left" } ?: "--"
            "Target $target · $remaining"
        }

        null -> "No target set"
    }
}

private fun getTimeGreeting(): String {
    val hour = LocalTime.now().hour
    return when {
        hour < 12 -> "Good morning"
        hour < 18 -> "Good afternoon"
        else -> "Good evening"
    }
}

/** Programmatic template engine that produces a 1–2 sentence daily insight from the day's data. */
private fun buildDailyInsight(insight: DailyInsight): String {
    val parts = mutableListOf<String>()

    // Readiness lead
    val readiness = insight.summary.readinessScore
    if (readiness != null) {
        parts += when {
            readiness >= 85 -> "You're in great shape today — readiness is high, so it's a good day to push hard."
            readiness >= 70 -> "Your body is reasonably recovered; moderate training is well-supported."
            readiness >= 55 -> "Readiness is below average — consider keeping today's effort light."
            else -> "Your body needs rest today; readiness is low, so prioritise recovery."
        }
    }

    // Sleep quality add-on
    val sleepScore = insight.summary.sleepScore
    if (sleepScore != null) {
        parts += when {
            sleepScore >= 85 -> "Last night's sleep was excellent — you should feel sharp and energised."
            sleepScore >= 70 -> "Sleep was solid. A short afternoon rest could top you up further."
            sleepScore >= 55 -> "Sleep quality was average; hydration and a walk can help offset any fatigue."
            else -> "Sleep was poor last night — avoid caffeine after noon and aim for an early bedtime."
        }
    }

    // HRV callout
    val delta = insight.hrvDelta
    if (delta != null && readiness == null) {
        parts += if (delta >= 5) {
            "HRV is trending up — your autonomic system is recovering well."
        } else if (delta <= -5) {
            "HRV dipped vs your baseline; stress, alcohol, or accumulated fatigue may be factors."
        } else {
            "HRV is close to your baseline — you're in a stable recovery state."
        }
    }

    return parts.take(2).joinToString(" ").ifBlank { "Sync more days to unlock personalised insights." }
}
