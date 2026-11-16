// Pure estimate for the demo "Estimated savings" card. Numbers are an
// ESTIMATE based on editable assumptions, not measured results.

export interface SavingsInputs {
  automatedDialogs: number;
  avgResponseMs: number | null;
  minutesPerInquiry: number;
  hourlyCostUsd: number;
  baselineMinutes: number;
}

export interface SavingsResult {
  hoursSaved: number;
  moneySavedUsd: number;
  botSeconds: number | null;
  speedupX: number | null;
}

export function estimateSavings({
  automatedDialogs,
  avgResponseMs,
  minutesPerInquiry,
  hourlyCostUsd,
  baselineMinutes,
}: SavingsInputs): SavingsResult {
  const hoursSaved = (automatedDialogs * minutesPerInquiry) / 60;
  const moneySavedUsd = hoursSaved * hourlyCostUsd;
  const botSeconds = avgResponseMs === null ? null : avgResponseMs / 1000;
  const speedupX = botSeconds ? (baselineMinutes * 60) / botSeconds : null;
  return { hoursSaved, moneySavedUsd, botSeconds, speedupX };
}
