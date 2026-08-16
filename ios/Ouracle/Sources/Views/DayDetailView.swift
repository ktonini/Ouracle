import Charts
import SwiftUI

/// Full detail for one day: scores, sleep stage timeline, durations,
/// and overnight HR/HRV charts.
struct DayDetailView: View {
    @EnvironmentObject var store: AppStore
    let day: DailySummary

    @State private var sessions: [SleepSessionDetail] = []
    @State private var ringNight: RingNight?
    @State private var loading = true
    @State private var loadError: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Spacer()
                    ScoreRing(title: "Sleep", score: day.sleepScore)
                    Spacer()
                    ScoreRing(title: "Readiness", score: day.readinessScore)
                    Spacer()
                    ScoreRing(title: "Activity", score: day.activityScore)
                    Spacer()
                }

                if loading {
                    ProgressView("Loading sleep detail…")
                        .frame(maxWidth: .infinity)
                } else if let loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                } else if sessions.isEmpty {
                    Text("No sleep recorded for this day.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                ForEach(sessions) { session in
                    sessionSection(session)
                }

                ringNightSection
            }
            .padding()
        }
        .navigationTitle(formattedDay(day.day))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            guard let client = store.client else { return }
            do {
                sessions = try await client.sleepSessions(day: day.day)
            } catch {
                loadError = error.localizedDescription
            }
            // Independent of the cloud sessions above, and fine to be absent.
            ringNight = try? await client.ringNight(day: day.day)
            loading = false
        }
    }

    // MARK: - From the ring itself

    /// Built from events read over Bluetooth, so it appears even for nights
    /// the cloud never scored.
    @ViewBuilder
    private var ringNightSection: some View {
        if let night = ringNight, !night.heartRate.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("From the ring", systemImage: "dot.radiowaves.left.and.right")
                        .font(.headline)
                    Spacer()
                    Text("\(night.beats.formatted()) beats")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let bedtime = night.detectedBedtimes.first,
                   let start = parseDateTime(bedtime.start),
                   let end = parseDateTime(bedtime.end)
                {
                    Text("Ring detected sleep \(start.formatted(date: .omitted, time: .shortened))–\(end.formatted(date: .omitted, time: .shortened))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !night.stages.isEmpty {
                    RingHypnogram(stages: night.stages)
                        .frame(height: 46)
                    stageLegend
                }

                if let summary = night.stageSummary {
                    HStack {
                        stat("Deep", "\(summary.deepMinutes)m")
                        stat("Light", "\(summary.lightMinutes)m")
                        stat("REM", "\(summary.remMinutes)m")
                        stat("Awake", "\(summary.awakeMinutes)m")
                    }
                    Text(stagingProvenance(summary.method))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                HStack {
                    stat("Avg HR", night.averageHr.map(String.init))
                    stat("Lowest", night.lowestHr.map(String.init))
                    stat("Samples", night.heartRate.count.formatted())
                }

                ringChart(night.heartRate, title: "Heart rate", unit: "bpm", color: .red)
                if !night.movement.isEmpty {
                    ringChart(night.movement, title: "Movement", unit: "mad", color: .purple)
                }
                if !night.temperature.isEmpty {
                    ringChart(night.temperature, title: "Temperature", unit: "°C", color: .orange)
                }
            }
            .padding()
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 14))
        }
    }

    private func ringChart(
        _ points: [RingNight.Point], title: String, unit: String, color: Color
    ) -> some View {
        let series = points.compactMap { point -> (Date, Double)? in
            guard let when = parseDateTime(point.t) else { return nil }
            return (when, point.value)
        }
        return VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.subheadline.weight(.semibold))
            Chart {
                ForEach(Array(series.enumerated()), id: \.offset) { _, sample in
                    LineMark(
                        x: .value("Time", sample.0),
                        y: .value(unit, sample.1)
                    )
                    .foregroundStyle(color)
                    .interpolationMethod(.monotone)
                }
            }
            .chartYScale(domain: .automatic(includesZero: false))
            .chartXAxis {
                AxisMarks(values: .stride(by: .hour)) { _ in
                    AxisGridLine()
                    AxisValueLabel(format: .dateTime.hour())
                }
            }
            .frame(height: 100)
        }
    }

    // MARK: - Session

    @ViewBuilder
    private func sessionSection(_ session: SleepSessionDetail) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(session.type == "long_sleep" ? "Sleep" : (session.type ?? "Sleep").capitalized)
                    .font(.headline)
                Spacer()
                if let start = session.bedtimeStart, let end = session.bedtimeEnd {
                    Text("\(clock(start)) – \(clock(end))")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if let phases = session.sleepPhase5Min, !phases.isEmpty {
                StageTimeline(phases: phases)
                    .frame(height: 44)
                stageLegend
            }

            durationBars(session)

            statRow(session)

            if let hr = session.hrData, hasValues(hr) {
                seriesChart(
                    title: "Heart rate",
                    series: hr, start: session.bedtimeStart,
                    color: .red, unit: "bpm"
                )
            }
            if let hrv = session.hrvData, hasValues(hrv) {
                seriesChart(
                    title: "HRV",
                    series: hrv, start: session.bedtimeStart,
                    color: .teal, unit: "ms"
                )
            }
        }
        .padding()
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 14))
    }

    private var stageLegend: some View {
        HStack(spacing: 12) {
            legendDot(SleepStage.deep)
            legendDot(.light)
            legendDot(.rem)
            legendDot(.awake)
        }
        .font(.caption2)
    }

    private func legendDot(_ stage: SleepStage) -> some View {
        HStack(spacing: 4) {
            Circle().fill(stage.color).frame(width: 7, height: 7)
            Text(stage.label).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func durationBars(_ session: SleepSessionDetail) -> some View {
        let items: [(SleepStage, Int?)] = [
            (.deep, session.deepSleepDuration),
            (.rem, session.remSleepDuration),
            (.light, session.lightSleepDuration),
            (.awake, session.awakeTime),
        ]
        let total = max(session.timeInBed ?? items.compactMap(\.1).reduce(0, +), 1)
        VStack(spacing: 6) {
            ForEach(items, id: \.0) { stage, seconds in
                if let seconds {
                    HStack {
                        Text(stage.label)
                            .font(.caption)
                            .frame(width: 48, alignment: .leading)
                        GeometryReader { geo in
                            Capsule()
                                .fill(stage.color)
                                .frame(width: max(
                                    geo.size.width * CGFloat(seconds) / CGFloat(total), 4
                                ))
                        }
                        .frame(height: 8)
                        Text(hm(seconds))
                            .font(.caption)
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                            .frame(width: 56, alignment: .trailing)
                    }
                }
            }
        }
    }

    private func statRow(_ session: SleepSessionDetail) -> some View {
        HStack {
            stat("Efficiency", session.efficiency.map { "\($0)%" })
            stat("Avg HR", session.averageHeartRate.map { String(format: "%.0f", $0) })
            stat("Avg HRV", session.averageHrv.map { "\($0)" })
            stat("Breath", session.averageBreath.map { String(format: "%.1f", $0) })
        }
    }

    private func stat(_ label: String, _ value: String?) -> some View {
        VStack(spacing: 2) {
            Text(value ?? "–").font(.subheadline.weight(.semibold)).monospacedDigit()
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Charts

    private struct SeriesPoint: Identifiable {
        let id: Int
        let time: Date
        let value: Double
    }

    private func seriesChart(
        title: String, series: SampledSeries, start: String?,
        color: Color, unit: String
    ) -> some View {
        let points = seriesPoints(series, start: start)
        return VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.subheadline.weight(.semibold))
            Chart(points) { point in
                LineMark(x: .value("Time", point.time), y: .value(unit, point.value))
                    .foregroundStyle(color)
                    .interpolationMethod(.monotone)
            }
            .chartYScale(domain: .automatic(includesZero: false))
            .chartXAxis {
                AxisMarks(values: .stride(by: .hour, count: 2)) { _ in
                    AxisGridLine()
                    AxisValueLabel(format: .dateTime.hour())
                }
            }
            .frame(height: 110)
        }
    }

    private func seriesPoints(_ series: SampledSeries, start: String?) -> [SeriesPoint] {
        guard let items = series.items else { return [] }
        let interval = series.interval ?? 300
        let startDate = start.flatMap(parseDateTime) ?? Date()
        return items.enumerated().compactMap { index, value in
            guard let value else { return nil }
            return SeriesPoint(
                id: index,
                time: startDate.addingTimeInterval(Double(index) * interval),
                value: value
            )
        }
    }

    private func hasValues(_ series: SampledSeries) -> Bool {
        series.items?.contains { $0 != nil } ?? false
    }

    // MARK: - Formatting

    private func parseDateTime(_ string: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: string) { return date }
        // Server emits naive timestamps ("2026-08-05T07:10:00"); treat as local.
        let plain = DateFormatter()
        plain.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return plain.date(from: string)
    }

    private func clock(_ string: String) -> String {
        guard let date = parseDateTime(string) else { return string }
        return date.formatted(date: .omitted, time: .shortened)
    }

    private func hm(_ seconds: Int) -> String {
        "\(seconds / 3600)h \(seconds % 3600 / 60)m"
    }

    private func formattedDay(_ day: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day) else { return day }
        return date.formatted(.dateTime.weekday(.wide).month().day())
    }
}

