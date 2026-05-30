package com.crackedoura.mobile.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.surfaceColorAtElevation
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.lifecycle.viewmodel.compose.viewModel
import com.crackedoura.mobile.data.repository.OuraRepository
import com.crackedoura.mobile.ui.screens.AIAnalystScreen
import com.crackedoura.mobile.ui.screens.AnalysisScreen
import com.crackedoura.mobile.ui.screens.DayDetailScreen
import com.crackedoura.mobile.ui.screens.OverviewScreen
import com.crackedoura.mobile.ui.screens.SettingsScreen
import com.crackedoura.mobile.ui.screens.SleepScreen
import com.crackedoura.mobile.ui.screens.TrendsScreen
import com.crackedoura.mobile.ui.theme.Coral
import com.crackedoura.mobile.ui.theme.Night
import com.crackedoura.mobile.ui.theme.Ocean

// ── Custom line-art icons ──────────────────────────────────────────────────────

/** Crescent moon — line-art, matches the glassmorphism mockup's Sleep tab icon. */
private val MoonCrescentIcon: ImageVector by lazy {
    ImageVector.Builder(
        name = "MoonCrescent",
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
    ).apply {
        path(
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.8f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        ) {
            moveTo(21f, 12.79f)
            arcTo(9f, 9f, 0f, isMoreThanHalf = true, isPositiveArc = true, x1 = 11.21f, y1 = 3f)
            arcTo(7f, 7f, 0f, isMoreThanHalf = false, isPositiveArc = false, x1 = 21f, y1 = 12.79f)
            close()
        }
    }.build()
}

/** Pulse / trend line — line-art, matches the glassmorphism mockup's Trends tab icon. */
private val PulseChartIcon: ImageVector by lazy {
    ImageVector.Builder(
        name = "PulseChart",
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
    ).apply {
        path(
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.8f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        ) {
            moveTo(2f, 12f)
            lineTo(6f, 12f)
            lineTo(9f, 3f)
            lineTo(15f, 21f)
            lineTo(18f, 12f)
            lineTo(22f, 12f)
        }
    }.build()
}

// ── Navigation destinations ───────────────────────────────────────────────────

