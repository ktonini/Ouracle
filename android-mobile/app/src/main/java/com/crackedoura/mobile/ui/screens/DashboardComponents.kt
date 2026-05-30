package com.crackedoura.mobile.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.ChevronLeft
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun HeroCard(
    eyebrow: String,
    title: String,
    subtitle: String = "",
    modifier: Modifier = Modifier,
    accent: List<Color> = listOf(
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.secondary,
    ),
    content: @Composable (() -> Unit)? = null,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(28.dp),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
    ) {
        Box(
            modifier = Modifier
                .background(
                    brush = Brush.linearGradient(accent),
                    shape = RoundedCornerShape(28.dp),
                )
                .padding(20.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    text = eyebrow.uppercase(),
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White.copy(alpha = 0.72f),
                )
                Text(
                    text = title,
                    style = MaterialTheme.typography.headlineSmall,
                    color = Color.White,
                )
                if (subtitle.isNotBlank()) {
                    Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = 0.84f),
                    )
                }
                if (content != null) {
                    content()
                }
            }
        }
    }
}

@Composable
fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    onClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = Color.White.copy(alpha = 0.06f),
        ),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = MaterialTheme.typography.titleLarge, color = Color.White)
                if (subtitle != null) {
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.45f),
                    )
                }
            }
            content()
        }
    }
}

@Composable
fun StatusPill(
    label: String,
    tone: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .background(
                color = tone.copy(alpha = 0.12f),
                shape = RoundedCornerShape(999.dp),
            )
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            modifier = Modifier
                .background(tone, CircleShape)
                .size(8.dp),
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = tone,
        )
    }
}

@Composable
fun MetricCard(
    title: String,
    value: String,
    subtitle: String,
    accentColor: Color,
    progress: Float? = null,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.06f)),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    title,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Box(
                    modifier = Modifier
                        .background(accentColor.copy(alpha = 0.18f), CircleShape)
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                ) {
                    Text(
                        text = "Live",
                        style = MaterialTheme.typography.labelLarge,
                        color = accentColor,
                    )
                }
            }
            Text(
                value,
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Black,
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (progress != null) {
                LinearProgressIndicator(
                    progress = { progress.coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth(),
                    color = accentColor,
                    trackColor = accentColor.copy(alpha = 0.12f),
                )
            }
        }
    }
}

@Composable
fun StatRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = Color.White.copy(alpha = 0.50f),
        )
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = Color.White,
        )
    }
}

@Composable
fun TrendSparkline(values: List<Int?>, color: Color, modifier: Modifier = Modifier) {
    if (values.isEmpty()) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .height(88.dp)
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(18.dp)),
        )
        return
    }

    val normalized = values.mapNotNull { it?.toFloat() }
    val min = normalized.minOrNull() ?: 0f
    val max = normalized.maxOrNull() ?: 100f
    val range = (max - min).takeIf { it > 0f } ?: 1f

    Canvas(
        modifier = modifier
            .fillMaxWidth()
            .height(88.dp),
    ) {
        val points = values.mapIndexedNotNull { index, value ->
            value?.let {
                val x = if (values.size == 1) 0f else size.width * index / (values.size - 1)
                val normalizedY = 1f - ((it - min) / range)
                Offset(x, normalizedY * size.height)
            }
        }

        val fillPath = Path()
        val strokePath = Path()

        points.forEachIndexed { index, offset ->
            if (index == 0) {
                strokePath.moveTo(offset.x, offset.y)
                fillPath.moveTo(offset.x, size.height)
                fillPath.lineTo(offset.x, offset.y)
            } else {
                strokePath.lineTo(offset.x, offset.y)
                fillPath.lineTo(offset.x, offset.y)
            }
        }

        if (points.isNotEmpty()) {
            fillPath.lineTo(points.last().x, size.height)
            fillPath.close()
        }

        drawPath(
            path = fillPath,
            brush = Brush.verticalGradient(
                colors = listOf(color.copy(alpha = 0.25f), Color.Transparent),
            ),
        )
        drawPath(
            path = strokePath,
            color = color,
            style = Stroke(width = 5f),
        )
    }
}

@Composable
fun EmptyStateCard(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
) {
    SectionCard(
        title = title,
        modifier = modifier,
        subtitle = body,
    ) {}
}

/**
 * A glass-card with a circular arc score ring (canvas-drawn) and a label underneath.
 * Matches the "Cracked Oura" desktop score ring aesthetic.
 */
/**
 * Horizontal score-ring row matching the glassmorphism mockup:
 * [Ring 72dp] [Label / Detail text]
 * Used inside a SectionCard for the "Core Scores" list.
 */
