import Charts
import SwiftUI

/// Trends over the synced window: pick a metric, see the line.
struct TrendsView: View {
    @EnvironmentObject var store: AppStore
    @State private var metric: TrendMetric = .sleepScore
    @State private var window: Int = 30
    @State private var ringMetric: RingTrendMetric = .breathRate
    @State private var ringTrends: RingTrends?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Metric", selection: $metric) {
                    ForEach(TrendMetric.allCases) { metric in
                        Text(metric.label).tag(metric)
                    }
                }
                .pickerStyle(.menu)

                Picker("Window", selection: $window) {
                    Text("7d").tag(7)
                    Text("30d").tag(30)
                    Text("90d").tag(90)
                }
                .pickerStyle(.segmented)

                if points.isEmpty {
                    ContentUnavailableView(
                        "Not enough data yet",
                        systemImage: "chart.xyaxis.line",
                        description: Text("Trends appear as days accumulate.")
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            chart
                            summary
                            if let ringTrends, !ringTrends.nights.isEmpty {
                                Divider().padding(.vertical, 4)
                                ringSection(ringTrends)
                            }
                        }
                    }
                }
            }
            .padding()
            .navigationTitle("Trends")
            .task(id: window) { await loadRingTrends() }
            .refreshable {
                await store.refresh()
                await loadRingTrends()
            }
        }
    }

    private struct TrendPoint: Identifiable {
        let id: String
        let date: Date
        let value: Double
    }

    private var points: [TrendPoint] {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let days = store.days.suffix(window)
        return days.compactMap { day in
            guard let value = metric.value(from: day),
                  let date = formatter.date(from: day.day)
            else { return nil }
            return TrendPoint(id: day.day, date: date, value: value)
        }
    }

    private var chart: some View {
        Chart(points) { point in
            LineMark(x: .value("Day", point.date), y: .value(metric.label, point.value))
                .foregroundStyle(metric.color)
                .interpolationMethod(.monotone)
            PointMark(x: .value("Day", point.date), y: .value(metric.label, point.value))
                .foregroundStyle(metric.color)
                .symbolSize(20)
        }
        .chartYScale(domain: .automatic(includesZero: metric.zeroBased))
        .frame(height: 240)
    }

    @ViewBuilder
    private var summary: some View {
        let values = points.map(\.value)
        if let last = values.last, !values.isEmpty {
            let avg = values.reduce(0, +) / Double(values.count)
            HStack {
                summaryStat("Latest", metric.format(last))
                summaryStat("Average", metric.format(avg))
                summaryStat("Best", metric.format(metric.lowerIsBetter ? values.min()! : values.max()!))
            }
        }
    }

    private func loadRingTrends() async {
        ringTrends = try? await store.client?.ringTrends(days: window)
    }

    /// Our figures and Oura's on one pair of axes. Seeing them diverge is the
    /// point: both the staging model and the SpO2 calibration are refitted
    /// nightly, and a drift shows here first.
    @ViewBuilder
    private func ringSection(_ trends: RingTrends) -> some View {
        let formatter = DateFormatter()
        let _ = formatter.dateFormat = "yyyy-MM-dd"

        Text("From the ring")
            .font(.headline)

        Picker("Ring metric", selection: $ringMetric) {
            ForEach(RingTrendMetric.allCases) { option in
                Text(option.label).tag(option)
            }
        }
        .pickerStyle(.menu)

        Chart {
            ForEach(trends.nights) { night in
                if let date = formatter.date(from: night.day) {
                    if let value = ringMetric.value(night.ours) {
                        LineMark(x: .value("Day", date), y: .value("Value", value))
                            .foregroundStyle(by: .value("Source", "Ring"))
                            .interpolationMethod(.monotone)
                    }
                    if let value = ringMetric.value(night.theirs) {
                        LineMark(x: .value("Day", date), y: .value("Value", value))
                            .foregroundStyle(by: .value("Source", "Oura"))
                            .interpolationMethod(.monotone)
                    }
                }
            }
        }
        .chartForegroundStyleScale(["Ring": Color.teal, "Oura": Color.secondary])
        .chartYScale(domain: .automatic(includesZero: false))
        .frame(height: 220)

        if let match = trends.agreement[ringMetric.key] {
            Text(agreementSentence(match, metric: ringMetric))
                .font(.caption2)
                .foregroundStyle(.secondary)
        } else {
            Text("No night yet has both figures for this metric.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    /// Plain prose rather than a bare number: "0.29" means nothing without
    /// knowing what it is 0.29 of, or which way it leans.
    private func agreementSentence(
        _ match: RingTrends.Agreement, metric: RingTrendMetric
    ) -> String {
        let gap = String(
            format: "Over %d nights the two differ by %.2f %@ on average",
            match.nights, match.meanAbsDifference, metric.unit
        )
        guard abs(match.bias) >= 0.05 else { return gap + ", with no consistent lean." }
        return gap + String(
            format: ", and the ring reads %@ by %.2f.",
            match.bias > 0 ? "high" : "low", abs(match.bias)
        )
    }

    private func summaryStat(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.headline).monospacedDigit()
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

enum TrendMetric: String, CaseIterable, Identifiable {
    case sleepScore, readinessScore, activityScore
    case hrv, restingHR, steps, totalSleep, temperature

    var id: String { rawValue }

    var label: String {
        switch self {
        case .sleepScore: return "Sleep score"
        case .readinessScore: return "Readiness score"
        case .activityScore: return "Activity score"
        case .hrv: return "HRV"
        case .restingHR: return "Resting HR"
        case .steps: return "Steps"
        case .totalSleep: return "Sleep duration"
        case .temperature: return "Temp deviation"
        }
    }

    var color: Color {
        switch self {
        case .sleepScore, .totalSleep: return .indigo
        case .readinessScore: return .blue
        case .activityScore, .steps: return .green
        case .hrv: return .teal
        case .restingHR: return .red
        case .temperature: return .orange
        }
    }

    var zeroBased: Bool {
        switch self {
        case .steps, .totalSleep: return true
        default: return false
        }
    }

    var lowerIsBetter: Bool {
        self == .restingHR
    }

    func value(from day: DailySummary) -> Double? {
        switch self {
        case .sleepScore: return day.sleepScore.map(Double.init)
        case .readinessScore: return day.readinessScore.map(Double.init)
        case .activityScore: return day.activityScore.map(Double.init)
        case .hrv: return day.averageHrv.map(Double.init)
        case .restingHR: return day.lowestHeartRate.map(Double.init)
        case .steps: return day.steps.map(Double.init)
        case .totalSleep: return day.totalSleepDuration.map { Double($0) / 3600 }
        case .temperature: return day.temperatureDeviation
        }
    }

    func format(_ value: Double) -> String {
        switch self {
        case .steps: return Int(value).formatted()
        case .totalSleep: return String(format: "%.1fh", value)
        case .temperature: return String(format: "%+.2f°", value)
        default: return String(format: "%.0f", value)
        }
    }
}


/// Metrics the ring produces itself, each with an Oura counterpart to compare
/// against.
enum RingTrendMetric: String, CaseIterable, Identifiable {
    case breathRate, spo2, deepMinutes, remMinutes, desaturationIndex

    var id: String { rawValue }

    var label: String {
        switch self {
        case .breathRate: return "Breathing rate"
        case .spo2: return "Blood oxygen"
        case .deepMinutes: return "Deep sleep"
        case .remMinutes: return "REM sleep"
        case .desaturationIndex: return "Dips per hour"
        }
    }

    /// Matches the server's agreement keys.
    var key: String {
        switch self {
        case .breathRate: return "breath_rate"
        case .spo2: return "spo2_percent"
        case .deepMinutes: return "deep_minutes"
        case .remMinutes: return "rem_minutes"
        case .desaturationIndex: return "desaturation_index"
        }
    }

    var unit: String {
        switch self {
        case .breathRate: return "breaths/min"
        case .spo2: return "%"
        case .deepMinutes, .remMinutes: return "minutes"
        case .desaturationIndex: return "dips/hour"
        }
    }

    func value(_ figures: RingTrends.Figures) -> Double? {
        switch self {
        case .breathRate: return figures.breathRate
        case .spo2: return figures.spo2Percent
        case .deepMinutes: return figures.deepMinutes.map(Double.init)
        case .remMinutes: return figures.remMinutes.map(Double.init)
        case .desaturationIndex: return figures.desaturationIndex
        }
    }
}
