<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import {
  Activity,
  SlidersHorizontal,
  RefreshCw,
  ArrowUpRight,
  Search,
  Wifi,
  Table2,
  ChartNoAxesCombined,
  X,
  ChevronRight,
} from "lucide-vue-next";
import { api } from "./api";
import type {
  Status,
  Snapshot,
  ChartData,
  Instrument,
  Quote,
  Event,
  Row,
} from "./types";
import { fmt, ist } from "./format";
import UiButton from "./UiButton.vue";
import DirectionBadge from "./DirectionBadge.vue";
import ChartWorkspace from "./ChartWorkspace.vue";
const status = ref<Status>();
const snapshot = ref<Snapshot>();
const chart = ref<ChartData>();
const catalog = ref<Instrument[]>([]);
const quotes = ref<Record<string, Quote>>({});
const view = ref<"scanner" | "chart">("scanner");
const busy = ref(false);
const error = ref("");
const direction = ref("all");
const search = ref("");
const details = ref(false);
const end = ref(new Date().toISOString().slice(0, 10));
const start = ref(
  new Date(Date.now() - 20 * 86400000).toISOString().slice(0, 10),
);
const priceBenchmark = ref("NIFTY 50");
const volumeBenchmark = ref("NIFTYBEES");
const length = ref(12);
const smoothing = ref(3);
const atr = ref(14);
const live = ref(true);
const marketFilter = ref(false);
const sectorFilter = ref(false);
const volumeFilter = ref(false);
const filtered = computed(
  () =>
    snapshot.value?.rows.filter(
      (r) =>
        (direction.value === "all" || r.direction === direction.value) &&
        r.symbol.toLowerCase().includes(search.value.toLowerCase()),
    ) || [],
);
const count = (name: string) =>
  snapshot.value?.rows.filter((r) => r.direction === name).length || 0;
