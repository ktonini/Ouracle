package com.crackedoura.mobile.ui

import android.app.DatePickerDialog
import android.content.Context
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import kotlin.math.abs

/**
 * Returns the available day (yyyy-MM-dd) closest to [target]. Used so a date-picker
 * selection that has no synced data still jumps to the nearest day we actually have,
 * instead of silently doing nothing.
 */
fun nearestAvailableDay(target: String, availableDays: List<String>): String? {
    if (availableDays.isEmpty()) return null
    val targetDate = parseDay(target) ?: return availableDays.last()
    return availableDays.minByOrNull { day ->
        parseDay(day)?.let { abs(ChronoUnit.DAYS.between(it, targetDate)) } ?: Long.MAX_VALUE
    }
}

/**
 * Shows a native date picker constrained to the range of [availableDays], initialised to
 * [currentDay] (falling back to the latest available day). The picked date is snapped to the
 * nearest available day before [onPicked] is invoked, guaranteeing the caller always receives
 * a day that exists in the dataset.
 */
fun showDayPicker(
    context: Context,
    currentDay: String?,
    availableDays: List<String>,
    onPicked: (day: String) -> Unit,
) {
    if (availableDays.isEmpty()) return
    val sorted = availableDays.mapNotNull { parseDay(it) }.sorted()
    val init = parseDay(currentDay) ?: sorted.lastOrNull() ?: LocalDate.now()
    val dialog = DatePickerDialog(
        context,
        { _, year, month, dayOfMonth ->
            val picked = "%04d-%02d-%02d".format(year, month + 1, dayOfMonth)
            val nearest = nearestAvailableDay(picked, availableDays) ?: picked
            onPicked(nearest)
        },
        init.year,
        init.monthValue - 1,
        init.dayOfMonth,
    )
    val zone = ZoneId.systemDefault()
    sorted.firstOrNull()?.let {
        dialog.datePicker.minDate = it.atStartOfDay(zone).toInstant().toEpochMilli()
    }
    sorted.lastOrNull()?.let {
        dialog.datePicker.maxDate = it.atStartOfDay(zone).toInstant().toEpochMilli()
    }
    dialog.show()
}