private sealed class AppDestination(
    val route: String,
    val label: String,
    val title: String,
    val icon: @Composable () -> Unit,
) {
    data object Overview : AppDestination(
        route = "overview",
        label = "Today",
        title = "Today",
        icon = { Icon(Icons.Outlined.Home, contentDescription = "Today") },
    )

    data object Sleep : AppDestination(
        route = "sleep",
        label = "Sleep",
        title = "Sleep",
        icon = { Icon(MoonCrescentIcon, contentDescription = "Sleep") },
    )

    data object Trends : AppDestination(
        route = "trends",
        label = "Trends",
        title = "Trends",
        icon = { Icon(PulseChartIcon, contentDescription = "Trends") },
    )

    data object Ai : AppDestination(
        route = "ai",
        label = "Advisor",
        title = "Advisor",
        icon = { Icon(Icons.Outlined.AutoAwesome, contentDescription = "Advisor") },
    )

    data object Explorer : AppDestination(
        route = "explorer",
        label = "Explorer",
        title = "Explorer",
        icon = { Icon(Icons.Outlined.Search, contentDescription = "Explorer") },
    )

    data object Settings : AppDestination(
        route = "settings",
        label = "Settings",
        title = "Settings",
        icon = { Icon(Icons.Outlined.Settings, contentDescription = "Settings") },
    )

    data object DayDetail : AppDestination(
        route = "day/{day}",
        label = "Day",
        title = "Day detail",
        icon = {},
    ) {
        fun createRoute(day: String): String = "day/$day"
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OuraMobileApp(viewModel: MainViewModel, repository: OuraRepository) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val insights = remember(uiState.recentSummaries, uiState.recentWorkouts) {
        buildDailyInsights(uiState.recentSummaries, uiState.recentWorkouts)
    }
    val snackbarHostState = remember { SnackbarHostState() }
    val navController = rememberNavController()
    val analysisViewModel: AnalysisViewModel = viewModel(factory = AnalysisViewModel.Factory(repository))
    val primaryDestinations = listOf(
        AppDestination.Overview,
        AppDestination.Sleep,
        AppDestination.Trends,
        AppDestination.Ai,
        AppDestination.Explorer,
        AppDestination.Settings,
    )
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val detailDay = backStackEntry?.arguments?.getString("day")
    val currentPrimary = primaryDestinations.firstOrNull { it.route == currentRoute }
    val showBottomBar = currentPrimary != null

    LaunchedEffect(uiState.syncMessage) {
        val message = uiState.syncMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
    }

    Box(modifier = Modifier.fillMaxSize().background(Night)) {
        // Atmospheric radial glow overlays — Ocean top-left, Coral bottom-right
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Ocean.copy(alpha = 0.18f), Color.Transparent),
                    center = Offset(0f, 0f),
                    radius = size.width * 0.85f,
                ),
                radius = size.width * 0.85f,
                center = Offset(0f, 0f),
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Coral.copy(alpha = 0.12f), Color.Transparent),
                    center = Offset(size.width, size.height),
                    radius = size.width * 0.75f,
                ),
                radius = size.width * 0.75f,
                center = Offset(size.width, size.height),
            )
        }

        Scaffold(
            modifier = Modifier.fillMaxSize(),
            containerColor = Color.Transparent,
            topBar = {
                if (!showBottomBar) {
                    TopAppBar(
                        title = {
                            Text(
                                text = when (currentRoute) {
                                    AppDestination.DayDetail.route -> formatDayLabel(detailDay)
                                    else -> currentPrimary?.title ?: "Cracked Oura"
                                },
                            )
                        },
                        navigationIcon = {
                            IconButton(onClick = { navController.popBackStack() }) {
                                Icon(
                                    imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                                    contentDescription = "Back",
                                )
                            }
                        },
                        colors = TopAppBarDefaults.topAppBarColors(
                            containerColor = MaterialTheme.colorScheme.surfaceColorAtElevation(2.dp)
                                .copy(alpha = 0.82f),
                        ),
                    )
                }
            },
            bottomBar = {
                if (showBottomBar) {
                    NavigationBar(
                        containerColor = Night.copy(alpha = 0.92f),
                        contentColor = Color.White,
                    ) {
                        primaryDestinations.forEach { item ->
                            NavigationBarItem(
                                selected = currentPrimary?.route == item.route,
                                onClick = {
                                    navController.navigate(item.route) {
                                        popUpTo(navController.graph.findStartDestination().id) {
                                            saveState = true
                                        }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                },
                                icon = item.icon,
                                label = { Text(item.label) },
                            )
                        }
                    }
                }
            },
            snackbarHost = {
                SnackbarHost(
                    hostState = snackbarHostState,
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            },
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = AppDestination.Overview.route,
            ) {
                composable(AppDestination.Overview.route) {
                    OverviewScreen(
                        padding = padding,
                        uiState = uiState,
                        insights = insights,
                        isRefreshing = uiState.isSyncing,
                        onRefresh = viewModel::syncNow,
                        onOpenDayDetail = { day ->
                            navController.navigate(AppDestination.DayDetail.createRoute(day))
                        },
                        onNavigateToSettings = {
                            navController.navigate(AppDestination.Settings.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                    )
                }

                composable(AppDestination.Sleep.route) {
                    SleepScreen(
                        padding = padding,
                        insights = insights,
                        isRefreshing = uiState.isSyncing,
                        onRefresh = viewModel::syncNow,
                        onOpenDayDetail = { day ->
                            navController.navigate(AppDestination.DayDetail.createRoute(day))
                        },
                    )
                }

                composable(AppDestination.Trends.route) {
                    TrendsScreen(
                        padding = padding,
                        insights = insights,
                        isRefreshing = uiState.isSyncing,
                        onRefresh = viewModel::syncNow,
                        onOpenDayDetail = { day ->
                            navController.navigate(AppDestination.DayDetail.createRoute(day))
                        },
                        onNavigateToSettings = {
                            navController.navigate(AppDestination.Settings.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                    )
                }

                composable(AppDestination.Ai.route) {
                    AIAnalystScreen(padding = padding)
                }

                composable(AppDestination.Explorer.route) {
                    AnalysisScreen(padding = padding, viewModel = analysisViewModel)
                }

                composable(AppDestination.Settings.route) {
                    val context = androidx.compose.ui.platform.LocalContext.current
                    SettingsScreen(
                        padding = padding,
                        uiState = uiState,
                        onSaveSettings = viewModel::saveSettings,
                        onSaveAndSync = viewModel::saveSettingsAndSync,
                        onDarkModeToggle = viewModel::setDarkMode,
                        onSaveUserName = viewModel::saveUserName,
                        onSaveBackgroundSyncInterval = { hours ->
                            viewModel.saveBackgroundSyncInterval(context, hours)
                        },
                    )
                }

                composable(
                    route = AppDestination.DayDetail.route,
                    arguments = listOf(navArgument("day") { type = NavType.StringType }),
                ) { entry ->
                    val day = entry.arguments?.getString("day")
                    val dayInsightsFlow = androidx.compose.runtime.remember(day) {
                        if (day != null) viewModel.observeInsightsForDay(day)
                        else kotlinx.coroutines.flow.flowOf(null)
                    }
                    val dayInsights by dayInsightsFlow
                        .collectAsStateWithLifecycle(initialValue = null)
                    LaunchedEffect(day) {
                        if (day != null) viewModel.requestInsightsForDay(day)
                    }
                    DayDetailScreen(
                        padding = padding,
                        insight = insights.firstOrNull { it.day == day },
                        isSyncing = uiState.isSyncing,
                        onSync = viewModel::syncNow,
                        dayInsights = dayInsights ?: uiState.todayInsights?.takeIf { it.day == day },
                        syncFreshness = uiState.syncFreshness,
                    )
                }
            }
        }
    }
}
