<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";
import {
  TabsRoot,
  TabsList,
  TabsTrigger,
  SwitchRoot,
  SwitchThumb,
  SelectRoot,
  SelectTrigger,
  SelectPortal,
  SelectContent,
  SelectItem,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
  TooltipPortal,
  TooltipContent,
} from "reka-ui";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileArchive,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RotateCcw,
  Search,
  Settings2,
} from "lucide-vue-next";
import type { ChartData, Point, Quote, Row, Snapshot, Status } from "./types";
import { fmt, et, numeric } from "./format";
import { downloadExport, type ExportKind } from "./download";
import { readChartTheme, type ChartTheme } from "./chart-theme";
import {
  ChartInstanceSlot,
  ResourceScope,
  contextBadge,
  maximizeRegion,
  replayView,
  selectPrimaryStudy,
  selectSecondaryStudy,
  setCompareMode,
  setPaneRatio,
  setSecondaryRatio,
  STUDIES,
  studyValue,
  toggleSidebar as toggleSidebarLayout,
  type ChartRegion,
  type StudyKey,
  type WorkspaceLayout,
} from "./workspace-state";

const props = defineProps<{
  data?: ChartData;
  selectedSymbol: string;
  rows: Row[];
  snapshot?: Snapshot;
  status?: Status;
  catalogAvailable: boolean;
  transport: string;
  quote?: Quote;
  loading: boolean;
  requestError?: string;
  busy?: boolean;
  liveMode: boolean;
  layout: WorkspaceLayout;
}>();
const emit = defineEmits<{
  (event: "select-symbol", symbol: string): void;
  (event: "fetch"): void;
  (event: "settings"): void;
  (event: "scanner"): void;
  (event: "update:live-mode", value: boolean): void;
  (event: "toggle-live", value: boolean): void;
  (event: "update:layout", value: WorkspaceLayout): void;
}>();

const exportBusy = ref(false);
const exportError = ref("");
const exportNotice = ref("");
async function exportData(kind: ExportKind) {
  const data = props.data;
  if (!data || data.symbol !== props.selectedSymbol || exportBusy.value) return;
  exportBusy.value = true; exportError.value = ""; exportNotice.value = "";
  try {
    const filename = await downloadExport(kind, data.symbol, data.run_id);
    exportNotice.value = `Download started: ${filename}`;
  } catch (error) {
    exportError.value = error instanceof Error ? error.message : "Export failed. Please retry.";
  } finally { exportBusy.value = false; }
}
watch(() => props.selectedSymbol, () => { exportError.value = ""; exportNotice.value = ""; });

