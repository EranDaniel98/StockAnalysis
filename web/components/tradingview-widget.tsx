"use client";

import { useEffect, useRef } from "react";

/**
 * Generic TradingView external-embedding widget host.
 *
 * TradingView's free widgets ship as a <script> whose JSON config lives in its
 * innerHTML; the script renders into a sibling container div. We recreate that
 * structure imperatively so React owns the lifecycle (clean teardown on symbol
 * change / unmount / HMR). These are iframes — display-only, not wired to our
 * data, and TradingView attribution stays in the rendered widget.
 */
export function TradingViewWidget({
  scriptSrc,
  config,
  height = 500,
}: {
  scriptSrc: string;
  config: Record<string, unknown>;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const configKey = JSON.stringify(config);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';
    const script = document.createElement("script");
    script.src = scriptSrc;
    script.async = true;
    script.type = "text/javascript";
    script.innerHTML = JSON.stringify({
      autosize: true,
      theme: "dark",
      ...config,
    });
    container.appendChild(script);
    return () => {
      container.innerHTML = "";
    };
    // configKey is the stringified config — depending on `config` directly
    // would re-mount the widget every render on object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptSrc, configKey]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container overflow-hidden rounded-md border border-border/60"
      style={{ height, width: "100%" }}
    />
  );
}

/** Full interactive price chart for one symbol. */
export function TradingViewChart({
  symbol,
  height = 520,
}: {
  symbol: string;
  height?: number;
}) {
  return (
    <TradingViewWidget
      height={height}
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
      config={{
        symbol,
        interval: "D",
        timezone: "Etc/UTC",
        style: "1",
        locale: "en",
        allow_symbol_change: true,
        hide_side_toolbar: false,
        withdateranges: true,
        calendar: false,
        support_host: "https://www.tradingview.com",
      }}
    />
  );
}

/** Reported financials (income / balance-sheet / cash-flow) for one symbol.
 * Display-only TradingView data — actuals as filed, NOT a forecast. */
export function TradingViewFinancials({
  symbol,
  height = 460,
}: {
  symbol: string;
  height?: number;
}) {
  return (
    <TradingViewWidget
      height={height}
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-financials.js"
      config={{
        symbol,
        displayMode: "regular",
        width: "100%",
        colorTheme: "dark",
        isTransparent: true,
        largeChartUrl: "",
        locale: "en",
      }}
    />
  );
}

/** Company description / sector / basic profile for one symbol (display-only). */
export function TradingViewProfile({
  symbol,
  height = 380,
}: {
  symbol: string;
  height?: number;
}) {
  return (
    <TradingViewWidget
      height={height}
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-symbol-profile.js"
      config={{
        symbol,
        width: "100%",
        colorTheme: "dark",
        isTransparent: true,
        locale: "en",
      }}
    />
  );
}

/** Oscillator + moving-average "buy/sell/neutral" gauge for one symbol. */
export function TradingViewTechnicals({
  symbol,
  height = 420,
}: {
  symbol: string;
  height?: number;
}) {
  return (
    <TradingViewWidget
      height={height}
      scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js"
      config={{
        symbol,
        interval: "1D",
        width: "100%",
        isTransparent: true,
        showIntervalTabs: true,
        displayMode: "single",
        locale: "en",
      }}
    />
  );
}
