import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createDefaultLayout,
  serializeLayout,
  loadLayout,
  selectPrimaryStudy,
  selectSecondaryStudy,
  setCompareMode,
  toggleSidebar,
  setPaneRatio,
  maximizeRegion,
  restoreLayout,
  createRequestGate,
  shouldLoadSnapshot,
  replayView,
  contextBadge,
  studyValue,
  ChartInstanceSlot,
  ResourceScope,
  type WorkspaceLayout,
} from "./workspace-state.ts";

test("choosing a study replaces the primary, and compare never duplicates it", () => {
  const initial = createDefaultLayout();
  assert.equal(initial.primaryStudy, "rrs");
  const selected = selectPrimaryStudy(initial, "rrv");
  assert.equal(selected.primaryStudy, "rrv");
  const comparing = setCompareMode(selected, true);
  assert.equal(comparing.compare, true);
  assert.notEqual(comparing.primaryStudy, comparing.secondaryStudy);
  assert.equal(selectSecondaryStudy(comparing, "rrv").secondaryStudy, "rrs");
  assert.equal(selectSecondaryStudy(comparing, "sector_rrs").secondaryStudy, "sector_rrs");
  assert.equal(selectPrimaryStudy(comparing, "rrv").secondaryStudy, "rrs");
});

test("collapsing the scanner preserves instrument and shared visible range", () => {
  const initial = createDefaultLayout();
  const chart = {
    ...initial,
    selectedSymbol: "TCS",
    visibleRange: { from: 20, to: 50 },
  };
  const collapsed = toggleSidebar(chart);
  assert.equal(collapsed.sidebarCollapsed, true);
  assert.equal(collapsed.selectedSymbol, "TCS");
  assert.deepEqual(collapsed.visibleRange, { from: 20, to: 50 });
});

test("presentation preferences persist without symbol or time-range data", () => {
  const layout = {
    ...createDefaultLayout(),
    selectedSymbol: "TCS",
    visibleRange: { from: 4, to: 24 },
    sidebarCollapsed: true,
  };
  const restored = loadLayout(serializeLayout(layout));
  assert.equal(restored.sidebarCollapsed, true);
  assert.equal(restored.selectedSymbol, undefined);
  assert.equal(restored.visibleRange, undefined);
});

test("resize and maximize/restore preserve selected studies and time range", () => {
  const initial: WorkspaceLayout = {
    ...createDefaultLayout(),
    compare: true,
    primaryStudy: "rrv",
    secondaryStudy: "sector_rrs",
    visibleRange: { from: 8, to: 38 },
  };
  const resized = setPaneRatio(initial, 0.68);
  const maximized = maximizeRegion(resized, "primary");
  assert.equal(maximized.maximizedRegion, "primary");
  const restored = restoreLayout(maximized);
  assert.equal(restored.priceRatio, 0.68);
  assert.equal(restored.compare, true);
  assert.equal(restored.primaryStudy, "rrv");
  assert.equal(restored.secondaryStudy, "sector_rrs");
  assert.deepEqual(restored.visibleRange, { from: 8, to: 38 });
});

test("latest instrument request wins even when an earlier request resolves later", () => {
  const gate = createRequestGate();
  const oldRequest = gate.begin();
  const currentRequest = gate.begin();
  assert.equal(gate.isCurrent(currentRequest), true);
  assert.equal(gate.isCurrent(oldRequest), false);
  gate.invalidate();
  assert.equal(gate.isCurrent(currentRequest), false);
});

test("an empty unconfigured workspace does not request a missing snapshot", () => {
  assert.equal(shouldLoadSnapshot({ snapshot_available: false }), false);
  assert.equal(shouldLoadSnapshot({ snapshot_available: true }), true);
});

test("replay truncates all observations and suppresses the provisional live quote", () => {
  const points = [{ time: 1 }, { time: 2 }, { time: 3 }];
  const view = replayView(points, true, 2, { price: 99, time: 3, provisional: true });
  assert.deepEqual(view.points, points.slice(0, 2));
  assert.equal(view.quote, undefined);
  assert.equal(view.inspectedTime, 2);
});

test("context badges use documented labels and missing context is unavailable", () => {
  const labels = { "0": "Unavailable", "1": "Bull trend", "-1": "Bear trend", "2": "Range", "3": "Transition", "4": "Dislocation" };
  assert.deepEqual(contextBadge(1, labels, "market"), { label: "Bull trend", tone: "bullish" });
  assert.deepEqual(contextBadge(2, labels, "market"), { label: "Range", tone: "caution" });
  assert.deepEqual(contextBadge(null, labels, "market"), { label: "Unavailable", tone: "unavailable" });
  assert.deepEqual(contextBadge(0, { "0": "Neutral", "1": "Strong", "-1": "Weak" }, "sector"), { label: "Neutral", tone: "caution" });
});

test("missing indicator observations render as unavailable, never zero", () => {
  assert.equal(studyValue(null), "Unavailable");
  assert.equal(studyValue(Number.NaN), "Unavailable");
  assert.equal(studyValue(0), "0.00");
});

test("routine updates reuse one chart instance and disposal is idempotent", () => {
  const slot = new ChartInstanceSlot<{ id: number }>();
  let creates = 0;
  const factory = () => ({ id: ++creates });
  const first = slot.ensure(factory);
  assert.equal(slot.ensure(factory), first);
  assert.equal(creates, 1);
  let removes = 0;
  slot.dispose(() => removes++);
  slot.dispose(() => removes++);
  assert.equal(removes, 1);
});

test("cleanup disposes resize observers, subscriptions, and timers exactly once", () => {
  const scope = new ResourceScope();
  const resources = { observer: 0, subscription: 0, timer: 0 };
  scope.add(() => resources.observer++);
  scope.add(() => resources.subscription++);
  scope.add(() => resources.timer++);
  scope.dispose();
  scope.dispose();
  assert.deepEqual(resources, { observer: 1, subscription: 1, timer: 1 });
});
