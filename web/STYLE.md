# StockNew web style guide

Bloomberg-Terminal / financial-quant aesthetic. Dark by default. Light variant works
but is not the showcase.

The token contract is defined in `app/globals.css`. This doc is the consumer cheat
sheet — when reskinning a page, reach for the named utilities here before adding
new colors.

## Principles

- **Dense and grid-style.** Hairline borders separate panels. No shadows. No
  glassmorphism. No gradients.
- **Sharp geometry.** `--radius` is `0.25rem`. Most surfaces use `rounded-sm`
  (4px) or `rounded-md` (about 5px). Avoid `rounded-xl` / `rounded-full` outside
  pill buttons.
- **Tabular nums everywhere.** Every number you render must align decimals. Use
  `.tabular`, `font-mono`, or wrap in `<TableCell>` / `<output>` (handled by the
  base layer in `globals.css`).
- **Mono for numeric data + tickers.** Sans (`font-sans`) for prose, headings,
  labels. Mono (`font-mono`) for prices, returns, scores, tickers, IDs, hashes.

## Color tokens

All colors live in `:root` (light) and `.dark` (dark) blocks in `globals.css`
and are wired through the `@theme inline` block, so Tailwind utilities like
`bg-card`, `text-muted-foreground`, `border-border` work as expected.

### Surfaces

| Token | Tailwind class | Use |
| --- | --- | --- |
| `--background` | `bg-background` | Page background. |
| `--card` | `bg-card` | Panels, dialogs. |
| `--popover` | `bg-popover` | Floating menus, tooltips. |
| `--muted` | `bg-muted` | Subtle backgrounds, hover states, inactive rows. |
| `--accent` | `bg-accent` | Hover/active highlight on interactive items. |
| `--secondary` | `bg-secondary` | Secondary buttons, low-emphasis chips. |
| `--sidebar` | `bg-sidebar` | App-shell left rail. |

### Text

| Token | Tailwind class | Use |
| --- | --- | --- |
| `--foreground` | `text-foreground` | Primary text. |
| `--muted-foreground` | `text-muted-foreground` | Captions, table headers, descriptions. |
| `--card-foreground`, `--popover-foreground`, etc. | matched-pair utilities | Text on the matching surface. |

### Lines and focus

| Token | Tailwind class | Use |
| --- | --- | --- |
| `--border` | `border-border` | Every divider. 1px, low contrast. |
| `--input` | `bg-input` | Input fill (transparent-ish in dark). |
| `--ring` | `ring-ring` / `outline-ring` | Cyan focus ring. |

### Actions

| Token | Tailwind class | Use |
| --- | --- | --- |
| `--primary` (amber) | `bg-primary text-primary-foreground` | Primary CTA. |
| `--destructive` (coral) | `text-destructive`, `bg-destructive/10` | Destructive button, error text. |

### Quant semantic colors (new)

These are the colors quant tables need everywhere. They are wired in both
`@theme inline` and both `:root` variants. The dark variant is slightly
brighter so the colors survive the graphite background.

| Token | Tailwind class | Use |
| --- | --- | --- |
| `--bullish` (mint) | `text-bullish`, `bg-bullish/10`, `border-bullish` | Profit, buy, up-move, positive IC. |
| `--bearish` (coral) | `text-bearish`, `bg-bearish/10`, `border-bearish` | Loss, sell, down-move, drawdown. |
| `--neutral` (graphite) | `text-neutral`, `bg-neutral/10`, `border-neutral` | Flat, no-signal, hold. |

One-liner example:

```tsx
<span
  className={cn(
    "font-mono",
    delta > 0 ? "text-bullish" : delta < 0 ? "text-bearish" : "text-neutral",
  )}
>
  {delta >= 0 ? "+" : ""}{delta.toFixed(2)}%
</span>
```

Or via the new `<Badge>` variants:

```tsx
<Badge variant={delta >= 0 ? "bullish" : "bearish"}>
  {delta.toFixed(2)}%
</Badge>
```

### Charts

Five chart tokens, recolored for quant clarity. Use them in order from `--chart-1`
to `--chart-5` so multi-series charts stay readable when colorblind-mapped.

| Token | Hue | Suggested use |
| --- | --- | --- |
| `--chart-1` | info cyan | Benchmarks, neutral series. |
| `--chart-2` | profit mint | Bullish / equity-up. |
| `--chart-3` | amber | Highlighted series. |
| `--chart-4` | loss coral | Bearish / drawdown. |
| `--chart-5` | neutral graphite | Background / reference lines. |

## Typography

- Headings + labels: `font-sans` (Geist Sans, wired via `--font-geist-sans`).
- Numerics + tickers: `font-mono` (Geist Mono, wired via `--font-geist-mono`).
- Tabular nums: the base layer applies `font-variant-numeric: tabular-nums` to
  `table`, `td`, `th`, `kbd`, `output`, `.tabular`, `.font-mono`, and any
  `[data-tabular]`. If you need tabular nums on a non-mono span, add `.tabular`.

## Component conventions

- **`<Card>`** — 1px border, no shadow. Tight `gap-3`, `py-3`. `<CardHeader>`
  has a 1px bottom rule. Use the `size="sm"` prop for denser dashboards.
- **`<Table>`** — text size `xs`, header is uppercase tracking-wider in
  `text-muted-foreground`. Cells have hairline bottom borders. Pass `mono`
  on a `<TableCell>` or `<TableRow>` for monospace.
- **`<Badge>`** — existing variants preserved. New `bullish` / `bearish` /
  `neutral` variants are tighter (`rounded-sm`), low-saturation tinted bg,
  monospace. Use for P&L deltas, signal direction, regime tags.
- **`<PageHeader>`** — title is `text-xl` semibold, bottom-bordered. Slot
  primary actions into the `actions` prop.

## What not to do

- Don't introduce new colors. If you need a hue, propose a token in this doc.
- Don't use `shadow-*` utilities on panels — borders only.
- Don't use `rounded-xl` / `rounded-2xl` on anything except images.
- Don't render naked numbers in a non-mono, non-tabular context.
- Don't hardcode hex / rgb / oklch values in components.

## When in doubt

Look at `<Card>`, `<Table>`, `<Badge>` in `components/ui/`. They are the canonical
example of how to consume these tokens. Match their density and border style.
