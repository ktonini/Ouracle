import Charts
import SwiftUI

/// Trends over the synced window: pick a metric, see the line.
struct TrendsView: View {
    @EnvironmentObject var store: AppStore
    @State private var metric: TrendMetric = .sleepScore
    @State private var window: Int = 30

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
                    chart
                    summary
                    Spacer()
                }
            }
            .padding()
            .navigationTitle("Trends")
            .refreshable { await store.refresh() }
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
        let days = (store.sync?.days ?? []).suffix(window)
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
