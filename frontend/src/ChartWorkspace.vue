<script setup lang="ts">
import {
  ref,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { Play, Pause, RotateCcw, Download } from "lucide-vue-next";
import type { ChartData, Quote } from "./types";
import { fmt, ist, numeric, replayPoints } from "./format";
import UiButton from "./UiButton.vue";
const props = defineProps<{ data: ChartData; quote?: Quote }>();
const host = ref<HTMLDivElement>();
const cursor = ref(0);
const replay = ref(false);
const playing = ref(false);
const hover = ref<number | null>(null);
const selected = ref([
  "volume",
  "rrs",
  "rrv",
  "rel_volatility",
  "market_regime",
  "sector_rrs",
]);
const labels: Record<string, string> = {
  volume: "Volume",
  rrs: "RRS",
  rrv: "Volume momentum",
  rel_volatility: "Volatility expansion",
  market_regime: "Market state",
  sector_rrs: "Sector strength",
};
let chart: IChartApi | undefined;
let timer: ReturnType<typeof setInterval> | undefined;
const visible = computed(() =>
  replayPoints(
    props.data.points,
    replay.value ? cursor.value : props.data.points.length,
  ),
);
const current = computed(
  () =>
    visible.value.find((p) => p.time === hover.value) ||
    visible.value[visible.value.length - 1],
);
function toggle(key: string) {
  selected.value = selected.value.includes(key)
    ? selected.value.filter((k) => k !== key)
    : [...selected.value, key];
}
function play() {
  replay.value = true;
  playing.value = !playing.value;
  if (playing.value && cursor.value >= props.data.points.length)
    cursor.value = 1;
}
function timeLabel(time: number) {
  return new Date(time * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
function draw() {
  if (!host.value) return;
  const oldRange = chart?.timeScale().getVisibleLogicalRange();
  chart?.remove();
  chart = createChart(host.value, {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "#0b111a" },
      textColor: "#8e9cb0",
      fontSize: 11,
      attributionLogo: true,
      panes: {
        separatorColor: "#263244",
        separatorHoverColor: "#3c526b",
        enableResize: true,
      },
    },
    grid: { vertLines: { color: "#141e2c" }, horzLines: { color: "#141e2c" } },
    rightPriceScale: { borderColor: "#263244" },
    timeScale: {
      borderColor: "#263244",
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: UTCTimestamp) => timeLabel(time),
    },
    localization: { timeFormatter: (time: UTCTimestamp) => ist(time) },
    crosshair: {
      vertLine: { labelBackgroundColor: "#24364c" },
      horzLine: { labelBackgroundColor: "#24364c" },
    },
  });
  const points = visible.value;
  const candles = chart.addSeries(CandlestickSeries, {
    upColor: "#2dd4a0",
    downColor: "#fb7185",
    borderVisible: false,
    wickUpColor: "#2dd4a0",
    wickDownColor: "#fb7185",
  });
  candles.setData(
    points.map((p) =>
      p.open != null && p.high != null && p.low != null && p.close != null
        ? {
            time: p.time as UTCTimestamp,
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
          }
        : { time: p.time as UTCTimestamp },
    ),
  );
  for (const [key, color] of [
    ["price_ema8", "#60a5fa"],
    ["price_ema21", "#fbbf24"],
  ]) {
    if (points.some((p) => numeric(p.features[key]) !== null)) {
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        title: key.replace("price_", "").toUpperCase(),
      });
      line.setData(
        points.map((p) => {
          const v = numeric(p.features[key]);
          return v === null
            ? { time: p.time as UTCTimestamp }
            : { time: p.time as UTCTimestamp, value: v };
        }),
      );
    }
  }
  let pane = 1;
  for (const key of selected.value) {
    const histogram = key === "volume";
    const series = histogram
      ? chart.addSeries(
          HistogramSeries,
          {
            priceFormat: { type: "volume" },
            priceLineVisible: false,
            title: labels[key],
          },
          pane,
        )
      : chart.addSeries(
          LineSeries,
          {
            color:
              key === "rrs"
                ? "#67e8f9"
                : key === "rrv"
                  ? "#c4b5fd"
                  : key === "rel_volatility"
                    ? "#fbbf24"
                    : key === "sector_rrs"
                      ? "#60a5fa"
                      : "#2dd4a0",
            lineWidth: 2,
            priceLineVisible: false,
            title: labels[key],
          },
          pane,
        );
    series.setData(
      points.map((p) => {
        const value = histogram ? p.volume : numeric(p.features[key]);
        return value == null
          ? { time: p.time as UTCTimestamp }
          : {
              time: p.time as UTCTimestamp,
              value,
              ...(histogram
                ? {
                    color:
                      (p.close ?? 0) >= (p.open ?? 0)
                        ? "#2dd4a04d"
                        : "#fb71854d",
                  }
                : {}),
            };
      }),
    );
    if (!histogram && key !== "market_regime")
      series.createPriceLine({
        price: 0,
        color: "#475569",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
      });
    chart.panes()[pane]?.setHeight(105);
    pane++;
  }
  chart.panes()[0]?.setHeight(310);
  chart.subscribeCrosshairMove((event) => {
    hover.value = typeof event.time === "number" ? event.time : null;
  });
  if (oldRange && oldRange.to <= points.length + 5)
    chart.timeScale().setVisibleLogicalRange(oldRange);
  else chart.timeScale().fitContent();
}
onMounted(() => {
  draw();
  timer = setInterval(() => {
    if (playing.value) {
      if (cursor.value < props.data.points.length) cursor.value++;
      else playing.value = false;
    }
  }, 600);
});
watch([visible, selected], async () => {
  await nextTick();
  draw();
});
watch(
  () => props.data.symbol,
  () => {
    cursor.value = props.data.points.length;
    replay.value = false;
    playing.value = false;
  },
);
onBeforeUnmount(() => {
  chart?.remove();
  if (timer) clearInterval(timer);
});
</script>
<template>
  <div class="chart-head">
    <div>
      <h2>{{ data.symbol }} <span class="muted">NSE · 5m</span></h2>
      <div class="small muted">
        Price: {{ data.price_benchmark }} · Volume proxy:
        {{ data.volume_benchmark }} · Sector:
        {{ data.sector_benchmark || "Unmapped" }}
      </div>
    </div>
    <a
      class="button"
      :href="'/api/v1/exports/' + encodeURIComponent(data.symbol) + '.csv'"
      ><Download :size="14" /> Export CSV</a
    >
  </div>
  <div class="ohlc">
    <span>{{ ist(current?.time) }} IST</span
    ><span
      >O <b>{{ fmt(current?.open) }}</b></span
    ><span
      >H <b>{{ fmt(current?.high) }}</b></span
    ><span
      >L <b>{{ fmt(current?.low) }}</b></span
    ><span
      >C <b>{{ fmt(current?.close) }}</b></span
    ><span v-if="quote && !replay" class="live-price"
      >LTP ₹{{ fmt(quote.price) }}
      <small>provisional · {{ ist(quote.time) }}</small></span
    >
  </div>
  <div class="study-controls">
    <button
      v-for="(label, key) in labels"
      :key="key"
      :class="['chip', { active: selected.includes(String(key)) }]"
      :aria-pressed="selected.includes(String(key))"
      @click="toggle(String(key))"
    >
      {{ label }}
    </button>
  </div>
  <div
    ref="host"
    class="chart-canvas"
    :style="{ height: 335 + selected.length * 105 + 'px' }"
  ></div>
  <div class="replay-bar">
    <label class="check"
      ><input
        type="checkbox"
        v-model="replay"
        @change="
          cursor = data.points.length;
          playing = false;
        "
      />
      Historical replay</label
    ><template v-if="replay"
      ><UiButton @click="play"
        ><Pause v-if="playing" :size="14" /><Play v-else :size="14" /></UiButton
      ><input
        type="range"
        min="1"
        :max="data.points.length"
        v-model.number="cursor"
        aria-label="Replay candle"
      /><span>{{ cursor }} / {{ data.points.length }}</span></template
    ><UiButton @click="chart?.timeScale().fitContent()"
      ><RotateCcw :size="14" /> Fit</UiButton
    ><a
      href="https://www.tradingview.com/"
      target="_blank"
      rel="noreferrer"
      class="small muted"
      >Charts by TradingView</a
    >
  </div>
  <div class="chart-notes">
    <span v-for="key in selected.filter((k) => k !== 'volume')" :key="key"
      >{{ labels[key] }}
      <b>{{
        key === "market_regime"
          ? data.regime_labels[String(current?.features[key])] || "Unavailable"
          : fmt(current?.features[key])
      }}</b></span
    >
  </div>
</template>
