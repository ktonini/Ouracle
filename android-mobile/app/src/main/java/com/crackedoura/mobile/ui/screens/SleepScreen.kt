package com.crackedoura.mobile.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.google.accompanist.swiperefresh.SwipeRefresh
import com.google.accompanist.swiperefresh.SwipeRefreshIndicator
import com.google.accompanist.swiperefresh.rememberSwipeRefreshState
import com.crackedoura.mobile.ui.DailyInsight
import com.crackedoura.mobile.ui.formatDayLabel
import com.crackedoura.mobile.ui.formatDurationSeconds
import com.crackedoura.mobile.ui.formatTimeOnly
import com.crackedoura.mobile.ui.showDayPicker
import kotlinx.coroutines.launch

// Semantic stage colors matching the glassmorphism palette
private val DeepSleepColor = Color(0xFF2041B9)
private val RemSleepColor  = Color(0xFF7B57F6)
private val LightSleepColor = Color(0xFF3966FF)
private val AwakeColor = Color(0xFFFF8B4A)
private val SleepRingColor = Color(0xFF2B6DFF)

@Composable
fun SleepScreen(
    padding: PaddingValues,
    insights: List<DailyInsight>,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    onOpenDayDetail: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val pagerState = rememberPagerState(
        initialPage = (insights.size - 1).coerceAtLeast(0),
    ) { insights.size.coerceAtLeast(1) }

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
                modifier = Modifier.padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                item {
                    HeroCard(
                        eyebrow = "Sleep",
                        title = "No sleep data yet",
                        subtitle = "Sync from desktop in Settings to copy sleep data from your PC.",
                        accent = listOf(DeepSleepColor, SleepRingColor),
                    )
                }
            }
            return@SwipeRefresh
        }

        HorizontalPager(
            state = pagerState,
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) { page ->
            val day = insights[page]
            val sparkValues = insights.subList(0, page + 1).takeLast(30)
                .map { it.totalSleepSeconds?.div(60) }

            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // Day navigation: swipe between days, chevrons, or calendar picker
                item {
                    val availableDays = insights.map { it.day }
                    DayNavigatorBar(
                        label = formatDayLabel(day.day),
                        canPrev = page > 0,
                        canNext = page < insights.size - 1,
                        onPrev = { scope.launch { pagerState.animateScrollToPage(page - 1) } },
                        onNext = { scope.launch { pagerState.animateScrollToPage(page + 1) } },
                        onPickDate = {
                            showDayPicker(context, day.day, availableDays) { picked ->
                                val idx = insights.indexOfFirst { it.day == picked }
                                if (idx >= 0) scope.launch { pagerState.animateScrollToPage(idx) }
                            }
                        },
                    )
                }

                item {
                    HeroCard(
                        eyebrow = "Sleep",
                        title = formatDayLabel(day.day),
                        subtitle = day.summary.sleepRecommendation?.takeIf { it.isNotBlank() }
                            ?: "Total sleep ${formatDurationSeconds(day.totalSleepSeconds)}",
                        accent = listOf(DeepSleepColor, SleepRingColor),
                    )
                }

                // Score ring + bedtime window
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        ScoreRingCard(
                            label = "Sleep Score",
                            score = day.summary.sleepScore,
                            subtitle = sleepQualityLabel(day.summary.sleepScore),
                            ringColor = SleepRingColor,
                            modifier = Modifier.weight(1.1f),
                            ringSize = 96,
                            strokeWidthDp = 10,
                            onClick = { onOpenDayDetail(day.day) },
                        )
                        BedtimeCard(
                            bedtimeStart = day.summary.bedtimeStart,
                            bedtimeEnd = day.summary.bedtimeEnd,
                            modifier = Modifier.weight(1.5f),
                        )
                    }
                }

                // Sleep stages bar
                item {
                    SleepStagesCard(latest = day)
                }

                // Sleep stats
                item {
                    SectionCard(
                        title = "Sleep detail",
                        subtitle = "Tap for the full day breakdown",
                        onClick = { onOpenDayDetail(day.day) },
                    ) {
                        StatRow("Total sleep", formatDurationSeconds(day.totalSleepSeconds))
                        StatRow("Deep sleep", formatDurationSeconds(day.summary.deepSleepDuration))
                        StatRow("REM sleep", formatDurationSeconds(day.summary.remSleepDuration))
                        StatRow("Awake time", formatDurationSeconds(day.summary.awakeTime))
                        StatRow("Nap sleep", formatDurationSeconds(day.summary.napSleepDuration))
                        StatRow("Efficiency", day.summary.sleepEfficiency?.let { "$it%" } ?: "--")
                        StatRow("Sessions", day.summary.sleepSessionCount?.toString() ?: "--")
                        StatRow(
                            "Sleep need estimate",
                            formatDurationSeconds(day.sleepNeedEstimateSeconds),
                        )
                        StatRow("Sleep debt", formatDurationSeconds(day.sleepDebtSeconds))
                    }
                }

                // 30-day sparkline
                item {
                    SectionCard(title = "30-day sleep trend") {
                        TrendSparkline(
                            values = sparkValues,
                            color = SleepRingColor,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun BedtimeCard(
    bedtimeStart: String?,
    bedtimeEnd: String?,
    modifier: Modifier = Modifier,
) {
    SectionCard(title = "Bedtime", modifier = modifier) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "Fell asleep",
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White.copy(alpha = 0.45f),
                )
                Text(
                    text = formatTimeOnly(bedtimeStart),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "Woke up",
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White.copy(alpha = 0.45f),
                )
                Text(
                    text = formatTimeOnly(bedtimeEnd),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )
            }
        }
    }
}

