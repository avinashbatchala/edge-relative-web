import type {
  ChartData,
  Snapshot,
  Status,
  Instrument,
  ScanRequest,
} from "./types";
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api/v1" + path, options);
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      body.error?.message ||
        (typeof body.detail === "string"
          ? body.detail
          : "Request validation failed. Check the selected dates."),
    );
  return body as T;
}
export const api = {
  health: () => request<Status>("/health"),
  instruments: () => request<Instrument[]>("/instruments"),
  sync: () => request<Instrument[]>("/instruments/sync", { method: "POST" }),
  snapshot: () => request<Snapshot>("/snapshot"),
  chart: (symbol: string) =>
    request<ChartData>("/charts/" + encodeURIComponent(symbol)),
  scan: (body: ScanRequest) =>
    request<Snapshot>("/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