/// Hypnogram for locally derived stages, drawn like the cloud one so the two
/// can be compared at a glance.
/// Says which staging produced these numbers. They are not Oura's, and a
/// learned model and a set of hand-tuned rules are not the same claim.
func stagingProvenance(_ method: String) -> String {
    switch method {
    case "ouracle-model-v1":
        return """
            Staged on your server by a model learned from Oura's own scoring of \
            your past nights, then decoded as a sequence rather than epoch by \
            epoch. Paler bands are lower confidence.
            """
    default:
        return """
            Derived on your server from the ring's movement, heart rate and \
            variability using fixed rules — an approximation, and weaker than \
            the learned model, which needs a few scored nights to train on.
            """
    }
}

struct RingHypnogram: View {
    let stages: [RingNight.Stage]

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width / CGFloat(max(stages.count, 1))
            HStack(alignment: .bottom, spacing: 0) {
                ForEach(stages) { entry in
                    let stage = SleepStage(rawValue: entry.stage) ?? .light
                    Rectangle()
                        .fill(stage.color.opacity(entry.confidence < 0.4 ? 0.45 : 1))
                        .frame(width: width, height: height(for: stage))
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
        }
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func height(for stage: SleepStage) -> CGFloat {
        switch stage {
        case .awake: return 46
        case .rem: return 34
        case .light: return 25
        case .deep: return 15
        }
    }
}

enum SleepStage: String {
    case deep, light, rem, awake

