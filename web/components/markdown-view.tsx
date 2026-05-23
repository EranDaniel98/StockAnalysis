import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Minimal markdown renderer for author-controlled report files —
 * handles headings, lists, tables, paragraphs, and inline
 * **bold** / *italic* / `code`. Briefings/watchlists are written
 * by our own pipeline so we skip XSS escaping.
 */
export function MarkdownView({ markdown }: { markdown: string }) {
  // Normalize CRLF and CR to LF first. Pipeline reports are written
  // by Python on Windows so the bytes are \r\n\r\n between blocks;
  // without this normalization the \n\n+ split finds zero matches
  // and the whole document collapses into a single <p>.
  const blocks = markdown
    .replace(/\r\n?/g, "\n")
    .split(/\n\n+/)
    .map((b) => b.trim())
    .filter(Boolean);
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none space-y-2">
      {blocks.map((block, i) => renderBlock(block, i))}
    </div>
  );
}

function renderBlock(block: string, key: number): ReactNode {
  const h = block.match(/^(#{1,6})\s+(.+)$/);
  if (h) {
    const level = h[1].length;
    const text = h[2];
    const Tag = `h${Math.min(level, 4)}` as "h1" | "h2" | "h3" | "h4";
    const sizeClass =
      level === 1 ? "text-xl"
      : level === 2 ? "text-lg"
      : level === 3 ? "text-base"
      : "text-sm";
    return (
      <Tag key={key} className={cn("mt-6 mb-2 font-semibold", sizeClass)}>
        {inline(text)}
      </Tag>
    );
  }
  // Blockquote: every line starts with "> ". Strip the marker, join the
  // remaining text as paragraphs (blank ">" lines act as separators).
  if (block.split("\n").every((l) => /^>\s?/.test(l))) {
    const stripped = block
      .split("\n")
      .map((l) => l.replace(/^>\s?/, ""))
      .join("\n");
    const paragraphs = stripped.split(/\n\s*\n/).filter((p) => p.trim());
    return (
      <blockquote
        key={key}
        className="my-3 border-l-2 border-amber-500/60 bg-amber-500/5 pl-3 py-2 text-sm"
      >
        {paragraphs.map((p, j) => (
          <p key={j} className="my-1 leading-relaxed">
            {inline(p)}
          </p>
        ))}
      </blockquote>
    );
  }
  if (block.includes("|") && block.split("\n")[1]?.includes("---")) {
    return <MdTable key={key} block={block} />;
  }
  if (block.split("\n").every((l) => /^[-*]\s/.test(l))) {
    return (
      <ul key={key} className="my-2 list-disc pl-5">
        {block.split("\n").map((l, j) => (
          <li key={j} className="my-0.5">
            {inline(l.replace(/^[-*]\s+/, ""))}
          </li>
        ))}
      </ul>
    );
  }
  if (block.split("\n").every((l) => /^\d+\.\s/.test(l))) {
    return (
      <ol key={key} className="my-2 list-decimal pl-5">
        {block.split("\n").map((l, j) => (
          <li key={j} className="my-0.5">
            {inline(l.replace(/^\d+\.\s+/, ""))}
          </li>
        ))}
      </ol>
    );
  }
  // Multi-line plain block: preserve line breaks so report sections that
  // use single newlines (e.g. label/value rows) don't collapse onto one
  // line. Block-level split is already on \n\n.
  if (block.includes("\n")) {
    return (
      <p key={key} className="my-2 whitespace-pre-line">
        {inline(block)}
      </p>
    );
  }
  return (
    <p key={key} className="my-2">
      {inline(block)}
    </p>
  );
}

function MdTable({ block }: { block: string }) {
  const lines = block.split("\n");
  if (lines.length < 2) return null;
  const headerCells = lines[0]
    .split("|")
    .map((c) => c.trim())
    .filter(Boolean);
  const bodyLines = lines.slice(2);
  return (
    <table className="my-4 w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border">
          {headerCells.map((h, i) => (
            <th
              key={i}
              className="px-2 py-1 text-left font-semibold text-muted-foreground"
            >
              {inline(h)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {bodyLines.map((line, i) => {
          const cleaned = line
            .replace(/^\||\|$/g, "")
            .split("|")
            .map((c) => c.trim());
          return (
            <tr key={i} className="border-b border-border/50">
              {cleaned.map((c, j) => (
                <td key={j} className="px-2 py-1 align-top">
                  {inline(c)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function inline(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let remaining = text;
  let key = 0;
  const patterns: Array<[RegExp, (m: RegExpMatchArray) => ReactNode]> = [
    [
      /`([^`]+)`/,
      (m) => (
        <code
          key={key}
          className="rounded bg-muted px-1 py-0.5 text-xs"
        >
          {m[1]}
        </code>
      ),
    ],
    [/\*\*([^*]+)\*\*/, (m) => <strong key={key}>{m[1]}</strong>],
    [/\*([^*]+)\*/, (m) => <em key={key}>{m[1]}</em>],
  ];
  while (remaining.length) {
    let earliest: { idx: number; len: number; node: ReactNode } | null = null;
    for (const [re, render] of patterns) {
      const m = remaining.match(re);
      if (!m || m.index === undefined) continue;
      if (earliest === null || m.index < earliest.idx) {
        earliest = { idx: m.index, len: m[0].length, node: render(m) };
      }
    }
    if (!earliest) {
      parts.push(remaining);
      break;
    }
    if (earliest.idx > 0) parts.push(remaining.slice(0, earliest.idx));
    parts.push(earliest.node);
    remaining = remaining.slice(earliest.idx + earliest.len);
    key++;
  }
  return parts;
}