const studyLabels: Record<StudyKey, string> = {
  rrs: "RRS",
  rrv: "Relative Volume Momentum",
  rel_volatility: "Relative Volatility Expansion",
  sector_rrs: "Sector Strength",
};
const studyColors: Record<StudyKey, "rrs" | "rrv" | "volatility" | "sector"> = {
  rrs: "rrs",
  rrv: "rrv",
  rel_volatility: "volatility",
  sector_rrs: "sector",
};
const directionFilters = ["all", "bullish", "bearish", "mixed", "unavailable"] as const;
const host = ref<HTMLDivElement>();
const chartHost = ref<HTMLDivElement>();
const search = ref("");
const filter = ref<(typeof directionFilters)[number]>("all");
const hoverTime = ref<number | null>(null);
const replay = ref(false);
const playing = ref(false);
const cursor = ref(0);
const chartInstanceId = ref(0);
const chartHeight = ref(0);
const viewportWidth = ref(typeof window === "undefined" ? 1440 : window.innerWidth);
const viewportHeight = ref(typeof window === "undefined" ? 900 : window.innerHeight);
const showCorrelation = ref(false);
const histogramMode = ref(false);
const showSignals = ref(true);
const range = computed(() => (props.data ? replayView(props.data.points, replay.value, cursor.value) : { points: [] as Point[], quote: undefined, inspectedTime: undefined }));
const points = computed(() => range.value.points);
const inspected = computed(() =>
  points.value.find((point) => point.time === hoverTime.value) ?? points.value.at(-1),
);
const activeRow = computed(() => props.rows.find((row) => row.symbol === props.selectedSymbol));
const narrowedRows = computed(() =>
  props.rows.filter((row) =>
    (filter.value === "all" || row.direction === filter.value) &&
    row.symbol.toLowerCase().includes(search.value.trim().toLowerCase()),
  ),
);
const currentQuality = computed(() =>
  props.data?.symbol === props.selectedSymbol
    ? props.data.quality.quality
    : activeRow.value?.quality ?? "missing",
);
const marketBadge = computed(() =>
  contextBadge(inspected.value?.features.market_regime as string | number | null | undefined, props.data?.regime_labels ?? {}, "market"),
);
const sectorBadge = computed(() =>
  contextBadge(
    inspected.value?.features.sector_state as string | number | null | undefined,
    { "-1": "Weak", "0": "Neutral", "1": "Strong" },
    "sector",
  ),
);
const visibleQuote = computed(() =>
  range.value.quote?.symbol === props.selectedSymbol &&
  props.data?.symbol === props.selectedSymbol &&
  props.data.quality.quality !== "historical" &&
  !replay.value
    ? range.value.quote
    : undefined,
);
const selectedStudyKeys = computed<StudyKey[]>(() =>
  props.layout.compare
    ? [props.layout.primaryStudy, props.layout.secondaryStudy]
    : [props.layout.primaryStudy],
);
const currentStudyValue = (key: StudyKey) => studyValue(inspected.value?.features[key]);
const studyArrow = (key: StudyKey) => {
  const index = points.value.findIndex((point) => point.time === inspected.value?.time);
  if (index <= 0) return "—";
  const current = numeric(points.value[index]?.features[key]);
  const previous = numeric(points.value[index - 1]?.features[key]);
  if (current === null || previous === null) return "—";
  return current > previous ? "↑" : current < previous ? "↓" : "→";
};
const canCompare = computed(
  () => viewportWidth.value >= 760 && viewportHeight.value >= 640 && chartHeight.value >= 450,
);
const qualityMessage = computed(() => {
  if (props.status && !props.status.configured) return "Schwab credentials are not configured on the backend.";
  if (!props.data) return props.loading ? "Loading confirmed candles…" : "Select an instrument to inspect its chart.";
  if (props.data.symbol !== props.selectedSymbol)
    return props.requestError
      ? `Unable to load ${props.selectedSymbol}; showing the last usable ${props.data.symbol} chart.`
      : `Loading ${props.selectedSymbol}; showing the last usable ${props.data.symbol} chart.`;
  if (!props.data.points.length) return "No usable confirmed candle data is available for this instrument.";
  if (props.data.quality.quality === "stale") return "Confirmed candles are stale; values are from the last successful reconciliation.";
  if (props.data.quality.quality === "warmup") return "Indicator warmup: one or more studies are not ready yet.";
  if (!props.data.sector_benchmark) return "Sector benchmark unavailable; sector strength will remain unavailable.";
  if (props.status?.feed !== "connected") return `Live feed ${props.status?.feed ?? "unavailable"}; the chart contains confirmed candles only.`;
  return "";
});
const chartSlot = new ChartInstanceSlot<IChartApi>();
const resources = new ResourceScope();
let resizeObserver: ResizeObserver | undefined;
let chartResizeFrame = 0;
let replayTimer: ReturnType<typeof setInterval> | undefined;
let candles: ISeriesApi<"Candlestick"> | undefined;
let volume: ISeriesApi<"Histogram"> | undefined;
let emaFast: ISeriesApi<"Line"> | undefined;
let emaSlow: ISeriesApi<"Line"> | undefined;
let correlationSeries: ISeriesApi<"Line"> | undefined;
let markerPlugin: ISeriesMarkersPluginApi<Time> | undefined;
let studySeries = new Map<StudyKey, ISeriesApi<"Line" | "Histogram">>();
let studySeriesSignature = "";
let initialRangeApplied = false;
let resolvedTheme: ChartTheme | undefined;

function chartTheme(): ChartTheme {
  resolvedTheme ??= readChartTheme();
  return resolvedTheme;
}

