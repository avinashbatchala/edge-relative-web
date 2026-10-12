/** Binary exports have their own transport; they must not pass through JSON API parsing. */
export type ExportKind = "csv" | "zip";
export type ExportFile = { blob: Blob; filename: string };
type ExportFetcher = (input: string) => Promise<Response>;

export async function requestExport(
  kind: ExportKind,
  symbol: string,
  runId?: string | null,
  fetcher: ExportFetcher = (input) => fetch(input),
): Promise<ExportFile> {
  const endpoint =
    kind === "csv" ? encodeURIComponent(symbol) + ".csv" : "run.zip";
  const query = runId ? "?run_id=" + encodeURIComponent(runId) : "";
  const response = await fetcher("/api/v1/exports/" + endpoint + query);
  if (!response.ok) {
    let message = `Export failed (HTTP ${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (typeof body.error?.message === "string")
        message = body.error.message;
    } catch {
      /* Never download an HTML error page as CSV. */
    }
    throw new Error(message);
  }
  const expected = kind === "csv" ? "text/csv" : "application/zip";
  const contentType = response.headers
    .get("content-type")
    ?.split(";")[0]
    .trim()
    .toLowerCase();
  if (contentType !== expected)
    throw new Error(
      `Server did not return a valid ${kind.toUpperCase()} export. Check the backend connection and refresh the chart.`,
    );
  const attachment = response.headers.get("content-disposition") || "";
  const supplied = /filename="([^"]+)"/i.exec(attachment)?.[1];
  const fallback =
    kind === "csv"
      ? symbol.replace(/[^A-Za-z0-9._-]/g, "_") + ".csv"
      : "edge-relative-run.zip";
  const filename = (supplied?.split(/[\\/]/).pop() || fallback).replace(
    /[\r\n]/g,
    "",
  );
  const blob = await response.blob();
  if (!blob.size)
    throw new Error("The export was empty. Fetch history and retry.");
  return { blob, filename };
}

export async function downloadExport(
  kind: ExportKind,
  symbol: string,
  runId?: string | null,
): Promise<string> {
  const file = await requestExport(kind, symbol, runId);
  const url = URL.createObjectURL(file.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.filename;
  anchor.hidden = true;
  document.body.append(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    // Allow Safari to begin consuming the URL before releasing it.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return file.filename;
}
