import SwiftUI

struct TodayView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let day = store.today {
                        scoreRow(day)
                        metricsGrid(day)
                        if let insights = store.sync?.todayInsights {
                            insightsSection(insights)
                        }
                        workoutsSection
                        freshnessFooter
                    } else if store.isLoading {
                        ProgressView("Syncing…")
                            .frame(maxWidth: .infinity, minHeight: 200)
                    } else {
                        emptyState
                    }
                }
                .padding()
            }
            .navigationTitle(store.today.map { formattedDay($0.day) } ?? "Today")
            .refreshable { await store.refresh() }
            .task { if store.sync == nil { await store.refresh() } }
            .overlay(alignment: .bottom) {
                if let error = store.lastError {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.white)
                        .padding(10)
                        .background(.red.opacity(0.9), in: Capsule())
                        .padding()
                }
            }
        }
    }

    private func scoreRow(_ day: DailySummary) -> some View {
        HStack {
            Spacer()
            ScoreRing(title: "Sleep", score: day.sleepScore)
            Spacer()
            ScoreRing(title: "Readiness", score: day.readinessScore)
            Spacer()
            ScoreRing(title: "Activity", score: day.activityScore)
            Spacer()
        }
    }

    private func metricsGrid(_ day: DailySummary) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 12) {
            metric("Steps", day.steps.map { $0.formatted() })
            metric("Resting HR", day.lowestHeartRate.map { "\($0) bpm" })
            metric("HRV", day.averageHrv.map { "\($0) ms" })
            metric("SpO₂", day.averageSpo2.map { String(format: "%.1f%%", $0) })
            metric(
                "Temp Δ",
                day.temperatureDeviation.map { String(format: "%+.2f°", $0) }
            )
            metric("Sleep", day.totalSleepDuration.map(duration))
            metric("Calories", day.activeCalories.map { $0.formatted() })
            metric("Resilience", day.resilienceLevel?.capitalized)
            batteryTile
        }
    }

    @ViewBuilder
    private var batteryTile: some View {
        if let battery = store.sync?.ringBattery {
            VStack(spacing: 4) {
                HStack(spacing: 4) {
                    Image(systemName: batterySymbol(battery))
                        .foregroundStyle(batteryColor(battery.level))
                    Text("\(battery.level)%")
                        .font(.headline)
                        .monospacedDigit()
                }
                Text(battery.charging || battery.inCharger ? "Charging" : "Ring")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func batterySymbol(_ battery: RingBatteryStatus) -> String {
        if battery.charging || battery.inCharger {
            return "battery.100percent.bolt"
        }
        switch battery.level {
        case 75...: return "battery.100percent"
        case 50..<75: return "battery.75percent"
        case 25..<50: return "battery.50percent"
        default: return "battery.25percent"
        }
    }

    private func batteryColor(_ level: Int) -> Color {
        switch level {
        case 50...: return .green
        case 20..<50: return .orange
        default: return .red
        }
    }

    private func metric(_ label: String, _ value: String?) -> some View {
        VStack(spacing: 4) {
            Text(value ?? "–")
                .font(.headline)
                .monospacedDigit()
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func insightsSection(_ insights: TodayInsights) -> some View {
        if let guidance = insights.guidance {
            VStack(alignment: .leading, spacing: 6) {
                Text(guidance.headline)
                    .font(.headline)
                ForEach(guidance.body, id: \.self) { line in
                    Text(line)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        }
        ForEach(insights.actionCards) { card in
            VStack(alignment: .leading, spacing: 4) {
                Label(card.title, systemImage: "exclamationmark.circle")
                    .font(.subheadline.weight(.semibold))
                Text(card.recommendation)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
        }
    }

    @ViewBuilder
    private var workoutsSection: some View {
        let todayWorkouts = (store.sync?.workouts ?? [])
            .filter { $0.day == store.today?.day }
        if !todayWorkouts.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Workouts").font(.headline)
                ForEach(todayWorkouts) { workout in
                    HStack {
                        Text(workout.activity?.capitalized ?? "Workout")
                        Spacer()
                        if let calories = workout.calories {
                            Text("\(Int(calories)) cal")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .font(.subheadline)
                }
            }
        }
    }

    @ViewBuilder
    private var freshnessFooter: some View {
        if let freshness = store.sync?.syncFreshness {
            Text(freshness.message ?? "Server status: \(freshness.status)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private var emptyState: some View {
        ContentUnavailableView(
            "No data yet",
            systemImage: "moon.zzz",
            description: Text("Pull to refresh once the server has synced your ring.")
        )
        .padding(.top, 80)
    }

    private func duration(_ seconds: Int) -> String {
        "\(seconds / 3600)h \(seconds % 3600 / 60)m"
    }

    private func formattedDay(_ day: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day) else { return day }
        return date.formatted(.dateTime.weekday(.wide).month().day())
    }
}