function updateLayout(update: WorkspaceLayout) {
  emit("update:layout", update);
}
function updateChartSize() {
  const element = chartHost.value;
  const instance = chartSlot.current;
  if (!element || !instance) return;
  const width = element.clientWidth;
  const height = element.clientHeight;
  if (width <= 0 || height <= 0) return;
  chartHeight.value = height;
  instance.resize(width, height);
  applyPaneHeights();
}
function applyPaneHeights() {
  const instance = chartSlot.current;
  const height = chartHeight.value;
  if (!instance || height <= 0) return;
  const panes = instance.panes();
  const timeScaleHeight = 30;
  const usableHeight = Math.max(0, height - timeScaleHeight);
  const maximized = props.layout.maximizedRegion;
  if (maximized === "price") {
    panes[0]?.setStretchFactor(usableHeight - 48 * (panes.length - 1));
    for (let index = 1; index < panes.length; index++) panes[index]?.setStretchFactor(48);
    return;
  }
  if (maximized === "primary") {
    panes[0]?.setStretchFactor(48);
    panes[1]?.setStretchFactor(usableHeight - 48 * (panes.length - 1));
    if (panes[2]) panes[2].setStretchFactor(48);
    return;
  }
  if (maximized === "secondary" && panes[2]) {
    panes[0]?.setStretchFactor(48);
    panes[1]?.setStretchFactor(48);
    panes[2].setStretchFactor(usableHeight - 96);
    return;
  }
  const priceRatio = props.layout.compare
    ? Math.min(props.layout.priceRatio, 0.55)
    : props.layout.priceRatio;
  const priceHeight = Math.max(180, Math.round(usableHeight * priceRatio));
  const studyHeight = Math.max(0, usableHeight - priceHeight);
  panes[0]?.setStretchFactor(priceHeight);
  if (panes[1] && panes[2]) {
    panes[1].setStretchFactor(Math.round(studyHeight * props.layout.secondaryRatio));
    panes[2].setStretchFactor(Math.round(studyHeight * (1 - props.layout.secondaryRatio)));
  } else if (panes[1]) {
    panes[1].setStretchFactor(studyHeight);
  }
}
function saveNativePaneHeights() {
  const panes = chartSlot.current?.panes() ?? [];
  const heights = panes.map((pane) => pane.getHeight());
  const total = heights.reduce((sum, height) => sum + height, 0);
  if (total <= 0 || props.layout.maximizedRegion) return;
  let resized = setPaneRatio(props.layout, heights[0] / total);
  if (props.layout.compare && heights.length > 2) {
    const studiesHeight = heights[1] + heights[2];
    if (studiesHeight > 0)
      resized = setSecondaryRatio(resized, heights[1] / studiesHeight);
  }
  updateLayout(resized);
}
function timeLabel(time: UTCTimestamp): string {
  return et(time);
}
function createChartInstance(): IChartApi {
  if (!chartHost.value) throw new Error("Chart surface is not mounted");
  chartInstanceId.value++;
  const theme = chartTheme();
  return createChart(chartHost.value, {
    width: Math.max(1, chartHost.value.clientWidth),
    height: Math.max(1, chartHost.value.clientHeight),
    layout: {
      background: { type: ColorType.Solid, color: theme.background },
      textColor: theme.foreground,
      fontSize: 11,
      panes: {
        separatorColor: theme.border,
        separatorHoverColor: theme.foreground,
        enableResize: true,
      },
    },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.border, minimumWidth: 64 },
    timeScale: {
      borderColor: theme.border,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: timeLabel,
      rightOffset: 2,
    },
    localization: { timeFormatter: (time: UTCTimestamp) => et(time) },
    crosshair: {
      vertLine: { color: theme.crosshair, labelBackgroundColor: theme.crosshairLabel },
      horzLine: { color: theme.crosshair, labelBackgroundColor: theme.crosshairLabel },
    },
  });
}
function createBaseSeries() {
  const instance = chartSlot.current;
  if (!instance || candles) return;
  const theme = chartTheme();
  candles = instance.addSeries(CandlestickSeries, {
    upColor: theme.bullish,
    downColor: theme.bearish,
    borderVisible: false,
    wickUpColor: theme.bullish,
    wickDownColor: theme.bearish,
    priceLineVisible: false,
  }, 0);
  volume = instance.addSeries(HistogramSeries, {
    priceScaleId: "volume",
    priceFormat: { type: "volume" },
    priceLineVisible: false,
    lastValueVisible: false,
    base: 0,
  }, 0);
  instance.panes()[0]?.priceScale("volume").applyOptions({
    scaleMargins: { top: 0.83, bottom: 0 },
    borderVisible: false,
    ticksVisible: false,
  });
  emaFast = instance.addSeries(LineSeries, {
    color: theme.emaFast,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA 8",
  }, 0);
  emaSlow = instance.addSeries(LineSeries, {
    color: theme.emaSlow,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA 21",
  }, 0);
  markerPlugin = createSeriesMarkers(candles, []);
}
function asTime(time: number): UTCTimestamp {
  return time as UTCTimestamp;
}
function candleData(source: Point[]): (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] {
  return source.map((point) =>
    point.open === null || point.high === null || point.low === null || point.close === null
      ? { time: asTime(point.time) }
      : { time: asTime(point.time), open: point.open, high: point.high, low: point.low, close: point.close },
  );
}
function lineData(source: Point[], key: string): (LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] {
  return source.map((point) => {
    const value = numeric(point.features[key]);
    return value === null ? { time: asTime(point.time) } : { time: asTime(point.time), value };
  });
}
function volumeData(source: Point[]): (HistogramData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] {
  const theme = chartTheme();
  return source.map((point) => {
    const value = numeric(point.volume);
    return value === null
      ? { time: asTime(point.time) }
      : {
          time: asTime(point.time),
          value,
          color: point.close !== null && point.open !== null && point.close >= point.open ? theme.bullish : theme.bearish,
        };
  });
}
function currentMarkers(source: Point[]): SeriesMarker<UTCTimestamp>[] {
  if (!showSignals.value) return [];
  const theme = chartTheme();
  const markers: SeriesMarker<UTCTimestamp>[] = [];
  for (const point of source) {
    const features = point.features;
    if (features.market_new_bull === true || features.sector_new_strong === true)
      markers.push({ time: asTime(point.time), position: "belowBar", color: theme.bullish, shape: "arrowUp", text: "Confirmed strength" });
    if (features.market_new_bear === true || features.sector_new_weak === true)
      markers.push({ time: asTime(point.time), position: "aboveBar", color: theme.bearish, shape: "arrowDown", text: "Confirmed weakness" });
    if (features.market_new_dislocation === true)
      markers.push({ time: asTime(point.time), position: "aboveBar", color: theme.volatility, shape: "circle", text: "Dislocation" });
  }
  return markers;
}
function updatePlotData(source = points.value) {
  if (!props.data || !candles || !volume || !emaFast || !emaSlow) return;
  candles.setData(candleData(source));
  volume.setData(volumeData(source));
  emaFast.setData(lineData(source, "price_ema8"));
  emaSlow.setData(lineData(source, "price_ema21"));
  for (const [key, series] of studySeries) {
    series.setData(lineData(source, key));
  }
  correlationSeries?.setData(lineData(source, "rrs_corr"));
  markerPlugin?.setMarkers(currentMarkers(source));
}
function clearStudySeries() {
  const instance = chartSlot.current;
  if (!instance) return;
  if (correlationSeries) instance.removeSeries(correlationSeries);
  correlationSeries = undefined;
  for (const series of studySeries.values()) instance.removeSeries(series);
  studySeries.clear();
}
function createStudySeries() {
  const instance = chartSlot.current;
  if (!instance) return;
  const signature = [
    ...selectedStudyKeys.value,
    `histogram:${histogramMode.value}`,
    `correlation:${showCorrelation.value && props.layout.primaryStudy === "rrs"}`,
  ].join("|");
  if (signature === studySeriesSignature) {
    updatePlotData();
    applyPaneHeights();
    return;
  }
  clearStudySeries();
  const theme = chartTheme();
  for (const [index, key] of selectedStudyKeys.value.entries()) {
    const paneIndex = index + 1;
    const isHistogram = histogramMode.value && key === "rrv";
    const color = theme[studyColors[key]];
    const series = isHistogram
      ? instance.addSeries(HistogramSeries, {
          color,
          priceLineVisible: false,
          lastValueVisible: true,
          title: studyLabels[key],
        }, paneIndex)
      : instance.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: studyLabels[key],
        }, paneIndex);
    series.createPriceLine({
      price: 0,
      color: theme.border,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
      title: "",
    });
    studySeries.set(key, series as ISeriesApi<"Line" | "Histogram">);
  }
  if (showCorrelation.value && props.layout.primaryStudy === "rrs") {
    correlationSeries = instance.addSeries(LineSeries, {
      color: theme.muted,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "RRS correlation",
    }, 1);
  }
  studySeriesSignature = signature;
  updatePlotData();
  applyPaneHeights();
}
function syncVisibleRange(rangeValue: { from: number; to: number } | null) {
  if (!rangeValue) return;
  updateLayout({ ...props.layout, visibleRange: rangeValue });
}
function fitContent() {
  chartSlot.current?.timeScale().fitContent();
}
function inspectTime(time: number | null) {
  hoverTime.value = time;
}
function toggleReplay(enabled: boolean) {
  replay.value = enabled;
  cursor.value = props.data?.points.length ?? 0;
  playing.value = false;
  hoverTime.value = null;
}
function scrubReplay(value: number) {
  replay.value = true;
  playing.value = false;
  cursor.value = value;
  hoverTime.value = null;
}
function togglePlayback() {
  if (!props.data?.points.length) return;
  if (!replay.value) toggleReplay(true);
  playing.value = !playing.value;
  if (playing.value && cursor.value >= props.data.points.length) cursor.value = 1;
}
function selectPrimary(value: unknown) {
  if (STUDIES.includes(value as StudyKey)) updateLayout(selectPrimaryStudy(props.layout, value as StudyKey));
}
function selectSecondary(value: unknown) {
  if (STUDIES.includes(value as StudyKey)) updateLayout(selectSecondaryStudy(props.layout, value as StudyKey));
}
function openInstrument(symbol: string) {
  emit("select-symbol", symbol);
  if (viewportWidth.value <= 700 && !props.layout.sidebarCollapsed)
    updateLayout(toggleSidebarLayout(props.layout));
}
function toggleCompare(value: boolean) {
  if (value && !canCompare.value) return;
  updateLayout(setCompareMode(props.layout, value));
}
function toggleSidebar() {
  updateLayout(toggleSidebarLayout(props.layout));
}
function toggleRegion(region: ChartRegion) {
  updateLayout(maximizeRegion(props.layout, region));
}
function onPriceRatio(value: string | number) {
  const ratio = Number(value);
  if (Number.isFinite(ratio)) updateLayout(setPaneRatio(props.layout, ratio));
}
function onSecondaryRatio(value: string | number) {
  const ratio = Number(value);
  if (Number.isFinite(ratio)) updateLayout(setSecondaryRatio(props.layout, ratio));
}
function setViewportSize() {
  viewportWidth.value = window.innerWidth;
  viewportHeight.value = window.innerHeight;
  if (window.innerWidth <= 700 && !props.layout.sidebarCollapsed)
    updateLayout(toggleSidebarLayout(props.layout));
}

