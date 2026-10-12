import { test } from "node:test";
import assert from "node:assert/strict";
import { createChartTheme } from "./chart-theme.ts";

test("the Lightweight Charts adapter resolves semantic Neutral and financial tokens", () => {
  const values: Record<string, string> = {
    "--background": "oklch(0.145 0 0)",
    "--foreground": "oklch(0.985 0 0)",
    "--muted-foreground": "oklch(0.708 0 0)",
    "--border": "oklch(1 0 0 / 10%)",
    "--chart-grid": "oklch(1 0 0 / 6%)",
    "--chart-crosshair": "oklch(0.78 0 0 / 55%)",
    "--accent": "oklch(0.371 0 0)",
    "--bullish": "oklch(0.72 0.16 162)",
    "--bearish": "oklch(0.69 0.19 18)",
    "--chart-rrs": "oklch(0.79 0.13 210)",
    "--chart-rrv": "oklch(0.77 0.12 300)",
    "--chart-volatility": "oklch(0.79 0.15 86)",
    "--chart-sector": "oklch(0.76 0.13 250)",
    "--chart-ema-fast": "oklch(0.75 0.13 250)",
    "--chart-ema-slow": "oklch(0.79 0.15 86)",
  };
  const theme = createChartTheme((token) => values[token] ?? "", (color) => color);
  assert.equal(theme.background, values["--background"]);
  assert.equal(theme.grid, values["--chart-grid"]);
  assert.equal(theme.bullish, values["--bullish"]);
  assert.equal(theme.crosshairLabel, values["--accent"]);
});

test("legacy shadcn HSL channel values are converted to valid CSS colors", () => {
  const values: Record<string, string> = {
    "--background": "0 0% 3.9%",
    "--foreground": "0 0% 98%",
    "--muted-foreground": "0 0% 63.9%",
    "--border": "0 0% 14.9%",
    "--chart-grid": "0 0% 20%",
    "--chart-crosshair": "0 0% 60%",
    "--accent": "0 0% 14.9%",
    "--bullish": "oklch(0.72 0.16 162)",
    "--bearish": "oklch(0.69 0.19 18)",
    "--chart-rrs": "oklch(0.79 0.13 210)",
    "--chart-rrv": "oklch(0.77 0.12 300)",
    "--chart-volatility": "oklch(0.79 0.15 86)",
    "--chart-sector": "oklch(0.76 0.13 250)",
    "--chart-ema-fast": "oklch(0.75 0.13 250)",
    "--chart-ema-slow": "oklch(0.79 0.15 86)",
  };
  const theme = createChartTheme((token) => values[token] ?? "", (color) => color);
  assert.equal(theme.background, "hsl(0 0% 3.9%)");
  assert.equal(theme.crosshairLabel, "hsl(0 0% 14.9%)");
  assert.equal(theme.bullish, values["--bullish"]);
});
