import SwiftUI

struct HistoryView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationStack {
            List(store.days.reversed()) { day in
                NavigationLink(value: day) {
                    HStack {
                        Text(shortDay(day.day))
                            .frame(width: 92, alignment: .leading)
                        Spacer()
                        scorePill(day.sleepScore, "moon.fill")
                        scorePill(day.readinessScore, "bolt.fill")
                        scorePill(day.activityScore, "flame.fill")
                    }
                    .font(.subheadline)
                }
            }
            .navigationDestination(for: DailySummary.self) { day in
                DayDetailView(day: day)
            }
            .navigationTitle("History")
            .overlay {
                if store.days.isEmpty {
                    ContentUnavailableView(
                        "No history yet", systemImage: "calendar"
                    )
                }
            }
            .refreshable { await store.refresh() }
        }
    }

    private func scorePill(_ score: Int?, _ icon: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon)
                .font(.caption2)
            Text(score.map(String.init) ?? "–")
                .monospacedDigit()
        }
        .frame(width: 52)
        .foregroundStyle(score == nil ? Color.secondary : Color.primary)
    }

    private func shortDay(_ day: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day) else { return day }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }
}