onMounted(async () => {
  const instance = chartSlot.ensure(createChartInstance);
  const unsubscribeCrosshair = () => instance.unsubscribeCrosshairMove(onCrosshairMove);
  const unsubscribeRange = () => instance.timeScale().unsubscribeVisibleLogicalRangeChange(syncVisibleRange);
  function onCrosshairMove(event: { time?: unknown }) {
    inspectTime(typeof event.time === "number" ? event.time : null);
  }
  instance.subscribeCrosshairMove(onCrosshairMove);
  instance.timeScale().subscribeVisibleLogicalRangeChange(syncVisibleRange);
  resources.add(unsubscribeCrosshair);
  resources.add(unsubscribeRange);
  chartHost.value?.addEventListener("pointerup", saveNativePaneHeights);
  chartHost.value?.addEventListener("pointercancel", saveNativePaneHeights);
  resources.add(() => chartHost.value?.removeEventListener("pointerup", saveNativePaneHeights));
  resources.add(() => chartHost.value?.removeEventListener("pointercancel", saveNativePaneHeights));
  window.addEventListener("resize", setViewportSize);
  resources.add(() => window.removeEventListener("resize", setViewportSize));
  setViewportSize();
  resizeObserver = new ResizeObserver(() => {
    cancelAnimationFrame(chartResizeFrame);
    chartResizeFrame = requestAnimationFrame(updateChartSize);
  });
  if (chartHost.value) resizeObserver.observe(chartHost.value);
  resources.add(() => resizeObserver?.disconnect());
  replayTimer = setInterval(() => {
    if (!playing.value || !props.data) return;
    if (cursor.value < props.data.points.length) cursor.value++;
    else playing.value = false;
  }, 600);
  resources.add(() => {
    if (replayTimer) clearInterval(replayTimer);
    cancelAnimationFrame(chartResizeFrame);
  });
  updateChartSize();
  if (props.data) {
    createBaseSeries();
    updatePlotData();
    createStudySeries();
  }
  if (props.layout.visibleRange) {
    instance.timeScale().setVisibleLogicalRange(props.layout.visibleRange);
    initialRangeApplied = true;
  } else if (props.data?.points.length) {
    fitContent();
    initialRangeApplied = true;
  }
  await nextTick();
});

