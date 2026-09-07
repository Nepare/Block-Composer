import { cn } from "cn"

export type BlockOrigin = "dissected" | "mutated" | "generated"

const ORIGIN_BADGES: Record<BlockOrigin, { emoji: string; label: string; className: string }> = {
  dissected: {
    emoji: "🌐",
    label: "Dissected",
    className: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  },
  mutated: {
    emoji: "♻️",
    label: "Mutated",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  generated: {
    emoji: "🌱",
    label: "Generated",
    className: "bg-green-500/10 text-green-700 dark:text-green-300",
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
        "inline-flex size-6 items-center justify-center rounded-full text-sm",
        badge.className,
        className
      )}
    >
      {badge.emoji}
    </span>
  )
}

export { OriginIcon }