@Composable
private fun SleepStagesCard(latest: DailyInsight) {
    val total = latest.totalSleepSeconds?.takeIf { it > 0 } ?: return
    val deep = latest.summary.deepSleepDuration ?: 0
    val rem = latest.summary.remSleepDuration ?: 0
    val awake = latest.summary.awakeTime ?: 0
    val light = (total - deep - rem - awake).coerceAtLeast(0)

    SectionCard(title = "Sleep stages") {
        // Proportional bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(20.dp)
                .clip(RoundedCornerShape(10.dp)),
        ) {
            if (deep > 0) {
                Box(
                    modifier = Modifier
                        .weight(deep.toFloat())
                        .height(20.dp)
                        .background(DeepSleepColor),
                )
            }
            if (rem > 0) {
                Box(
                    modifier = Modifier
                        .weight(rem.toFloat())
                        .height(20.dp)
                        .background(RemSleepColor),
                )
            }
            if (light > 0) {
                Box(
                    modifier = Modifier
                        .weight(light.toFloat())
                        .height(20.dp)
                        .background(LightSleepColor),
                )
            }
            if (awake > 0) {
                Box(
                    modifier = Modifier
                        .weight(awake.toFloat())
                        .height(20.dp)
                        .background(AwakeColor),
                )
            }
        }

        // Legend
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            StageLegendItem("Deep", DeepSleepColor, formatDurationSeconds(deep))
            StageLegendItem("REM", RemSleepColor, formatDurationSeconds(rem))
            StageLegendItem("Light", LightSleepColor, formatDurationSeconds(light))
            StageLegendItem("Awake", AwakeColor, formatDurationSeconds(awake))
        }
    }
}

@Composable
private fun StageLegendItem(label: String, color: Color, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier = Modifier
                .background(color.copy(alpha = 0.80f), RoundedCornerShape(4.dp))
                .padding(horizontal = 8.dp, vertical = 3.dp),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = Color.White,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            color = Color.White.copy(alpha = 0.60f),
        )
    }
}

private fun sleepQualityLabel(score: Int?): String = when {
    score == null -> "No score"
    score >= 85 -> "Optimal"
    score >= 70 -> "Good"
    score >= 55 -> "Fair"
    else -> "Pay attention"
}
