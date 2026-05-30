package com.crackedoura.mobile.ui

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.absoluteValue
import kotlin.math.roundToInt

private val prettyDateFormatter = DateTimeFormatter.ofPattern("EEE, MMM d, yyyy")
private val compactDateFormatter = DateTimeFormatter.ofPattern("MMM d")
private val monthDateFormatter = DateTimeFormatter.ofPattern("MMM d", Locale.US)
private val prettyDateTimeFormatter = DateTimeFormatter.ofPattern("MMM d, HH:mm")
private val shortTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

fun formatDayLabel(day: String?): String {
    if (day.isNullOrBlank()) return "No data"
    return runCatching {
        LocalDate.parse(day).format(prettyDateFormatter)
    }.getOrDefault(day)
}

fun formatDayShort(day: String?): String {
    if (day.isNullOrBlank()) return "--"
    return runCatching {
        LocalDate.parse(day).format(compactDateFormatter)
    }.getOrDefault(day)
}

fun formatDayMonth(day: String?): String {
    if (day.isNullOrBlank()) return "--"
    return runCatching {
        LocalDate.parse(day).format(monthDateFormatter)
    }.getOrDefault(day)
}

fun formatDateTimeLabel(value: String?): String {
    if (value.isNullOrBlank()) return "--"
    return parseDateTime(value)?.format(prettyDateTimeFormatter) ?: value
}

fun formatTimeOnly(value: String?): String {
    if (value.isNullOrBlank()) return "--:--"
    return parseDateTime(value)?.format(shortTimeFormatter) ?: value
}

fun formatDurationSeconds(seconds: Int?): String {
    if (seconds == null || seconds <= 0) return "--"
    val totalMinutes = seconds / 60
    val hours = totalMinutes / 60
    val minutes = totalMinutes % 60
    return if (hours > 0) "${hours}h ${minutes}m" else "${minutes}m"
}

fun formatDurationHours(seconds: Int?): String {
    if (seconds == null || seconds <= 0) return "--"
    return String.format(Locale.US, "%.1f h", seconds / 3600f)
}

fun formatCompactNumber(value: Int?): String {
    if (value == null) return "--"
    return when {
        value >= 10_000 -> String.format(Locale.US, "%.1fk", value / 1000f)
        value >= 1_000 -> String.format(Locale.US, "%.1fk", value / 1000f)
        else -> value.toString()
    }
}

fun formatSignedDelta(value: Int?, unit: String = ""): String {
    if (value == null) return "--"
    val suffix = unit.takeIf { it.isNotBlank() }?.let { " $it" }.orEmpty()
    return if (value > 0) "+$value$suffix" else "$value$suffix"
}

fun formatSignedDecimal(value: Float?, unit: String = "", decimals: Int = 1): String {
    if (value == null) return "--"
    val pattern = "%.${decimals}f"
    val formatted = String.format(Locale.US, pattern, value.absoluteValue)
    val suffix = unit.takeIf { it.isNotBlank() }?.let { " $it" }.orEmpty()
    return if (value >= 0f) "+$formatted$suffix" else "-$formatted$suffix"
}

fun formatPercent(value: Float?, decimals: Int = 0): String {
    if (value == null) return "--"
    return String.format(Locale.US, "%.${decimals}f%%", value * 100f)
}

fun formatMeters(value: Int?): String {
    if (value == null) return "--"
    return if (value >= 1000) {
        String.format(Locale.US, "%.1f km", value / 1000f)
    } else {
        "$value m"
    }
}

fun formatDateRange(startDay: String?, endDay: String?): String {
    if (startDay.isNullOrBlank() || endDay.isNullOrBlank()) return "--"
    val start = parseDay(startDay) ?: return "$startDay to $endDay"
    val end = parseDay(endDay) ?: return "$startDay to $endDay"
    return "${start.format(monthDateFormatter)} to ${end.format(monthDateFormatter)}"
}

fun parseDay(day: String?): LocalDate? {
    if (day.isNullOrBlank()) return null
    return runCatching { LocalDate.parse(day) }.getOrNull()
}

fun parseDateTime(value: String): LocalDateTime? {
    return runCatching {
        OffsetDateTime.parse(value).toLocalDateTime()
    }.recoverCatching {
        LocalDateTime.parse(value)
    }.recoverCatching {
        Instant.parse(value).atZone(ZoneId.systemDefault()).toLocalDateTime()
    }.getOrNull()
}
