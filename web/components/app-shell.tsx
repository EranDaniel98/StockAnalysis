"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  Activity,
  BarChart3,
  Briefcase,
  Grid3x3,
  HelpCircle,
  Home,
  LineChart,
  Microscope,
  Search,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";

import { RegimeTile } from "@/components/regime-tile";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

type NavLink = {
  href: string;
  label: string;
  icon: typeof Wallet;
  description: string;
};

const NAV: NavLink[] = [
  {
    href: "/",
    label: "Home",
    icon: Home,
    description: "Today's best plays across every strategy",
  },
  {
    href: "/factors",
    label: "Factors",
    icon: Sparkles,
    description: "Composite-factor daily picks (m+q+v)",
  },
  {
    href: "/portfolio",
    label: "Portfolio",
    icon: Wallet,
    description: "Live Alpaca account + positions",
  },
  {
    href: "/scan",
    label: "Scan",
    icon: Search,
    description: "Trigger a market scan",
  },
  {
    href: "/buy-signals",
    label: "BUY now",
    icon: TrendingUp,
    description: "Live BUY+ signals across every strategy",
  },
  {
    href: "/backtests",
    label: "Backtests",
    icon: BarChart3,
    description: "Run history + tearsheets",
  },
  {
    href: "/diagnose",
    label: "Diagnose",
    icon: Microscope,
    description: "Alphalens IC diagnostic",
  },
  {
    href: "/recommendations",
    label: "Recommendations",
    icon: LineChart,
    description: "Paper-trade recommendation history",
  },
  {
    href: "/sectors",
    label: "Sectors",
    icon: Grid3x3,
    description: "SPDR sector rotation map",
  },
  {
    href: "/help",
    label: "Help",
    icon: HelpCircle,
    description: "Quick start, glossary, FAQ",
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  // Detect Mac vs Windows/Linux for the keyboard-hint label.
  // useSyncExternalStore is the React-recommended hydration-safe pattern
  // for browser-API snapshots: SSR uses the fallback (false → Ctrl), and
  // hydration reads navigator.userAgent so Mac users see ⌘K from first
  // paint without a flash.
  const isMac = useSyncExternalStore(
    () => () => {},
    () => /Mac|iPhone|iPad/i.test(navigator.userAgent),
    () => false,
  );

  // ⌘K / Ctrl+K toggles the palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const [tickerInput, setTickerInput] = useState("");
  const onTickerSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    // Strip anything that isn't an alphanumeric / dot / dash. Tickers like
    // BRK.B or BF-B are valid; arbitrary user input shouldn't reach the URL.
    const clean = t.replace(/[^A-Z0-9.\-]/g, "");
    if (!clean) return;
    setTickerInput("");
    router.push(`/stocks/${clean}`);
  };

  return (
    <div className="flex min-h-screen">
      <aside className="border-border/40 bg-background/50 sticky top-0 hidden h-screen w-64 shrink-0 border-r p-4 md:flex md:flex-col">
        <Link href="/" className="mb-4 flex items-center gap-2 px-2">
          <Activity className="text-primary h-5 w-5" />
          <span className="font-semibold tracking-tight">StockNew</span>
        </Link>

        <form
          onSubmit={onTickerSubmit}
          className="mb-4 flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2 focus-within:border-primary/50"
        >
          <Search className="h-3.5 w-3.5 opacity-50" />
          <input
            type="text"
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
            placeholder="Analyze ticker…"
            spellCheck={false}
            autoCapitalize="characters"
            className="flex-1 bg-transparent py-1.5 font-mono text-xs tracking-wider uppercase placeholder:normal-case placeholder:tracking-normal placeholder:text-muted-foreground/60 focus:outline-none"
          />
          <kbd className="bg-muted/60 rounded px-1 py-0.5 font-mono text-[9px] text-muted-foreground">
            ↵
          </kbd>
        </form>

        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            // Exact match, or current path is a sub-route of this nav
            // item *and* no later (more specific) nav item matches first.
            // Simplest expression: exact, or starts-with + "/". Nested
            // routes (e.g. /research/feed) get their own entry above.
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname === item.href ||
                  pathname.startsWith(item.href + "/");
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "hover:bg-muted/60 flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
                  active && "bg-muted text-foreground font-medium",
                )}
              >
                <Icon className="h-4 w-4 opacity-70" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <Separator className="my-4" />

        <button
          onClick={() => setOpen(true)}
          className="text-muted-foreground hover:bg-muted/60 flex items-center justify-between rounded-md px-2 py-2 text-xs"
        >
          <span className="flex items-center gap-2">
            <Briefcase className="h-3.5 w-3.5" />
            Command palette
          </span>
          <kbd className="bg-muted/60 rounded px-1.5 py-0.5 font-mono text-[10px]">
            {isMac ? "⌘K" : "Ctrl K"}
          </kbd>
        </button>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <header className="border-border/40 bg-background/50 sticky top-0 z-10 flex justify-end gap-2 border-b px-6 py-2 backdrop-blur">
          <RegimeTile />
        </header>
        <div className="mx-auto w-full max-w-7xl px-6 py-8">{children}</div>
      </main>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Search pages or actions…" />
        <CommandList>
          <CommandEmpty>No results.</CommandEmpty>
          <CommandGroup heading="Pages">
            {NAV.map((item) => (
              <CommandItem
                key={item.href}
                onSelect={() => {
                  router.push(item.href);
                  setOpen(false);
                }}
              >
                <item.icon className="mr-2 h-4 w-4" />
                <span>{item.label}</span>
                <span className="text-muted-foreground ml-auto text-xs">
                  {item.description}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </div>
  );
}
