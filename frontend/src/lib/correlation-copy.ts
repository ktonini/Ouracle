/** Plain-language helpers for correlation UI (Discover + Correlate). */

export function lagSummary(lagDays: number, xLabel: string, yLabel: string): string {
  if (lagDays === 0) {
    return `Same-day pairing: each point compares ${xLabel} and ${yLabel} on the same calendar day.`;
  }
  if (lagDays === 1) {
    return `Next-day pairing (lag +1): each point compares one day's ${xLabel} with the following day's ${yLabel} — useful for "does last night affect tomorrow?" questions.`;
  }
  if (lagDays > 1) {
    return `Lag +${lagDays} days: ${xLabel} on day D is paired with ${yLabel} on day D+${lagDays}.`;
  }
  return `Lag ${lagDays} days: ${yLabel} on day D is paired with ${xLabel} on day D+${Math.abs(lagDays)}.`;
}

export function directionSummary(
  xLabel: string,
  yLabel: string,
  coefficient: number | null | undefined,
): string | null {
  if (coefficient == null) return null;
  const c = coefficient;
  if (Math.abs(c) < 0.1) {
    return `Over this period, ${xLabel} and ${yLabel} barely move together — other factors likely matter more.`;
  }
  if (c > 0) {
    return `When ${xLabel} runs higher than your usual, ${yLabel} on the paired day tends to run higher too (and lower when ${xLabel} is lower).`;
  }
  return `When ${xLabel} runs higher than your usual, ${yLabel} on the paired day tends to run lower (and higher when ${xLabel} is lower).`;
}

export function strengthLabel(coefficient: number | null | undefined): string {
  if (coefficient == null) return 'unknown strength';
  const a = Math.abs(coefficient);
  if (a < 0.1) return 'negligible';
  if (a < 0.3) return 'weak';
  if (a < 0.5) return 'moderate';
  if (a < 0.7) return 'strong';
  return 'very strong';
}
