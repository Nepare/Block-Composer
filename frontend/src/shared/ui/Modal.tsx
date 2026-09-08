import type { ReactNode } from "react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog"

interface ModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: string
  contentClassName?: string
  children?: ReactNode
}

function Modal({ open, onOpenChange, title, description, contentClassName, children }: ModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={contentClassName}>
        <DialogHeader className="border-b pb-4">
          <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}

export { Modal }
