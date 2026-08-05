// Home Screen widget: the day's sleep/readiness/activity score rings.
//
// The provider fetches fresh scores directly (token via the App Group
// keychain) and falls back to the app's last-synced snapshot offline.

import SwiftUI
import WidgetKit

@main
struct OuracleWidgetBundle: WidgetBundle {
    var body: some Widget {
        ScoresWidget()
    }
}

struct ScoresEntry: TimelineEntry {
    let date: Date
    let snapshot: SharedStore.Snapshot?

    static let placeholder = ScoresEntry(
        date: .now,
        snapshot: .init(
            day: "2026-08-04", sleep: 82, readiness: 76, activity: 93,
            steps: 8250, updatedAt: .now
        )
    )
}

struct ScoresProvider: TimelineProvider {
    func placeholder(in context: Context) -> ScoresEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (ScoresEntry) -> Void) {
        if context.isPreview {
            completion(.placeholder)
        } else {
            completion(ScoresEntry(date: .now, snapshot: SharedStore.readSnapshot()))
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<ScoresEntry>) -> Void) {
        Task {
            let entry = ScoresEntry(date: .now, snapshot: await currentSnapshot())
            // The server syncs daily; hourly widget refreshes are plenty.
            let next = Calendar.current.date(byAdding: .hour, value: 1, to: .now)!
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }

    private func currentSnapshot() async -> SharedStore.Snapshot? {
        let cached = SharedStore.readSnapshot()
        guard
            let urlString = SharedStore.readServerURL(),
            let url = URL(string: urlString),
            let token = Keychain.read(account: "api-token"),
            !token.isEmpty
        else { return cached }

        let client = OuracleClient(baseURL: url, token: token)
        guard
            let sync = try? await client.sync(windowDays: 3),
            let day = sync.days.last
        else { return cached }

        let fresh = SharedStore.Snapshot(
            day: day.day,
            sleep: day.sleepScore,
            readiness: day.readinessScore,
            activity: day.activityScore,
            steps: day.steps,
            updatedAt: .now
        )
        SharedStore.save(snapshot: fresh)
        return fresh
    }
}

struct ScoresWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "OuracleScores", provider: ScoresProvider()) { entry in
            ScoresWidgetView(entry: entry)
                .containerBackground(for: .widget) {
                    LinearGradient(
                        colors: [Color(red: 0.10, green: 0.10, blue: 0.19),
                                 Color(red: 0.04, green: 0.04, blue: 0.09)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                }
        }
        .configurationDisplayName("Scores")
        .description("Today's sleep, readiness, and activity rings.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

struct ScoresWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: ScoresEntry

    var body: some View {
        if let snapshot = entry.snapshot {
            switch family {
            case .systemMedium: medium(snapshot)
            default: small(snapshot)
            }
        } else {
            Text("Open Ouracle to connect")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.7))
                .multilineTextAlignment(.center)
        }
    }

    private func small(_ snapshot: SharedStore.Snapshot) -> some View {
        HStack(spacing: 8) {
            WidgetRing(label: "Slp", score: snapshot.sleep)
            WidgetRing(label: "Rdy", score: snapshot.readiness)
            WidgetRing(label: "Act", score: snapshot.activity)
        }
    }

    private func medium(_ snapshot: SharedStore.Snapshot) -> some View {
        HStack(spacing: 18) {
            WidgetRing(label: "Sleep", score: snapshot.sleep, diameter: 58)
            WidgetRing(label: "Readiness", score: snapshot.readiness, diameter: 58)
            WidgetRing(label: "Activity", score: snapshot.activity, diameter: 58)
            VStack(alignment: .trailing, spacing: 4) {
                if let steps = snapshot.steps {
                    Text(steps.formatted())
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("steps")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.6))
                }
                Text(shortDay(snapshot.day))
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.6))
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    private func shortDay(_ day: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day) else { return day }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }
}

struct WidgetRing: View {
    let label: String
    let score: Int?
    var diameter: CGFloat = 40

    private var color: Color {
        guard let score else { return .white.opacity(0.25) }
        switch score {
        case 85...: return .green
        case 70..<85: return .blue
        case 60..<70: return .orange
        default: return .red
        }
    }

    var body: some View {
        VStack(spacing: 3) {
            ZStack {
                Circle()
                    .stroke(color.opacity(0.25), lineWidth: diameter * 0.11)
                Circle()
                    .trim(from: 0, to: CGFloat(score ?? 0) / 100)
                    .stroke(color, style: StrokeStyle(
                        lineWidth: diameter * 0.11, lineCap: .round
                    ))
                    .rotationEffect(.degrees(-90))
                Text(score.map(String.init) ?? "–")
                    .font(.system(size: diameter * 0.36, weight: .semibold))
                    .monospacedDigit()
                    .foregroundStyle(.white)
            }
            .frame(width: diameter, height: diameter)
            Text(label)
                .font(.system(size: 9))
                .foregroundStyle(.white.opacity(0.6))
        }
    }
}
