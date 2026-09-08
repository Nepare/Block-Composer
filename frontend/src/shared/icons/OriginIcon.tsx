import { cn } from "cn"

export type BlockOrigin = "dissected" | "mutated" | "generated" | "manual"

const ORIGIN_BADGES: Record<BlockOrigin, { emoji: string; label: string; className: string; ringClassName: string }> = {
  dissected: {
    emoji: "🌐",
    label: "Dissected",
    className: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
    ringClassName: "border-r-blue-500/50 border-b-blue-500/50 border-l-blue-500/50",
  },
  mutated: {
    emoji: "♻️",
    label: "Mutated",
    className: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
    ringClassName: "border-r-cyan-500/50 border-b-cyan-500/50 border-l-cyan-500/50",
  },
  generated: {
    emoji: "🌱",
    label: "Generated",
    className: "bg-green-500/15 text-green-700 dark:text-green-300",
    ringClassName: "border-r-green-500/50 border-b-green-500/50 border-l-green-500/50",
  },
  manual: {
    emoji: "✏️",
    label: "Manual",
    className: "bg-slate-500/15 text-slate-700 dark:text-slate-300",
    ringClassName: "border-r-slate-500/50 border-b-slate-500/50 border-l-slate-500/50",
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

function GeneratingSpinner({ origin, className }: OriginIconProps) {
  const badge = ORIGIN_BADGES[origin]
  return (
    <span
      className={cn("relative inline-flex size-9 shrink-0 items-center justify-center", className)}
    >
      <span
        className={cn("absolute inset-0 animate-spin rounded-full border-2 border-t-transparent", badge.ringClassName)}
        aria-hidden="true"
      />
      <span role="img" aria-label={badge.label} title={badge.label} className="text-sm select-none">
        {badge.emoji}
      </span>
    </span>
  )
}

export { OriginIcon, GeneratingSpinner }
