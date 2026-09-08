import { useState } from "react";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  onConfirm: () => void;
  suppressionKey?: string;
}

// Caller decides whether to open this dialog at all (checking `suppressionKey` in
// localStorage beforehand) — this component only persists the preference when told to.
export function ConfirmDialog({ open, onOpenChange, title, description, onConfirm, suppressionKey }: ConfirmDialogProps) {
  const [dontShowAgain, setDontShowAgain] = useState(false);

  function handleOpenChange(next: boolean) {
    if (!next) setDontShowAgain(false);
    onOpenChange(next);
  }

  function handleConfirm() {
    if (suppressionKey && dontShowAgain) {
      try {
        localStorage.setItem(suppressionKey, "true");
      } catch {
        // storage unavailable — the preference just won't persist
      }
    }
    onConfirm();
    handleOpenChange(false);
  }

  return (
    <Modal open={open} onOpenChange={handleOpenChange} title={title} description={description}>
      <div className="flex flex-col gap-4">
        {suppressionKey && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(event) => setDontShowAgain(event.target.checked)}
              className="size-4 rounded border-input"
            />
            Don't show this again
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={handleConfirm}>
            Confirm
          </Button>
        </div>
      </div>
    </Modal>
  );
}
