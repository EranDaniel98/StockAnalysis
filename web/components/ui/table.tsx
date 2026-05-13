"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto"
    >
      <table
        data-slot="table"
        // tabular-nums on every table: quant rows must align decimals.
        className={cn(
          "w-full caption-bottom text-xs [font-variant-numeric:tabular-nums]",
          className
        )}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn(
        "[&_tr]:border-b [&_tr]:border-border text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t border-border bg-muted/30 font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({
  className,
  mono,
  ...props
}: React.ComponentProps<"tr"> & { mono?: boolean }) {
  return (
    <tr
      data-slot="table-row"
      data-mono={mono ? "" : undefined}
      // Hairline row divider, low-contrast hover. `mono` prop on a row
      // flips its cells to font-mono (cascades via the data attr below).
      className={cn(
        "border-b border-border/70 transition-colors hover:bg-muted/40 has-aria-expanded:bg-muted/40 data-[state=selected]:bg-muted data-[mono]:font-mono",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      // Headers: uppercase label-style, hairline underline already on
      // the parent <thead> row.
      className={cn(
        "h-8 px-2 text-left align-middle text-[10px] font-medium tracking-wider whitespace-nowrap text-muted-foreground uppercase [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCell({
  className,
  mono,
  ...props
}: React.ComponentProps<"td"> & { mono?: boolean }) {
  return (
    <td
      data-slot="table-cell"
      // Add `mono` to flip a single cell to monospace (e.g. tickers,
      // prices). All cells get tabular-nums via the parent <table>.
      className={cn(
        "px-2 py-1.5 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0",
        mono && "font-mono",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-3 text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
