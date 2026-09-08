import { cn } from "cn"

export type BlockOrigin = "dissected" | "mutated" | "generated" | "manual"

const ORIGIN_BADGES: Record<BlockOrigin, { emoji: string; label: string; className: string }> = {
  dissected: {
    emoji: "🌐",
    label: "Dissected",
    className: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  },
  mutated: {
    emoji: "♻️",
    label: "Mutated",
    className: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
  },
  generated: {
    emoji: "🌱",
    label: "Generated",
    className: "bg-green-500/15 text-green-700 dark:text-green-300",
  },
  manual: {
    emoji: "✏️",
    label: "Manual",
    className: "bg-slate-500/15 text-slate-700 dark:text-slate-300",
  },
}

interface OriginIconProps {
  origin: BlockOrigin
  className?: string
}

function OriginIcon({ origin, className }: OriginIconProps) {
  const badge = ORIGIN_BADGES[origin]
  return (
    <span
      role="img"
      aria-label={badge.label}
      title={badge.label}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-xl text-base select-none",
        badge.className,
        className
      )}
    >
      {badge.emoji}
    </span>
  )
}

export { OriginIcon }
