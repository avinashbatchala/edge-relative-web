import { fmt, numeric } from "./format.ts";

export const STUDIES = ["rrs", "rrv", "rel_volatility", "sector_rrs"] as const;
export type StudyKey = (typeof STUDIES)[number];
export type ChartRegion = "price" | "primary" | "secondary";
export type VisibleRange = { from: number; to: number };
export type WorkspaceLayout = {
  sidebarCollapsed: boolean;
  compare: boolean;
  primaryStudy: StudyKey;
  secondaryStudy: StudyKey;
  priceRatio: number;
  secondaryRatio: number;
  maximizedRegion: ChartRegion | null;
  selectedSymbol?: string;
  visibleRange?: VisibleRange;
  restoreSnapshot?: WorkspaceLayout;
};
export type ContextTone = "bullish" | "bearish" | "caution" | "unavailable";

const DEFAULT_LAYOUT: WorkspaceLayout = {
  sidebarCollapsed: false,
  compare: false,
  primaryStudy: "rrs",
  secondaryStudy: "rrv",
  priceRatio: 0.63,
  secondaryRatio: 0.5,
  maximizedRegion: null,
};
export function createDefaultLayout(): WorkspaceLayout {
  return { ...DEFAULT_LAYOUT };
}

export function selectPrimaryStudy(
  layout: WorkspaceLayout,
  study: StudyKey,
): WorkspaceLayout {
  return {
    ...layout,
    primaryStudy: study,
    secondaryStudy:
      layout.compare && study === layout.secondaryStudy
        ? layout.primaryStudy
        : layout.secondaryStudy,
  };
}

export function selectSecondaryStudy(
  layout: WorkspaceLayout,
  study: StudyKey,
): WorkspaceLayout {
  if (study === layout.primaryStudy) return layout;
  return { ...layout, secondaryStudy: study };
}

export function setCompareMode(
  layout: WorkspaceLayout,
  compare: boolean,
): WorkspaceLayout {
  return {
    ...layout,
    compare,
    secondaryStudy:
      compare && layout.secondaryStudy === layout.primaryStudy
        ? STUDIES.find((study) => study !== layout.primaryStudy) ?? "rrv"
        : layout.secondaryStudy,
  };
}

export function toggleSidebar(layout: WorkspaceLayout): WorkspaceLayout {
  return { ...layout, sidebarCollapsed: !layout.sidebarCollapsed };
}

export function setPaneRatio(
  layout: WorkspaceLayout,
  priceRatio: number,
): WorkspaceLayout {
  return { ...layout, priceRatio: clamp(priceRatio, 0.52, 0.76) };
}

export function setSecondaryRatio(
  layout: WorkspaceLayout,
  secondaryRatio: number,
): WorkspaceLayout {
  return { ...layout, secondaryRatio: clamp(secondaryRatio, 0.3, 0.7) };
}

export function maximizeRegion(
  layout: WorkspaceLayout,
  region: ChartRegion,
): WorkspaceLayout {
  if (layout.maximizedRegion) return restoreLayout(layout);
  const { restoreSnapshot: _restoreSnapshot, ...prior } = layout;
  return { ...layout, maximizedRegion: region, restoreSnapshot: prior };
}

export function restoreLayout(layout: WorkspaceLayout): WorkspaceLayout {
  const prior = layout.restoreSnapshot;
  if (prior) {
    const { restoreSnapshot: _restoreSnapshot, ...restored } = prior;
    return { ...restored, maximizedRegion: null };
  }
  return { ...layout, maximizedRegion: null };
}

export function serializeLayout(layout: WorkspaceLayout): string {
  const {
    maximizedRegion: _maximized,
    selectedSymbol: _symbol,
    visibleRange: _range,
    restoreSnapshot: _restoreSnapshot,
    ...preferences
  } = layout;
  return JSON.stringify(preferences);
}

export function loadLayout(serialized: string | null): WorkspaceLayout {
  if (!serialized) return createDefaultLayout();
  try {
    const saved = JSON.parse(serialized) as Partial<WorkspaceLayout>;
    const result = { ...DEFAULT_LAYOUT, ...saved, maximizedRegion: null };
    if (!STUDIES.includes(result.primaryStudy) || !STUDIES.includes(result.secondaryStudy))
      return createDefaultLayout();
    return result;
  } catch {
    return createDefaultLayout();
  }
}

export function createRequestGate() {
  let sequence = 0;
  return {
    begin: () => ++sequence,
    isCurrent: (token: number) => token === sequence,
    invalidate: () => ++sequence,
  };
}

export const shouldLoadSnapshot = (status: { snapshot_available: boolean }): boolean =>
  status.snapshot_available;

export type ReplayQuote = { symbol?: string; price: number; time: number; provisional: true };
export function replayView<T extends { time: number }>(
  points: T[],
  replay: boolean,
  cursor: number,
  quote?: ReplayQuote,
) {
  const visibleCount = Math.max(0, Math.min(points.length, Math.floor(cursor)));
  const visiblePoints = replay ? points.slice(0, visibleCount) : points;
  return {
    points: visiblePoints,
    quote: replay ? undefined : quote,
    inspectedTime: visiblePoints.at(-1)?.time,
  };
}

export function contextBadge(
  code: string | number | null | undefined,
  labels: Record<string, string>,
  kind: "market" | "sector",
): { label: string; tone: ContextTone } {
  if (code === null || code === undefined || String(code) === "")
    return { label: "Unavailable", tone: "unavailable" };
  const key = String(code);
  const label = labels[key];
  if (!label || label.toLowerCase() === "unavailable")
    return { label: "Unavailable", tone: "unavailable" };
  const numericCode = Number(code);
  const tone: ContextTone = numericCode === 1
    ? "bullish"
    : numericCode === -1
      ? "bearish"
      : kind === "market" && numericCode === 0
        ? "unavailable"
        : "caution";
  return { label, tone };
}

export function studyValue(value: unknown): string {
  return numeric(value) === null ? "Unavailable" : fmt(value);
}

export class ChartInstanceSlot<T> {
  #instance: T | undefined;

  ensure(factory: () => T): T {
    this.#instance ??= factory();
    return this.#instance;
  }

  get current(): T | undefined {
    return this.#instance;
  }

  dispose(remove: (instance: T) => void): void {
    if (this.#instance === undefined) return;
    const instance = this.#instance;
    this.#instance = undefined;
    remove(instance);
  }
}

export class ResourceScope {
  #disposers = new Set<() => void>();
  #disposed = false;

  add(dispose: () => void): () => void {
    if (this.#disposed) {
      dispose();
      return () => {};
    }
    this.#disposers.add(dispose);
    return () => this.#disposers.delete(dispose);
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    for (const dispose of this.#disposers) dispose();
    this.#disposers.clear();
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