    var color: Color {
        switch self {
        case .deep: return .indigo
        case .light: return .blue
        case .rem: return .teal
        case .awake: return .orange
        }
    }

    var label: String {
        switch self {
        case .rem: return "REM"
        default: return rawValue.capitalized
        }
    }

    /// Oura 5-minute phase encoding: 1 deep, 2 light, 3 REM, 4 awake.
    init?(phaseCharacter: Character) {
        switch phaseCharacter {
        case "1": self = .deep
        case "2": self = .light
        case "3": self = .rem
        case "4": self = .awake
        default: return nil
        }
    }
}

/// Horizontal hypnogram: one colored segment per 5-minute phase sample.
struct StageTimeline: View {
    let phases: String

    var body: some View {
        GeometryReader { geo in
            let stages = phases.compactMap(SleepStage.init(phaseCharacter:))
            let width = geo.size.width / CGFloat(max(stages.count, 1))
            HStack(alignment: .bottom, spacing: 0) {
                ForEach(Array(stages.enumerated()), id: \.offset) { _, stage in
                    Rectangle()
                        .fill(stage.color)
                        .frame(width: width, height: height(for: stage))
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
        }
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func height(for stage: SleepStage) -> CGFloat {
        switch stage {
        case .awake: return 44
        case .rem: return 33
        case .light: return 24
        case .deep: return 14
        }
    }
}
