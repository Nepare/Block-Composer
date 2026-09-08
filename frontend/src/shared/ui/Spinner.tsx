import { Loader2 } from "lucide-react"
import { cn } from "cn"

interface SpinnerProps {
  className?: string
}

function Spinner({ className }: SpinnerProps) {
  return <Loader2 className={cn("size-4 animate-spin text-primary", className)} aria-hidden="true" />
}

export { Spinner }
