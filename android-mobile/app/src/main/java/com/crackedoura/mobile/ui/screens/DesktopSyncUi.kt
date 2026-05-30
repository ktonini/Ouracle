package com.crackedoura.mobile.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.crackedoura.mobile.data.remote.SyncFreshnessDto
import com.crackedoura.mobile.ui.formatDateTimeLabel

@Composable
fun DesktopRoleBanner(modifier: Modifier = Modifier) {
    SectionCard(
        title = "How this app works",
        modifier = modifier,
        subtitle = "A companion to Cracked Oura on your PC — not a standalone Oura client.",
    ) {
        Text(
            text = "• Your PC signs in to Oura, requests exports, and stores data locally.\n" +
                "• This phone copies that cached data over Wi‑Fi or Tailscale.\n" +
                "• You cannot log in to Oura or request exports from the phone.",
            style = MaterialTheme.typography.bodyMedium,
            color = Color.White.copy(alpha = 0.72f),
        )
    }
}

@Composable
fun SyncFreshnessCard(
    freshness: SyncFreshnessDto?,
    isPhoneSyncing: Boolean,
    modifier: Modifier = Modifier,
) {
    if (freshness == null && !isPhoneSyncing) return

    SectionCard(
        title = "Desktop data status",
        modifier = modifier,
        subtitle = if (isPhoneSyncing) {
            "Copying the latest cache from your PC…"
        } else {
            "Reported by your desktop app after Oura export/ingest."
        },
    ) {
        if (isPhoneSyncing) {
            StatusPill(label = "Phone sync running", tone = Color(0xFF3FA9F5))
        }
        freshness ?: return@SectionCard

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SyncFreshnessPill(freshness)
            freshness.daysBehind?.let { behind ->
                if (behind > 0) {
                    StatusPill(label = "$behind d behind expected", tone = Color(0xFFFFB347))
                }
            }
        }

        freshness.expectedLatestDay?.let {
            DetailMetricRow("Expected through", it)
        }

        freshness.message?.takeIf { it.isNotBlank() }?.let { msg ->
            Text(
                text = msg,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.78f),
            )
        }

        freshness.latestDay?.let {
            DetailMetricRow("Latest day on PC", it)
        }
        freshness.lastIngestAt?.let {
            DetailMetricRow("Last ingest on PC", formatDateTimeLabel(it))
        }
        freshness.lastExportRequestAt?.let {
            DetailMetricRow("Last export requested", formatDateTimeLabel(it))
        }
        freshness.automationStatus?.let { status ->
            DetailMetricRow("Desktop automation", formatAutomationStatus(status))
        }
        freshness.nextRun?.let {
            DetailMetricRow("Next scheduled sync (PC)", formatDateTimeLabel(it))
        }

        if (freshness.automationStatus == "otp_needed" || freshness.automationStatus == "Waiting") {
            Text(
                text = "Complete Oura sign-in on the desktop app (Settings → Connection). " +
                    "Then tap Sync from desktop here.",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFFFFB347),
                fontWeight = FontWeight.Medium,
            )
        } else if (freshness.status == "blocked" || freshness.status == "very_stale") {
            Text(
                text = "Fix sync on the desktop app first, then use Sync from desktop on this phone.",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFFFFB347),
            )
        }
    }
}

@Composable
private fun DetailMetricRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = Color.White.copy(alpha = 0.45f),
        )
        Text(
            text = value,
            style = MaterialTheme.typography.labelMedium,
            color = Color.White.copy(alpha = 0.88f),
            fontWeight = FontWeight.Medium,
        )
    }
}

private fun formatAutomationStatus(status: String): String = when (status) {
    "otp_needed" -> "Waiting for Oura code (desktop)"
    "Waiting" -> "Waiting for Oura code (desktop)"
    "Processing", "Ingesting", "Downloading..." -> "Syncing on desktop"
    "Error" -> "Error on desktop"
    "Idle" -> "Idle"
    else -> status
}

fun contributorStatusLabel(status: String): String = when (status) {
    "optimal" -> "Optimal"
    "good" -> "Good"
    "fair" -> "Fair"
    "pay_attention" -> "Pay attention"
    "missing" -> "No data"
    else -> "Unknown"
}
