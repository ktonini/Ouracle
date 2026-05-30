package com.crackedoura.mobile.data.repository

import androidx.room.withTransaction
import com.crackedoura.mobile.data.local.AppDatabase
import com.crackedoura.mobile.data.local.DailySummaryEntity
import com.crackedoura.mobile.data.local.InsightsEntity
import com.crackedoura.mobile.data.local.OuraDao
import com.crackedoura.mobile.data.local.SyncStateEntity
import com.crackedoura.mobile.data.local.WorkoutEntity
import com.crackedoura.mobile.data.remote.AnomalyResponseDto
import com.crackedoura.mobile.data.remote.CorrelationResponseDto
import com.crackedoura.mobile.data.remote.InvestigationCreateDto
import com.crackedoura.mobile.data.remote.MetricSpecDto
import com.crackedoura.mobile.data.remote.MobileApiService
import com.crackedoura.mobile.data.remote.MobileSyncResponseDto
import com.crackedoura.mobile.data.remote.SavedInvestigationDto
import com.crackedoura.mobile.data.remote.SyncFreshnessDto
import com.crackedoura.mobile.data.remote.TodayInsightsDto
import com.crackedoura.mobile.data.remote.toEntity
import kotlinx.serialization.json.JsonObject
import com.crackedoura.mobile.util.AppLogger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

class SyncFailureException(
    message: String,
    val reason: SyncFailureReason? = null,
) : IllegalStateException(message)