@Composable
fun ScoreListRow(
    label: String,
    score: Int?,
    detail: String,
    ringColor: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp, vertical = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(18.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Circular ring — larger hero size with glow
        Box(
            modifier = Modifier.size(88.dp),
            contentAlignment = Alignment.Center,
        ) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                // Glow layer — soft radial bleed behind the ring
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(ringColor.copy(alpha = 0.22f), Color.Transparent),
                        center = Offset(size.width / 2f, size.height / 2f),
                        radius = size.width * 0.52f,
                    ),
                    radius = size.width * 0.52f,
                )
                val strokePx = 9.dp.toPx()
                val inset = strokePx / 2f
                val arcSize = Size(size.width - strokePx, size.height - strokePx)
                // Track arc
                drawArc(
                    color = ringColor.copy(alpha = 0.15f),
                    startAngle = 135f, sweepAngle = 270f, useCenter = false,
                    style = Stroke(width = strokePx, cap = StrokeCap.Round),
                    topLeft = Offset(inset, inset), size = arcSize,
                )
                // Progress arc
                val progress = (score ?: 0).coerceIn(0, 100) / 100f
                if (progress > 0f) {
                    drawArc(
                        color = ringColor,
                        startAngle = 135f, sweepAngle = 270f * progress, useCenter = false,
                        style = Stroke(width = strokePx, cap = StrokeCap.Round),
                        topLeft = Offset(inset, inset), size = arcSize,
                    )
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = score?.toString() ?: "--",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Black,
                    color = Color.White,
                )
                Text(
                    text = scoreQualityLabel(score),
                    style = MaterialTheme.typography.labelSmall,
                    color = ringColor,
                )
            }
        }
        // Info
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = label,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color.White.copy(alpha = 0.90f),
            )
            Text(
                text = detail,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.45f),
            )
        }
    }
}

private fun scoreQualityLabel(score: Int?): String = when {
    score == null -> ""
    score >= 85 -> "Optimal"
    score >= 70 -> "Good"
    score >= 60 -> "Fair"
    else -> "Low"
}

/**
 * Shared day-navigation row: previous-day chevron, centred date label (with year),
 * a calendar button to jump to a date, and a next-day chevron. Used by the Today,
 * Sleep and Trends screens so day navigation behaves consistently everywhere.
 */
@Composable
fun DayNavigatorBar(
    label: String,
    canPrev: Boolean,
    canNext: Boolean,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onPickDate: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onPrev, enabled = canPrev) {
            Icon(
                imageVector = Icons.Outlined.ChevronLeft,
                contentDescription = "Previous day",
                tint = if (canPrev) Color.White.copy(0.7f) else Color.White.copy(0.2f),
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = Color.White.copy(alpha = 0.75f),
            textAlign = TextAlign.Center,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onPickDate) {
            Icon(
                imageVector = Icons.Outlined.CalendarMonth,
                contentDescription = "Pick date",
                tint = Color.White.copy(alpha = 0.6f),
            )
        }
        IconButton(onClick = onNext, enabled = canNext) {
            Icon(
                imageVector = Icons.Outlined.ChevronRight,
                contentDescription = "Next day",
                tint = if (canNext) Color.White.copy(0.7f) else Color.White.copy(0.2f),
            )
        }
    }
}

@Composable
fun ScoreRingCard(
    label: String,
    score: Int?,
    subtitle: String,
    ringColor: Color,
    modifier: Modifier = Modifier,
    ringSize: Int = 84,
    strokeWidthDp: Int = 9,
    onClick: (() -> Unit)? = null,
) {
    Card(
        modifier = modifier
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = Color.White.copy(alpha = 0.06f),
        ),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(
                modifier = Modifier.size(ringSize.dp),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val strokePx = strokeWidthDp.dp.toPx()
                    val inset = strokePx / 2f
                    val arcSize = Size(size.width - strokePx, size.height - strokePx)
                    val startAngle = 135f
                    val sweepAngle = 270f

                    // Track arc
                    drawArc(
                        color = ringColor.copy(alpha = 0.18f),
                        startAngle = startAngle,
                        sweepAngle = sweepAngle,
                        useCenter = false,
                        style = Stroke(width = strokePx, cap = StrokeCap.Round),
                        topLeft = Offset(inset, inset),
                        size = arcSize,
                    )

                    // Progress arc
                    val progress = (score ?: 0).coerceIn(0, 100) / 100f
                    if (progress > 0f) {
                        drawArc(
                            color = ringColor,
                            startAngle = startAngle,
                            sweepAngle = sweepAngle * progress,
                            useCenter = false,
                            style = Stroke(width = strokePx, cap = StrokeCap.Round),
                            topLeft = Offset(inset, inset),
                            size = arcSize,
                        )
                    }
                }
                Text(
                    text = score?.toString() ?: "--",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Black,
                    color = Color.White,
                )
            }

            Text(
                text = label,
                style = MaterialTheme.typography.labelLarge,
                color = ringColor,
                textAlign = TextAlign.Center,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.45f),
                textAlign = TextAlign.Center,
            )
        }
    }
}
