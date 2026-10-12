export type ChartTheme = {
  background: string;
  foreground: string;
  muted: string;
  border: string;
  grid: string;
  crosshair: string;
  crosshairLabel: string;
  bullish: string;
  bearish: string;
  rrs: string;
  rrv: string;
  volatility: string;
  sector: string;
  emaFast: string;
  emaSlow: string;
};

export type ColorResolver = (cssColor: string) => string;
export type TokenReader = (name: string) => string;

const tokens: Record<keyof ChartTheme, string> = {
  background: "--background",
  foreground: "--foreground",
  muted: "--muted-foreground",
  border: "--border",
  grid: "--chart-grid",
  crosshair: "--chart-crosshair",
  crosshairLabel: "--accent",
  bullish: "--bullish",
  bearish: "--bearish",
  rrs: "--chart-rrs",
  rrv: "--chart-rrv",
  volatility: "--chart-volatility",
  sector: "--chart-sector",
  emaFast: "--chart-ema-fast",
  emaSlow: "--chart-ema-slow",
};

export function createChartTheme(
  readToken: TokenReader,
  resolveColor: ColorResolver,
): ChartTheme {
  return Object.fromEntries(
    Object.entries(tokens).map(([key, token]) => {
      const value = readToken(token).trim();
      if (!value) throw new Error(`Missing chart theme token: ${token}`);
      const cssColor = value.startsWith("--") ? readToken(value) : value;
      const normalized = /^(?:oklch|oklab|color|rgb|rgba|hsl|hsla|lab|lch)\(/i.test(cssColor)
        ? cssColor
        : `hsl(${cssColor})`;
      return [key, resolveColor(normalized)];
    }),
  ) as ChartTheme;
}

/** Convert modern CSS colors (including HSL/OKLCH custom properties) to canvas RGBA. */
export function resolveCssColor(cssColor: string): string {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas color resolution is unavailable");
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = cssColor;
  context.fillRect(0, 0, 1, 1);
  const [red, green, blue, alpha] = context.getImageData(0, 0, 1, 1).data;
  return `rgba(${red}, ${green}, ${blue}, ${(alpha / 255).toFixed(3)})`;
}

export function readChartTheme(root: Element = document.documentElement): ChartTheme {
  const styles = getComputedStyle(root);
  return createChartTheme(
    (token) => styles.getPropertyValue(token),
    resolveCssColor,
  );
}