class OuraRepository(
    private val database: AppDatabase,
    private val dao: OuraDao,
    private val apiService: MobileApiService,
    private val preferencesRepository: SyncPreferencesRepository,
) {
    private companion object {
        const val TAG = "Repository"
    }

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    private val todayInsightsState = MutableStateFlow<TodayInsightsDto?>(null)
    private val syncFreshnessState = MutableStateFlow<SyncFreshnessDto?>(null)

    fun observeTodayInsights(): StateFlow<TodayInsightsDto?> = todayInsightsState.asStateFlow()
    fun observeSyncFreshness(): StateFlow<SyncFreshnessDto?> = syncFreshnessState.asStateFlow()

    fun observeInsightsForDay(day: String): Flow<TodayInsightsDto?> =
        dao.observeInsightsForDay(day).map { entity ->
            entity?.let { decodeInsightsOrNull(it.payloadJson) }
        }

    suspend fun loadPersistedState() {
        val state = runCatching { dao.getSyncState() }.getOrNull() ?: return
        state.freshnessJson?.let { freshnessJson ->
            decodeFreshnessOrNull(freshnessJson)?.let { syncFreshnessState.value = it }
        }
        val latestDay = state.latestInsightsDay ?: return
        val insightsEntity = runCatching { dao.getInsightsForDay(latestDay) }.getOrNull() ?: return
        decodeInsightsOrNull(insightsEntity.payloadJson)?.let { todayInsightsState.value = it }
    }

    suspend fun ensureInsightsFor(day: String): Result<Unit> {
        val cached = runCatching { dao.getInsightsForDay(day) }.getOrNull()
        if (cached != null) return Result.success(Unit)
        return fetchInsightsFor(day)
    }

    suspend fun fetchInsightsFor(day: String): Result<Unit> {
        val settings = try {
            preferencesRepository.currentSettings()
        } catch (t: CancellationException) {
            throw t
        } catch (t: Throwable) {
            return Result.failure(t)
        }
        if (settings.token.isBlank()) {
            return Result.failure(IllegalStateException("Missing sync token."))
        }
        val candidates = try {
            candidatesInOrder(settings)
        } catch (t: CancellationException) {
            throw t
        } catch (t: Throwable) {
            return Result.failure(t)
        }
        if (candidates.isEmpty()) return Result.failure(IllegalStateException("No server configured."))

        var lastError: Throwable? = null
        for (candidate in candidates) {
            try {
                val validated = SyncConfigValidator.validatedConfigForSave(candidate, settings.token, settings.windowDays)
                val payload = apiService.insightsForDay(
                    url = "${validated.serverUrl}/api/mobile/insights/$day",
                    token = validated.token,
                )
                persistInsights(day, payload, updateLatest = false)
                return Result.success(Unit)
            } catch (t: CancellationException) {
                throw t
            } catch (t: Throwable) {
                AppLogger.w(TAG, "Per-day insights fetch failed url=$candidate day=$day", t)
                lastError = t
            }
        }
        return Result.failure(lastError ?: IllegalStateException("Insights fetch failed."))
    }

    private fun decodeInsightsOrNull(payload: String): TodayInsightsDto? = try {
        json.decodeFromString(TodayInsightsDto.serializer(), payload)
    } catch (t: Throwable) {
        AppLogger.w(TAG, "Failed to decode persisted insights", t)
        null
    }

    private fun decodeFreshnessOrNull(payload: String): SyncFreshnessDto? = try {
        json.decodeFromString(SyncFreshnessDto.serializer(), payload)
    } catch (t: Throwable) {
        AppLogger.w(TAG, "Failed to decode persisted freshness", t)
        null
    }

    private suspend fun persistInsights(
        day: String,
        payload: TodayInsightsDto,
        updateLatest: Boolean,
    ) {
        val encoded = json.encodeToString(TodayInsightsDto.serializer(), payload)
        val now = java.time.Instant.now().toString()
        dao.upsertInsights(InsightsEntity(day = day, payloadJson = encoded, fetchedAt = now))
        if (updateLatest) {
            val existing = dao.getSyncState()
            dao.upsertSyncState(
                SyncStateEntity(
                    id = 1,
                    freshnessJson = existing?.freshnessJson,
                    latestInsightsDay = day,
                ),
            )
        }
    }

    private suspend fun persistFreshness(freshness: SyncFreshnessDto?) {
        val encoded = freshness?.let { json.encodeToString(SyncFreshnessDto.serializer(), it) }
        val existing = dao.getSyncState()
        dao.upsertSyncState(
            SyncStateEntity(
                id = 1,
                freshnessJson = encoded,
                latestInsightsDay = existing?.latestInsightsDay,
            ),
        )
    }

    fun observeSettings(): Flow<SyncSettings> = preferencesRepository.settings

    fun observeLatestSummary(): Flow<DailySummaryEntity?> = dao.observeLatestSummary()

    fun observeRecentSummaries(limit: Int): Flow<List<DailySummaryEntity>> =
        dao.observeRecentSummaries(limit)

    fun observeRecentWorkouts(limit: Int): Flow<List<WorkoutEntity>> =
        dao.observeRecentWorkouts(limit)

    suspend fun saveDarkMode(enabled: Boolean?) {
        preferencesRepository.saveDarkMode(enabled)
    }

    suspend fun saveUserName(name: String) {
        preferencesRepository.saveUserName(name)
    }

    suspend fun saveSyncSettings(
        localServerUrl: String,
        tailscaleServerUrl: String,
        preferredNetwork: String,
        token: String,
        windowDays: Int,
    ) {
        preferencesRepository.saveSettings(localServerUrl, tailscaleServerUrl, preferredNetwork, token, windowDays)
        AppLogger.i(TAG, "Settings saved windowDays=$windowDays")
    }

    suspend fun saveBackgroundSyncInterval(hours: Int) {
        preferencesRepository.saveBackgroundSyncInterval(hours)
        AppLogger.i(TAG, "Background sync interval saved hours=$hours")
    }

    suspend fun recordBackgroundResult(errorMessage: String?) {
        val currentHours = preferencesRepository.currentSettings().backgroundSyncIntervalHours
        val nextRun = if (currentHours > 0) {
            java.time.Instant.now()
                .plus(currentHours.toLong(), java.time.temporal.ChronoUnit.HOURS)
                .toString()
        } else null
        preferencesRepository.recordBackgroundRun(
            timestamp = java.time.Instant.now().toString(),
            error = errorMessage,
            nextRunAt = nextRun,
        )
    }

    suspend fun recordNextBackgroundRun(nextRunAt: String?) {
        preferencesRepository.recordNextBackgroundRun(nextRunAt)
    }

    private suspend fun candidatesInOrder(settings: SyncSettings): List<String> {
        val raw = when (settings.preferredNetwork) {
            "local" -> listOfNotNull(settings.localServerUrl.takeIf { it.isNotBlank() })
            "tailscale" -> listOfNotNull(settings.tailscaleServerUrl.takeIf { it.isNotBlank() })
            else -> listOfNotNull(
                settings.localServerUrl.takeIf { it.isNotBlank() },
                settings.tailscaleServerUrl.takeIf { it.isNotBlank() },
            )
        }
        if (raw.size <= 1 || settings.token.isBlank()) return raw

        val probes = ServerReachabilityDetector.probeAll(raw, settings.token)
        val reachable = probes.filter { it.reachable }.map { it.url }
        val unreachable = raw.filter { url -> reachable.none { it == url } }
        return reachable + unreachable
    }

    // ── Phase 2: Analysis ─────────────────────────────────────────────────────

    /** Call [block] against the first reachable server URL in priority order. */
    private suspend fun <T> withFirstServer(block: suspend (serverUrl: String, token: String) -> T): Result<T> {
        val settings = try {
            preferencesRepository.currentSettings()
        } catch (t: CancellationException) { throw t } catch (t: Throwable) { return Result.failure(t) }
        if (settings.token.isBlank()) return Result.failure(IllegalStateException("Missing sync token."))
        val candidates = when (settings.preferredNetwork) {
            "local" -> listOfNotNull(settings.localServerUrl.takeIf { it.isNotBlank() })
            "tailscale" -> listOfNotNull(settings.tailscaleServerUrl.takeIf { it.isNotBlank() })
            else -> listOfNotNull(
                settings.localServerUrl.takeIf { it.isNotBlank() },
                settings.tailscaleServerUrl.takeIf { it.isNotBlank() },
            )
        }
        if (candidates.isEmpty()) return Result.failure(IllegalStateException("No server configured."))
        var lastError: Throwable? = null
        for (serverUrl in candidates) {
            try { return Result.success(block(serverUrl, settings.token)) }
            catch (t: CancellationException) { throw t }
            catch (t: Throwable) { lastError = t }
        }
        return Result.failure(lastError ?: IllegalStateException("Request failed"))
    }

    suspend fun fetchCatalog(): Result<List<MetricSpecDto>> =
        withFirstServer { url, token -> apiService.getAnalysisCatalog("$url/api/analysis/catalog", token) }

    suspend fun runCorrelation(
        xMetric: String, yMetric: String, lagDays: Int, method: String, startDate: String, endDate: String,
    ): Result<CorrelationResponseDto> = withFirstServer { url, token ->
        apiService.getCorrelation("$url/api/analysis/correlate", token, xMetric, yMetric, lagDays, method, startDate, endDate)
    }

    suspend fun fetchAnomalies(day: String, windowDays: Int = 14): Result<List<AnomalyResponseDto>> =
        withFirstServer { url, token -> apiService.getAnomalies("$url/api/analysis/anomalies/$day", token, windowDays, 28) }

    suspend fun listInvestigations(): Result<List<SavedInvestigationDto>> =
        withFirstServer { url, token -> apiService.listInvestigations("$url/api/investigations", token) }

    suspend fun createInvestigation(name: String, kind: String, payload: JsonObject?): Result<SavedInvestigationDto> =
        withFirstServer { url, token ->
            apiService.createInvestigation("$url/api/investigations", token, InvestigationCreateDto(name, kind, payload))
        }

    suspend fun deleteInvestigation(id: String): Result<Unit> =
        withFirstServer { url, token -> apiService.deleteInvestigation("$url/api/investigations/$id", token) }

    // ── Sync ──────────────────────────────────────────────────────────────────

    suspend fun syncNow(): Result<Unit> {
        val settings = try {
            preferencesRepository.currentSettings()
        } catch (t: CancellationException) {
            throw t
        } catch (t: Throwable) {
            val reason = SyncFailureReason.Unknown(null, "Could not read sync settings: ${t.message ?: t::class.java.simpleName}")
            return fail(reason)
        }

        if (settings.token.isBlank()) {
            return fail(SyncFailureReason.MissingToken("Paste the sync token from the desktop app in Settings."))
        }

        val candidates = try {
            candidatesInOrder(settings)
        } catch (t: CancellationException) {
            throw t
        } catch (t: Throwable) {
            AppLogger.w(TAG, "Reachability probe threw, falling back to raw candidate order", t)
            when (settings.preferredNetwork) {
                "local" -> listOfNotNull(settings.localServerUrl.takeIf { it.isNotBlank() })
                "tailscale" -> listOfNotNull(settings.tailscaleServerUrl.takeIf { it.isNotBlank() })
                else -> listOfNotNull(
                    settings.localServerUrl.takeIf { it.isNotBlank() },
                    settings.tailscaleServerUrl.takeIf { it.isNotBlank() },
                )
            }
        }
        if (candidates.isEmpty()) {
            return fail(SyncFailureReason.NoServerConfigured(noServerMessage(settings.preferredNetwork)))
        }

        AppLogger.i(TAG, "Sync starting candidates=${candidates.joinToString()} windowDays=${settings.windowDays}")

        val perUrlFailures = mutableListOf<Pair<String, SyncFailureReason>>()
        for ((index, candidate) in candidates.withIndex()) {
            AppLogger.i(TAG, "Sync attempt ${index + 1}/${candidates.size} url=$candidate")
            try {
                val response = attemptSync(candidate, settings)
                preferencesRepository.recordSyncSuccess(response.generatedAt)
                preferencesRepository.recordSuccessfulUrl(candidate)
                AppLogger.i(TAG, "Sync succeeded url=$candidate")
                return Result.success(Unit)
            } catch (t: CancellationException) {
                AppLogger.i(TAG, "Sync cancelled url=$candidate")
                throw t
            } catch (t: Throwable) {
                val reason = SyncFailureDiagnoser.classify(t, candidate)
                AppLogger.w(TAG, "Sync attempt failed url=$candidate reason=${reason::class.java.simpleName}: ${reason.userMessage}", t)
                perUrlFailures += candidate to reason
                if (reason.isTerminal()) break
            }
        }

        val combined = if (perUrlFailures.size == 1) perUrlFailures.first().second
        else SyncFailureReason.AllCandidatesFailed(perUrlFailures.toList())
        return fail(combined)
    }

    private suspend fun attemptSync(url: String, settings: SyncSettings): MobileSyncResponseDto {
        val validated = SyncConfigValidator.validatedConfigForSave(url, settings.token, settings.windowDays)
        apiService.ping("${validated.serverUrl}/api/mobile/ping", validated.token)
        val response = apiService.sync(
            url = "${validated.serverUrl}/api/mobile/sync",
            token = validated.token,
            windowDays = validated.windowDays,
        )
        val summaries = response.days.map { it.toEntity() }
        val workouts = response.workouts.map { it.toEntity() }
        persistSyncResponse(
            summaries = summaries,
            workouts = workouts,
            availableStartDay = response.availableStartDay,
        )
        todayInsightsState.value = response.todayInsights
        syncFreshnessState.value = response.syncFreshness
        response.syncFreshness?.let { fresh ->
            AppLogger.i(
                TAG,
                "Desktop freshness status=${fresh.status} latestDay=${fresh.latestDay} " +
                    "daysBehind=${fresh.daysBehind} message=${fresh.message?.take(120)}",
            )
        }
        val insightsDay = response.todayInsights?.day
        if (response.todayInsights != null && !insightsDay.isNullOrBlank()) {
            runCatching { persistInsights(insightsDay, response.todayInsights, updateLatest = true) }
                .onFailure { AppLogger.w(TAG, "Failed to persist today insights day=$insightsDay", it) }
        }
        runCatching { persistFreshness(response.syncFreshness) }
            .onFailure { AppLogger.w(TAG, "Failed to persist sync freshness", it) }
        AppLogger.i(TAG, "Sync persisted url=${validated.serverUrl} summaries=${summaries.size} workouts=${workouts.size}")
        return response
    }

    private suspend fun fail(reason: SyncFailureReason): Result<Unit> {
        val message = reason.userMessage
        preferencesRepository.recordSyncFailure(message)
        AppLogger.e(TAG, "Sync failed: $message")
        return Result.failure(SyncFailureException(message, reason))
    }

    private fun noServerMessage(preferredNetwork: String): String = when (preferredNetwork) {
        "local" -> "No local LAN server URL configured. Add one in Settings."
        "tailscale" -> "No Tailscale server URL configured. Add one in Settings."
        else -> "No server URLs configured. Add at least one address in Settings."
    }

    private suspend fun persistSyncResponse(
        summaries: List<DailySummaryEntity>,
        workouts: List<WorkoutEntity>,
        availableStartDay: String?,
    ) {
        database.withTransaction {
            if (summaries.isNotEmpty()) {
                dao.upsertDailySummaries(summaries)
            }
            if (workouts.isNotEmpty()) {
                dao.upsertWorkouts(workouts)
            }
            if (!availableStartDay.isNullOrBlank()) {
                dao.deleteSummariesBefore(availableStartDay)
                dao.deleteWorkoutsBefore(availableStartDay)
                dao.deleteInsightsBefore(availableStartDay)
            }
        }
    }
}
