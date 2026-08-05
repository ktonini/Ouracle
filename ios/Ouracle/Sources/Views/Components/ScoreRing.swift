import SwiftUI

/// Circular score gauge, 0–100, colored by band like the score semantics
/// used across the desktop app (85+ optimal, 70+ good, below needs attention).
struct ScoreRing: View {
    let title: String
    let score: Int?

    private var color: Color {
        guard let score else { return .secondary.opacity(0.3) }
        switch score {
        case 85...: return .green
        case 70..<85: return .blue
        case 60..<70: return .orange
        default: return .red
        }
    }

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(color.opacity(0.15), lineWidth: 8)
                Circle()
                    .trim(from: 0, to: CGFloat(score ?? 0) / 100)
                    .stroke(color, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.easeOut(duration: 0.6), value: score)
                Text(score.map(String.init) ?? "–")
                    .font(.title2.weight(.semibold))
                    .monospacedDigit()
            }
            .frame(width: 84, height: 84)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title) score \(score.map(String.init) ?? "unavailable")")
    }
}
