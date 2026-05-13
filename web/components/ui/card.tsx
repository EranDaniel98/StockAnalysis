import * as React from "react"

import { cn } from "@/lib/utils"

function Card({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"div"> & { size?: "default" | "sm" }) {
  return (
    <div
      data-slot="card"
      data-size={size}
      // Hairline border instead of soft shadow/ring — Bloomberg-style
      // panels are separated by 1px rules, not elevation.
      className={cn(
        "group/card flex flex-col gap-3 overflow-hidden rounded-md border border-border bg-card py-3 text-sm text-card-foreground has-data-[slot=card-footer]:pb-0 has-[>img:first-child]:pt-0 data-[size=sm]:gap-2 data-[size=sm]:py-2 data-[size=sm]:has-data-[slot=card-footer]:pb-0 *:[img:first-child]:rounded-t-md *:[img:last-child]:rounded-b-md",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      // 1px underline rule on headers — matches the grid-style aesthetic.
      // `.border-b` modifier (when caller adds it) gives a stronger rule.
      className={cn(
        "group/card-header @container/card-header grid auto-rows-min items-start gap-1 rounded-t-md border-b border-border px-3 pb-2 group-data-[size=sm]/card:px-2 group-data-[size=sm]/card:pb-1.5 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] [.border-b]:pb-2 group-data-[size=sm]/card:[.border-b]:pb-1.5",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn(
        "font-heading text-sm leading-snug font-medium tracking-tight group-data-[size=sm]/card:text-xs",
        className
      )}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-3 group-data-[size=sm]/card:px-2", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "flex items-center rounded-b-md border-t border-border bg-muted/30 px-3 py-2 group-data-[size=sm]/card:px-2 group-data-[size=sm]/card:py-1.5",
        className
      )}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