let socket: WebSocket | undefined;
let retry: ReturnType<typeof setTimeout> | undefined;
let mounted = true;
let sequence: number | undefined;
let chartRequest = 0;
const selected = ref("");
const transport = ref("connecting");
async function openChart(symbol: string) {
  selected.value = symbol;
  view.value = "chart";
  chart.value = undefined;
  error.value = "";
  const token = ++chartRequest;
  try {
    const result = await api.chart(symbol);
    if (token === chartRequest) chart.value = result;
  } catch (e) {
    if (token === chartRequest) error.value = (e as Error).message;
  }
}
async function updateSnapshot(value: Snapshot) {
  snapshot.value = value;
  if (view.value === "chart" && selected.value) {
    const token = ++chartRequest;
    try {
      const result = await api.chart(selected.value);
      if (token === chartRequest) chart.value = result;
    } catch {
      chart.value = undefined;
    }
  }
}
async function fetchData() {
  busy.value = true;
  error.value = "";
  try {
    const now = new Date();
    const requestedEnd =
      end.value === now.toISOString().slice(0, 10)
        ? now.toISOString()
        : end.value + "T15:30:00+05:30";
    await updateSnapshot(
      await api.scan({
        start: start.value + "T09:15:00+05:30",
        end: requestedEnd,
        refresh: true,
        live: live.value && end.value === now.toISOString().slice(0, 10),
        price_benchmark: priceBenchmark.value,
        volume_benchmark: volumeBenchmark.value,
        parameters: {
          length: length.value,
          smoothVol: smoothing.value,
          atrPeriod: atr.value,
        },
        market_filter: marketFilter.value,
        sector_filter: sectorFilter.value,
        volume_filter: volumeFilter.value,
        min_volume_momentum: 0,
      }),
    );
    status.value = await api.health();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function sync() {
  busy.value = true;
  error.value = "";
  try {
    catalog.value = await api.sync();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
function connect() {
  if (!mounted) return;
  socket = new WebSocket(
    (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/api/v1/ws",
  );
  socket.onopen = () => {
    transport.value = "connected";
    sequence = undefined;
  };
  socket.onmessage = async (event) => {
    let message: Event;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.schema_version !== "1.0") return;
    if (sequence !== undefined && message.sequence > sequence + 1) {
      try {
        await updateSnapshot(await api.snapshot());
      } catch {}
    }
    sequence = message.sequence;
    if (message.type === "status") status.value = message.payload;
    if (message.type === "quote")
      quotes.value[message.payload.symbol] = message.payload;
    if (message.type === "snapshot") await updateSnapshot(message.payload);
  };
  socket.onclose = () => {
    transport.value = "disconnected";
    if (mounted) retry = setTimeout(connect, 3000);
  };
  socket.onerror = () => socket?.close();
}
onMounted(async () => {
  connect();
  try {
    [status.value, catalog.value] = await Promise.all([
      api.health(),
      api.instruments(),
    ]);
    try {
      await updateSnapshot(await api.snapshot());
    } catch {
      /* Truthful empty state before the first fetch. */
    }
  } catch (e) {
    error.value = (e as Error).message;
  }
});
onBeforeUnmount(() => {
  mounted = false;
  socket?.close();
  if (retry) clearTimeout(retry);
});
function rowTime(row: Row) {
  return ist(row.candle_time);
}
</script>
<template>
  <div class="workspace">
    <aside class="rail">
      <div class="brand-mark">er<span>↗</span></div>
      <button
        :class="{ selected: view === 'scanner' }"
        aria-label="Scanner"
        title="Scanner"
        @click="view = 'scanner'"
      >
        <Table2 :size="20" /></button
      ><button
        :class="{ selected: view === 'chart' }"
        aria-label="Chart workspace"
        title="Charts"
        @click="view = 'chart'"
      >
        <ChartNoAxesCombined :size="20" />
      </button>
      <div class="rail-bottom">
        <button
          aria-label="Settings and data diagnostics"
          title="Settings"
          @click="details = true"
        >
          <SlidersHorizontal :size="19" />
        </button>
      </div>
    </aside>
    <div class="main">
      <header>
        <div class="title">
          <strong>EDGE RELATIVE</strong><span class="divider"></span
          ><span>Market workspace</span><span class="poc">POC</span>
        </div>
        <div class="connection">
          <Wifi :size="14" /><span
            :class="{ good: status?.feed === 'connected' }"
            >Groww ·
            {{ status?.configured ? status.feed : "unconfigured" }}</span
          ><span class="small muted">UI {{ transport }}</span>
        </div>
      </header>
      <div class="toolbar">
        <div class="tabs">
          <button
            :class="{ active: view === 'scanner' }"
            @click="view = 'scanner'"
          >
            Scanner</button
          ><button
            :class="{ active: view === 'chart' }"
            @click="view = 'chart'"
          >
            Chart workspace
          </button>
        </div>
        <div class="date-controls">
          <label>From<input type="date" v-model="start" /></label
          ><label>To<input type="date" v-model="end" /></label
          ><label class="check"
            ><input type="checkbox" v-model="live" /> Live</label
          ><UiButton primary :busy="busy" @click="fetchData"
            ><RefreshCw :size="14" :class="{ spin: busy }" />{{
              busy ? "Fetching…" : "Fetch / refresh"
            }}</UiButton
          >
        </div>
      </div>
      <div v-if="error" class="error" role="alert">
        <strong>Unable to complete request</strong><span>{{ error }}</span
        ><button aria-label="Dismiss error" @click="error = ''">×</button>
      </div>
      <div v-if="status && !status.configured" class="setup-banner">
        <Activity :size="18" />
        <div>
          <strong>Connect Groww to get started</strong
          ><span
            >Add your Groww credentials to the backend environment and restart.
            Your keys stay on the server.</span
          >
        </div>
      </div>
      <template v-if="view === 'scanner'">
        <section class="intro">
          <div>
            <div class="eyebrow">NSE EQUITIES / COMPLETED 5-MINUTE CANDLES</div>
            <h1>Find the relative edge<span>.</span></h1>
            <p>
              One universe. Both directions. Every observation backed by its
              chart.
            </p>
          </div>
          <div class="run-meta">
            <span class="muted small">Last completed candle · IST</span
            ><b>{{
              snapshot
                ? ist(Date.parse(snapshot.as_of) / 1000)
                : "Awaiting Groww data"
            }}</b
            ><button class="text-button" @click="details = true">
              Data quality <ArrowUpRight :size="14" />
            </button>
          </div>
        </section>
        <section class="stats">
          <div>
            <span>Universe</span
            ><strong>{{
              catalog
                .filter((i) => i.kind === "stock" && i.enabled)
                .length.toString()
                .padStart(2, "0")
            }}</strong
            ><small>Enabled equities</small>
          </div>
          <div class="bullish-stat">
            <span>Bullish</span
            ><strong>{{ count("bullish").toString().padStart(2, "0") }}</strong
            ><small>Positive + rising RRS</small>
          </div>
          <div class="bearish-stat">
            <span>Bearish</span
            ><strong>{{ count("bearish").toString().padStart(2, "0") }}</strong
            ><small>Negative + falling RRS</small>
          </div>
          <div>
            <span>Mixed / unavailable</span
            ><strong>{{
              (count("mixed") + count("unavailable"))
                .toString()
                .padStart(2, "0")
            }}</strong
            ><small>Filters or incomplete inputs</small>
          </div>
        </section>
        <section class="scanner-panel">
          <div class="panel-controls">
            <div class="segmented">
              <button
                v-for="name in [
                  'all',
                  'bullish',
                  'bearish',
                  'mixed',
                  'unavailable',
                ]"
                :key="name"
                :class="{ active: direction === name }"
                @click="direction = name"
              >
                {{ name }}
              </button>
            </div>
            <label class="search"
              ><Search :size="14" /><input
                v-model="search"
                placeholder="Search symbol"
                aria-label="Search symbols"
            /></label>
          </div>
          <div class="filter-line">
            <span>Confirm with</span
            ><label class="check"
              ><input type="checkbox" v-model="marketFilter" />Market
              direction</label
            ><label class="check"
              ><input type="checkbox" v-model="sectorFilter" />Sector
              direction</label
            ><label class="check"
              ><input type="checkbox" v-model="volumeFilter" />Volume momentum ≥
              0</label
            ><span class="small muted">Apply on next fetch</span>
          </div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Last close ₹</th>
                  <th>RRS</th>
                  <th>Volume momentum</th>
                  <th>Volatility expansion</th>
                  <th>Sector RRS</th>
                  <th>Direction</th>
                  <th>Quality</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in filtered" :key="row.symbol">
                  <td>
                    <button class="symbol" @click="openChart(row.symbol)">
                      {{ row.symbol }}</button
                    ><small>{{ rowTime(row) }} IST</small>
                  </td>
                  <td>{{ fmt(row.close) }}</td>
                  <td
                    :class="{
                      positive: (row.rrs ?? 0) > 0,
                      negative: (row.rrs ?? 0) < 0,
                    }"
                  >
                    {{ fmt(row.rrs) }}
                  </td>
                  <td>{{ fmt(row.rrv) }}</td>
                  <td>{{ fmt(row.relative_volatility) }}</td>
                  <td>{{ fmt(row.sector_rrs) }}</td>
                  <td><DirectionBadge :direction="row.direction" /></td>
                  <td>
                    <span
                      :class="['quality', row.quality]"
                      :title="(row.reasons || []).join(' · ')"
                      >{{ row.quality }}</span
                    >
                  </td>
                  <td>
                    <button
                      class="icon-button"
                      :aria-label="'Open ' + row.symbol + ' chart'"
                      @click="openChart(row.symbol)"
                    >
                      <ChevronRight :size="16" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="!filtered.length" class="empty">
            <div class="empty-icon"><Activity :size="26" /></div>
            <h3>
              {{
                snapshot
                  ? "No matching instruments"
                  : "Your scanner is ready for real data"
              }}
            </h3>
            <p>
              {{
                snapshot
                  ? "Adjust the direction or symbol filter."
                  : "Fetch Groww history to calculate the five studies. No values are shown until data is available."
              }}
            </p>
            <UiButton v-if="!snapshot" primary :busy="busy" @click="fetchData"
              >Fetch Groww history <ArrowUpRight :size="14"
            /></UiButton>
          </div>
          <div class="panel-footer">
            <span
              >{{ filtered.length }} instruments · directional
              observations</span
            ><span
              >{{ snapshot?.price_benchmark || "NIFTY 50" }} price benchmark ·
              {{ snapshot?.volume_benchmark || "NIFTYBEES" }} volume proxy</span
            >
          </div>
        </section>
      </template>
      <section v-else class="chart-panel">
        <div class="chart-selector">
          <label
            >Instrument
            <select
              :value="selected"
              @change="openChart(($event.target as HTMLSelectElement).value)"
            >
              <option value="" disabled>Select an instrument</option>
              <option v-for="row in snapshot?.rows || []" :value="row.symbol">
                {{ row.symbol }}
              </option>
            </select></label
          ><DirectionBadge
            v-if="chart"
            :direction="chart.quality.direction"
          /><span v-if="chart" class="small muted"
            >{{ chart.quality.quality }} ·
            {{ (chart.quality.reasons || []).join(" · ") }}</span
          >
        </div>
        <ChartWorkspace
          v-if="chart"
          :data="chart"
          :quote="chart.quality.quality!=='historical' && status?.feed==='connected' ? quotes[chart.symbol] : undefined"
        />
        <div v-else class="empty">
          <ChartNoAxesCombined :size="32" />
          <h3>
            {{
              selected && snapshot
                ? "Loading chart…"
                : "Choose an instrument from the scanner"
            }}
          </h3>
          <p>The chart and scanner share the same Python calculations.</p>
          <UiButton @click="view = 'scanner'">Open scanner</UiButton>
        </div>
      </section>
      <footer>
        <span
          ><span class="dot"></span
          >{{ status?.message || "Connecting to backend…" }}</span
        ><span>Research observations · Asia/Kolkata</span>
      </footer>
    </div>
    <div v-if="details" class="overlay" @click.self="details = false">
      <section
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <div class="dialog-heading">
          <h2 id="settings-title">Workspace & data quality</h2>
          <button
            class="icon-button"
            aria-label="Close settings"
            @click="details = false"
          >
            <X :size="20" />
          </button>
        </div>
        <p class="muted">
          Instrument identities are resolved against Groww's master and saved
          for future runs.
        </p>
        <UiButton :busy="busy" @click="sync"
          ><RefreshCw :size="14" />Sync instrument identities</UiButton
        >
        <div class="catalog">
          <div v-for="i in catalog" :key="i.symbol">
            <strong>{{ i.symbol }}</strong
            ><span>{{ i.kind }}</span
            ><span class="muted">{{
              i.groww_symbol || "Awaiting resolution"
            }}</span>
          </div>
        </div>
        <div class="settings-form">
          <label
            >Price benchmark<select v-model="priceBenchmark">
              <option
                v-for="i in catalog.filter(
                  (i) => i.kind === 'index' && i.enabled,
                )"
                :value="i.symbol"
              >
                {{ i.symbol }}
              </option>
            </select></label
          ><label
            >Volume benchmark<select v-model="volumeBenchmark">
              <option
                v-for="i in catalog.filter(
                  (i) => i.kind !== 'index' && i.enabled,
                )"
                :value="i.symbol"
              >
                {{ i.symbol }}
              </option>
            </select></label
          ><label
            >RRS lookback<input
              type="number"
              min="2"
              max="200"
              v-model.number="length" /></label
          ><label
            >Volume smoothing<input
              type="number"
              min="1"
              max="50"
              v-model.number="smoothing" /></label
          ><label
            >Volatility ATR length<input
              type="number"
              min="2"
              max="200"
              v-model.number="atr"
          /></label>
          <p class="small muted">
            Settings apply on the next fetch. Live mode is used when the range
            ends today.
          </p>
        </div>
        <details>
          <summary>Calculated parameters</summary>
          <pre>{{
            chart?.parameters ||
            "Default ThinkScript settings. Fetch and open a chart to inspect."
          }}</pre>
        </details>
        <details>
          <summary>Fetch diagnostics</summary>
          <pre>{{ snapshot?.diagnostics || "No fetch completed yet." }}</pre>
        </details>
      </section>
    </div>
  </div>
</template>
