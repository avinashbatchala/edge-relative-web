<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "reka-ui";
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
import { fmt, et } from "./format";
import UiButton from "./UiButton.vue";
import DirectionBadge from "./DirectionBadge.vue";
import ChartWorkspace from "./ChartWorkspace.vue";
import { createRequestGate, loadLayout, serializeLayout, shouldLoadSnapshot, type WorkspaceLayout } from "./workspace-state";
const status = ref<Status>();
const snapshot = ref<Snapshot>();
const chart = ref<ChartData>();
const chartLoading = ref(false);
const chartError = ref("");
const catalog = ref<Instrument[]>([]);
const catalogAvailable = ref(false);
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
const priceBenchmark = ref("SPY");
const volumeBenchmark = ref("SPY");
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
const selected = ref("");
function loadSavedLayout() {
  try {
    return loadLayout(localStorage.getItem("edge-relative:chart-layout"));
  } catch {
    return loadLayout(null);
  }
}
const layout = ref<WorkspaceLayout>(loadSavedLayout());
const transport = ref("connecting");
const chartRequests = createRequestGate();
async function openChart(symbol: string) {
  selected.value = symbol;
  view.value = "chart";
  const token = chartRequests.begin();
  chartError.value = "";
  if (chart.value?.symbol === symbol) {
    chartLoading.value = false;
    return;
  }
  chartLoading.value = true;
  try {
    const result = await api.chart(symbol);
    if (chartRequests.isCurrent(token)) chart.value = result;
  } catch (e) {
    if (chartRequests.isCurrent(token)) chartError.value = (e as Error).message;
  } finally {
    if (chartRequests.isCurrent(token)) chartLoading.value = false;
  }
}
async function updateSnapshot(value: Snapshot) {
  snapshot.value = value;
  if (view.value === "chart" && selected.value) {
    const token = chartRequests.begin();
    const symbol = selected.value;
    chartLoading.value = true;
    try {
      const result = await api.chart(symbol);
      if (chartRequests.isCurrent(token)) chart.value = result;
    } catch (e) {
      if (chartRequests.isCurrent(token)) chartError.value = (e as Error).message;
    } finally {
      if (chartRequests.isCurrent(token)) chartLoading.value = false;
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
        : end.value + "T23:59:59Z";
    await updateSnapshot(
      await api.scan({
        start: start.value + "T00:00:00Z",
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
    catalogAvailable.value = true;
    if (shouldLoadSnapshot(status.value))
      await updateSnapshot(await api.snapshot());
  } catch (e) {
    error.value = (e as Error).message;
  }
});
watch(
  () => [
    layout.value.sidebarCollapsed,
    layout.value.compare,
    layout.value.primaryStudy,
    layout.value.secondaryStudy,
    layout.value.priceRatio,
    layout.value.secondaryRatio,
  ],
  () => {
  try {
    localStorage.setItem("edge-relative:chart-layout", serializeLayout(layout.value));
  } catch {
    /* Presentation preferences are optional when browser storage is unavailable. */
  }
  },
);
onBeforeUnmount(() => {
  mounted = false;
  chartRequests.invalidate();
  socket?.close();
  if (retry) clearTimeout(retry);
});
function rowTime(row: Row) {
  return et(row.candle_time);
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
    <div class="main" :class="{ 'main-chart': view === 'chart' }">
      <header>
        <div class="title">
          <strong>EDGE RELATIVE</strong><span class="divider"></span
          ><span>Market workspace</span><span class="poc">POC</span>
        </div>
        <div class="connection">
          <Wifi :size="14" /><span
            :class="{ good: status?.feed === 'connected' }"
            >Schwab ·
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
        <div v-if="view === 'scanner'" class="date-controls">
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
      <div v-if="error && view === 'scanner'" class="error" role="alert">
        <strong>Unable to complete request</strong><span>{{ error }}</span
        ><button aria-label="Dismiss error" @click="error = ''">×</button>
      </div>
      <div v-if="status && !status.configured && view === 'scanner'" class="setup-banner">
        <Activity :size="18" />
        <div>
          <strong>Connect Schwab to get started</strong
          ><span
            >Add your Schwab credentials to the backend environment and restart.
            Your keys stay on the server.</span
          >
        </div>
      </div>
      <template v-if="view === 'scanner'">
        <section class="intro">
          <div>
            <div class="eyebrow">US EQUITIES / COMPLETED 5-MINUTE CANDLES</div>
            <h1>Find the relative edge<span>.</span></h1>
            <p>
              One universe. Both directions. Every observation backed by its
              chart.
            </p>
          </div>
          <div class="run-meta">
            <span class="muted small">Last completed candle · ET</span
            ><b>{{
              snapshot
                ? et(Date.parse(snapshot.as_of) / 1000)
                : "Awaiting Schwab data"
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
                  <th>Last close $</th>
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
                    ><small>{{ rowTime(row) }} ET</small>
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
                  : "Fetch Schwab history to calculate the five studies. No values are shown until data is available."
              }}
            </p>
            <UiButton v-if="!snapshot" primary :busy="busy" @click="fetchData"
              >Fetch Schwab history <ArrowUpRight :size="14"
            /></UiButton>
          </div>
          <div class="panel-footer">
            <span
              >{{ filtered.length }} instruments · directional
              observations</span
            ><span
              >{{ snapshot?.price_benchmark || "SPY" }} price benchmark ·
              {{ snapshot?.volume_benchmark || "SPY" }} volume proxy</span
            >
          </div>
        </section>
      </template>
      <ChartWorkspace
        v-else
        :data="chart"
        :selected-symbol="selected"
        :rows="snapshot?.rows || []"
        :snapshot="snapshot"
        :status="status"
        :catalog-available="catalogAvailable"
        :transport="transport"
        :quote="status?.feed === 'connected' && selected ? quotes[selected] : undefined"
        :loading="chartLoading"
        :request-error="chartError"
        :busy="busy"
        :live-mode="live"
        :layout="layout"
        @update:layout="layout = $event"
        @select-symbol="openChart"
        @fetch="fetchData"
        @settings="details = true"
        @toggle-live="live = $event"
        @scanner="view = 'scanner'; details = !catalogAvailable"
      />
      <footer v-if="view === 'scanner'">
        <span
          ><span class="dot"></span
          >{{ status?.message || "Connecting to backend…" }}</span
        ><span>Research observations · America/New_York</span>
      </footer>
    </div>
    <DialogRoot :open="details" @update:open="details = $event">
      <DialogPortal>
        <DialogOverlay class="overlay" />
        <DialogContent class="dialog" aria-labelledby="settings-title">
        <div class="dialog-heading">
          <DialogTitle id="settings-title">Workspace & data quality</DialogTitle>
          <DialogClose as-child>
            <button class="icon-button" aria-label="Close settings">
            <X :size="20" />
          </button>
          </DialogClose>
        </div>
        <DialogDescription class="muted">
          Instrument identities are resolved against Schwab's instrument lookup and saved
          for future runs.
        </DialogDescription>
        <UiButton :busy="busy" @click="sync"
          ><RefreshCw :size="14" />Sync instrument identities</UiButton
        >
        <div class="catalog">
          <div v-for="i in catalog" :key="i.symbol">
            <strong>{{ i.symbol }}</strong
            ><span>{{ i.kind }}</span
            ><span class="muted">{{
              i.schwab_symbol || "Awaiting resolution"
            }}</span>
          </div>
        </div>
        <div class="settings-form">
          <template v-if="view === 'chart'">
            <label>
              Fetch start date
              <input type="date" v-model="start" aria-label="Chart scan start date" />
            </label>
            <label>
              Fetch end date
              <input type="date" v-model="end" aria-label="Chart scan end date" />
            </label>
            <label class="settings-inline-switch">
              Include live feed on the next fetch
              <input type="checkbox" v-model="live" />
            </label>
            <UiButton primary :busy="busy" @click="fetchData">
              <RefreshCw :size="14" /> Fetch confirmed history
            </UiButton>
            <UiButton @click="view = 'scanner'; details = false">
              <Table2 :size="14" /> Open full scanner
            </UiButton>
          </template>
          <label
            >Price benchmark<select v-model="priceBenchmark">
              <option
                v-for="i in catalog.filter(
                  (i) => (i.kind === 'index' || i.kind === 'etf') && i.enabled,
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
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </div>
</template>
