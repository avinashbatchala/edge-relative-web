import type { components } from "./generated-api";
export type Snapshot = components["schemas"]["ScanSnapshot"];
export type Row = components["schemas"]["ScannerRow"];
export type ChartData = components["schemas"]["ChartResponse"];
export type Point = components["schemas"]["ChartPoint"];
export type Status = components["schemas"]["Status"];
export type Instrument = components["schemas"]["Instrument"];
export type ScanRequest = components["schemas"]["ScanRequest"];
export type Quote = {
  symbol: string;
  price: number;
  time: number;
  provisional: true;
};
export type Event = {
  schema_version: "1.0";
  sequence: number;
  sent_at: string;
} & (
  | { type: "status"; payload: Status }
  | { type: "snapshot"; payload: Snapshot }
  | { type: "quote"; payload: Quote }
);