watch(
  () => props.data,
  async (data, oldData) => {
    if (!data || !chartSlot.current) return;
    if (data.symbol !== oldData?.symbol) {
      cursor.value = data.points.length;
      replay.value = false;
      playing.value = false;
      hoverTime.value = null;
    }
    createBaseSeries();
    updatePlotData();
    createStudySeries();
    if (!initialRangeApplied && data.points.length) {
      fitContent();
      initialRangeApplied = true;
    } else if (props.layout.visibleRange) {
      try {
        chartSlot.current.timeScale().setVisibleLogicalRange(props.layout.visibleRange);
      } catch {
        fitContent();
      }
    }
    await nextTick();
    updateChartSize();
  },
);
watch(points, (source) => updatePlotData(source));
watch(
  () => [props.layout.primaryStudy, props.layout.secondaryStudy, props.layout.compare, showCorrelation.value, histogramMode.value],
  () => {
    createStudySeries();
    nextTick(updateChartSize);
  },
);
watch(
  () => props.layout.priceRatio,
  () => applyPaneHeights(),
);
watch(
  () => [props.layout.secondaryRatio, props.layout.maximizedRegion],
  () => applyPaneHeights(),
);
watch(showSignals, () => markerPlugin?.setMarkers(currentMarkers(points.value)));
watch(canCompare, (enabled) => {
  if (!enabled && props.layout.compare) updateLayout(setCompareMode(props.layout, false));
});
watch(
  () => props.selectedSymbol,
  () => {
    replay.value = false;
    playing.value = false;
    hoverTime.value = null;
  },
);
onBeforeUnmount(() => {
  resources.dispose();
  chartSlot.dispose((instance) => instance.remove());
});
</script>

