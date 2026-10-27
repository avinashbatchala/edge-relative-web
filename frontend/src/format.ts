export const numeric = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
export const fmt = (value: unknown, digits = 2) => {
  const n = numeric(value);
  return n === null
    ? "—"
    : n.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
};
export const et = (epoch: number | null | undefined) =>
  epoch == null
    ? "—"
    : new Date(epoch * 1000).toLocaleString("en-US", {
        timeZone: "America/New_York",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
export function replayPoints<T>(points: T[], count: number): T[] {
  return points.slice(0, Math.max(0, Math.min(points.length, count)));
}