<template>
  <TooltipProvider :delay-duration="350">
    <div class="chart-workspace" :class="{ 'sidebar-collapsed': layout.sidebarCollapsed, 'compare-mode': layout.compare, 'region-maximized': !!layout.maximizedRegion }">
      <aside class="scanner-sidebar" aria-label="Instrument scanner">
        <div class="sidebar-heading">
          <span v-if="!layout.sidebarCollapsed">Watchlist <small>{{ rows.length }}</small></span>
          <TooltipRoot>
            <TooltipTrigger as-child>
              <button class="icon-button sidebar-toggle" type="button" :aria-label="layout.sidebarCollapsed ? 'Expand scanner sidebar' : 'Collapse scanner sidebar'" :title="layout.sidebarCollapsed ? 'Expand scanner sidebar' : 'Collapse scanner sidebar'" @click="toggleSidebar">
                <ChevronLeft v-if="!layout.sidebarCollapsed" :size="16" />
                <ChevronRight v-else :size="16" />
              </button>
            </TooltipTrigger>
            <TooltipPortal><TooltipContent class="tooltip">{{ layout.sidebarCollapsed ? 'Expand scanner' : 'Collapse scanner' }}</TooltipContent></TooltipPortal>
          </TooltipRoot>
        </div>
        <template v-if="!layout.sidebarCollapsed">
          <label class="sidebar-search"><Search :size="14" /><input v-model="search" type="search" placeholder="Search symbol" aria-label="Search instruments" /></label>
          <div class="sidebar-filters" role="group" aria-label="Filter instruments by direction">
            <button v-for="name in directionFilters" :key="name" type="button" :class="{ active: filter === name }" :aria-pressed="filter === name" @click="filter = name">{{ name }}</button>
          </div>
          <div class="scanner-list" role="listbox" aria-label="Instruments">
            <button v-for="row in narrowedRows" :key="row.symbol" class="instrument-row" type="button" role="option" :aria-selected="selectedSymbol === row.symbol" :class="{ selected: selectedSymbol === row.symbol }" @click="openInstrument(row.symbol)">
              <span class="instrument-identity"><strong>{{ row.symbol }}</strong><small>{{ row.quality }}</small></span>
              <span class="instrument-metrics"><b :class="{ positive: (row.rrs ?? 0) > 0, negative: (row.rrs ?? 0) < 0 }">RRS {{ studyValue(row.rrs) }}</b><span :class="['badge', row.direction]">{{ row.direction }}</span></span>
            </button>
            <div v-if="!narrowedRows.length" class="sidebar-empty">{{ snapshot ? 'No matching instruments.' : 'Scanner values appear after a successful fetch.' }}</div>
          </div>
          <p class="scanner-context">Latest scanner snapshot · {{ snapshot ? et(Date.parse(snapshot.as_of) / 1000) : 'not available' }} ET</p>
        </template>
        <template v-else>
          <div class="collapsed-instruments">
            <TooltipRoot v-for="row in narrowedRows" :key="row.symbol">
              <TooltipTrigger as-child>
                <button class="collapsed-symbol" type="button" :aria-label="`Open ${row.symbol}, ${row.direction}, RRS ${studyValue(row.rrs)}`" :aria-pressed="selectedSymbol === row.symbol" :class="{ selected: selectedSymbol === row.symbol }" @click="openInstrument(row.symbol)">{{ row.symbol.slice(0, 1) }}</button>
              </TooltipTrigger>
              <TooltipPortal><TooltipContent class="tooltip">{{ row.symbol }} · RRS {{ studyValue(row.rrs) }} · {{ row.direction }} · {{ row.quality }}</TooltipContent></TooltipPortal>
            </TooltipRoot>
          </div>
        </template>
        <button class="scanner-full-link" type="button" :title="layout.sidebarCollapsed ? 'Open full scanner' : 'Open full scanner view'" @click="$emit('scanner')">{{ layout.sidebarCollapsed ? '↗' : catalogAvailable ? 'Full scanner view' : 'Configure data & full scanner' }}</button>
      </aside>

      <section class="chart-stage" aria-label="Chart workspace">
        <div v-if="exportError" class="export-feedback export-error" role="alert">{{ exportError }}</div>
        <div v-else-if="exportBusy || exportNotice" class="export-feedback" role="status">{{ exportBusy ? 'Preparing full loaded-run export…' : exportNotice }}</div>
        <div class="chart-toolbar">
          <div class="chart-instrument-heading">
            <button class="icon-button mobile-sidebar-button" type="button" aria-label="Open instrument scanner" title="Open instrument scanner" @click="toggleSidebar"><Search :size="15" /></button>
            <strong>{{ selectedSymbol || 'Select instrument' }}</strong>
            <span class="exchange-pill">US · 5m</span>
            <span v-if="currentQuality" :class="['quality-pill', currentQuality]">{{ currentQuality }}</span>
          </div>
          <div class="chart-toolbar-meta">
            <span class="benchmark-pair"><span>Price <b>{{ data?.price_benchmark ?? snapshot?.price_benchmark ?? '—' }}</b></span><span>Volume <b>{{ data?.volume_benchmark ?? snapshot?.volume_benchmark ?? '—' }}</b></span></span>
            <span :class="['feed-state', status?.feed === 'connected' ? 'feed-connected' : 'feed-disconnected']"><i></i>{{ status?.configured ? `Schwab ${status.feed}` : 'Schwab unconfigured' }} · UI {{ transport }}</span>
            <span :class="['badge', marketBadge.tone]">Market · {{ marketBadge.label }}</span>
            <span :class="['badge', sectorBadge.tone]">Sector · {{ sectorBadge.label }}</span>
          </div>
          <div class="chart-toolbar-actions">
            <TooltipRoot><TooltipTrigger as-child><button class="icon-button" type="button" aria-label="Indicator settings" title="Indicator settings" @click="emit('settings')"><Settings2 :size="16" /></button></TooltipTrigger><TooltipPortal><TooltipContent class="tooltip">Indicator settings</TooltipContent></TooltipPortal></TooltipRoot>
            <TooltipRoot><TooltipTrigger as-child><button class="icon-button" type="button" aria-label="Refresh confirmed chart data" title="Refresh confirmed chart data" :disabled="busy" @click="emit('fetch')"><RotateCcw :size="15" /></button></TooltipTrigger><TooltipPortal><TooltipContent class="tooltip">Fetch confirmed history</TooltipContent></TooltipPortal></TooltipRoot>
            <template v-if="data && data.symbol === selectedSymbol">
              <button type="button" class="icon-button export-link" :disabled="exportBusy" :aria-busy="exportBusy" :aria-label="`Export ${selectedSymbol} full CSV`" title="CSV: all loaded candles, indicators and signals; independent of replay" @click="exportData('csv')"><Download :size="16" /></button>
              <button type="button" class="icon-button export-link" :disabled="exportBusy" :aria-busy="exportBusy" aria-label="Export complete scan diagnostic ZIP" title="Run ZIP: all stocks, benchmark inputs, daily context, settings and diagnostics" @click="exportData('zip')"><FileArchive :size="16" /></button>
            </template>
          </div>
        </div>
        <p class="benchmark-detail">{{ data?.sector_benchmark ? `Sector ${data.sector_benchmark}` : 'Sector benchmark unavailable' }} <span>·</span> Confirmed candles and scanner metrics reconcile to the latest completed bar.</p>
        <div class="chart-status-row" aria-live="polite">
          <span v-if="qualityMessage" :class="['quality-message', currentQuality === 'stale' ? 'warning' : '', status && !status.configured ? 'warning' : '']">{{ qualityMessage }}</span>
            <span v-if="props.data && props.data.symbol !== selectedSymbol && selectedSymbol && loading" class="quality-message loading">Loading {{ selectedSymbol }}…</span>
          <span v-if="requestError" class="quality-message error-message" role="alert">{{ requestError }}</span>
          <label class="live-mode-switch"><span>Live mode</span><SwitchRoot :model-value="liveMode" aria-label="Enable live feed during next fetch" class="switch-control" @update:model-value="emit('toggle-live', $event); emit('update:live-mode', $event)"><SwitchThumb class="switch-thumb" /></SwitchRoot><span>{{ liveMode ? 'Enabled for fetch' : 'Disabled' }}</span><span v-if="visibleQuote" class="provisional-label">Provisional LTP</span></label>
        </div>

        <div ref="host" class="plot-workspace" :class="{ 'has-no-data': !data?.points.length, 'plot-maximized-price': layout.maximizedRegion === 'price', 'plot-maximized-primary': layout.maximizedRegion === 'primary', 'plot-maximized-secondary': layout.maximizedRegion === 'secondary' }">
          <div class="price-region-heading">
            <div class="ohlc-strip"><span class="ohlc-time">{{ et(inspected?.time) }} ET</span><span>O <b>{{ fmt(inspected?.open) }}</b></span><span>H <b>{{ fmt(inspected?.high) }}</b></span><span>L <b>{{ fmt(inspected?.low) }}</b></span><span>C <b>{{ fmt(inspected?.close) }}</b></span><span v-if="visibleQuote" class="provisional-quote">LTP ${{ fmt(visibleQuote.price) }} <small>provisional · {{ et(visibleQuote.time) }}</small></span></div>
            <TooltipRoot><TooltipTrigger as-child><button class="icon-button maximize-button" type="button" :aria-label="layout.maximizedRegion === 'price' ? 'Restore chart layout' : 'Maximize price region'" :title="layout.maximizedRegion === 'price' ? 'Restore layout' : 'Maximize price chart'" @click="toggleRegion('price')"><Minimize2 v-if="layout.maximizedRegion === 'price'" :size="15" /><Maximize2 v-else :size="15" /></button></TooltipTrigger><TooltipPortal><TooltipContent class="tooltip">{{ layout.maximizedRegion === 'price' ? 'Restore layout' : 'Maximize price region' }}</TooltipContent></TooltipPortal></TooltipRoot>
          </div>
          <div ref="chartHost" :data-chart-instance="chartInstanceId" class="chart-canvas" aria-label="Synchronized price and indicator chart"></div>
          <div v-if="!data?.points.length" class="chart-empty-overlay">
            <strong>{{ loading ? `Loading ${selectedSymbol || 'instrument'}…` : requestError ? 'Unable to load chart' : selectedSymbol ? 'No usable confirmed candles' : 'Choose an instrument' }}</strong>
            <span>{{ status && !status.configured ? 'Schwab credentials are not configured. Add them to the backend environment to load real history.' : loading ? 'Chart layout is ready; confirmed candle data is loading.' : 'Select an instrument from the scanner or fetch Schwab history. No sample data is shown.' }}</span>
          </div>
          <div v-if="data && data.symbol !== selectedSymbol" class="stale-chart-overlay" role="status">Loading {{ selectedSymbol }} · retaining last usable {{ data.symbol }} chart</div>
          <div class="pane-resize-controls">
            <label>Price / indicators <input type="range" min="0.52" max="0.76" step="0.01" :value="layout.priceRatio" aria-label="Resize price and indicator regions" @input="onPriceRatio(($event.target as HTMLInputElement).value)" /></label>
            <label v-if="layout.compare">Compare split <input type="range" min="0.30" max="0.70" step="0.01" :value="layout.secondaryRatio" aria-label="Resize compared study panels" @input="onSecondaryRatio(($event.target as HTMLInputElement).value)" /></label>
          </div>
        </div>

        <section class="indicator-region" :class="{ 'study-maximized': layout.maximizedRegion === 'primary', 'secondary-maximized': layout.maximizedRegion === 'secondary' }" aria-label="Indicator studies">
          <div class="indicator-header">
            <TabsRoot :model-value="layout.primaryStudy" class="study-tabs-root" @update:model-value="selectPrimary">
              <TabsList class="study-tabs" aria-label="Primary indicator">
                <TabsTrigger v-for="key in STUDIES" :key="key" :value="key" class="study-tab">{{ studyLabels[key] }}</TabsTrigger>
              </TabsList>
            </TabsRoot>
            <div class="indicator-controls">
              <label class="compare-control" :title="canCompare ? 'Show a second indicator panel' : 'Comparison requires a taller desktop workspace'"><span>Compare</span><SwitchRoot :model-value="layout.compare" :disabled="!canCompare" aria-label="Compare a second indicator" class="switch-control" @update:model-value="toggleCompare"><SwitchThumb class="switch-thumb" /></SwitchRoot></label>
              <SelectRoot v-if="layout.compare" :model-value="layout.secondaryStudy" @update:model-value="selectSecondary">
                <SelectTrigger class="secondary-select" aria-label="Secondary indicator"><span>{{ studyLabels[layout.secondaryStudy] }}</span></SelectTrigger>
                <SelectPortal><SelectContent class="select-content" position="popper"><SelectItem v-for="key in STUDIES.filter((study) => study !== layout.primaryStudy)" :key="key" :value="key" class="select-item">{{ studyLabels[key] }}</SelectItem></SelectContent></SelectPortal>
              </SelectRoot>
              <span v-else-if="!canCompare" class="compare-hint">Compare is unavailable at this viewport height.</span>
              <details class="study-options">
                <summary aria-label="Study presentation settings" title="Study presentation settings"><Settings2 :size="15" /></summary>
                <div class="study-options-menu"><strong>Study presentation</strong><label><input v-model="showCorrelation" type="checkbox" />Show RRS correlation</label><label><input v-model="histogramMode" type="checkbox" />Volume momentum histogram</label><label><input v-model="showSignals" type="checkbox" />Show confirmed signal markers</label></div>
              </details>
              <TooltipRoot><TooltipTrigger as-child><button class="icon-button" type="button" :aria-label="layout.maximizedRegion === 'primary' ? 'Restore chart layout' : 'Maximize indicator region'" :title="layout.maximizedRegion === 'primary' ? 'Restore layout' : 'Maximize indicator'" @click="toggleRegion('primary')"><Minimize2 v-if="layout.maximizedRegion === 'primary'" :size="15" /><Maximize2 v-else :size="15" /></button></TooltipTrigger><TooltipPortal><TooltipContent class="tooltip">{{ layout.maximizedRegion === 'primary' ? 'Restore layout' : 'Maximize indicator' }}</TooltipContent></TooltipPortal></TooltipRoot>
            </div>
          </div>
          <div class="study-readouts">
            <span v-for="key in selectedStudyKeys" :key="key" :class="['study-readout', `study-${key}`]">
              <span>{{ studyLabels[key] }}</span><strong>{{ currentStudyValue(key) }}</strong><span class="study-arrow" :aria-label="`Direction ${studyArrow(key)}`">{{ studyArrow(key) }}</span>
            </span>
            <span class="study-context-note">{{ inspected ? `${et(inspected.time)} ET · ${replay ? 'historical replay' : 'completed candle'}` : 'Indicator values unavailable' }}</span>
          </div>
        </section>

        <div class="replay-toolbar">
          <label class="replay-switch"><SwitchRoot :model-value="replay" :disabled="!data?.points.length" aria-label="Historical replay" class="switch-control" @update:model-value="toggleReplay"><SwitchThumb class="switch-thumb" /></SwitchRoot><span>Replay</span></label>
          <template v-if="replay && data?.points.length">
            <button class="button button-compact" type="button" :aria-label="playing ? 'Pause historical replay' : 'Play historical replay'" @click="togglePlayback"><Pause v-if="playing" :size="14" /><Play v-else :size="14" /></button>
            <input type="range" min="1" :max="data.points.length" :value="cursor" aria-label="Replay candle" @input="scrubReplay(Number(($event.target as HTMLInputElement).value))" />
            <span class="replay-time">{{ et(range.inspectedTime) }} ET · {{ cursor }} / {{ data.points.length }}</span>
          </template>
          <span v-else class="replay-time">{{ inspected ? et(inspected.time) : 'No candle selected' }} ET</span>
          <button class="button button-compact" type="button" @click="fitContent"><RotateCcw :size="14" />Fit</button>
          <span v-if="snapshot" class="scanner-asof">Scanner snapshot · {{ et(Date.parse(snapshot.as_of) / 1000) }} ET</span>
        </div>
      </section>
    </div>
  </TooltipProvider>
</template>
