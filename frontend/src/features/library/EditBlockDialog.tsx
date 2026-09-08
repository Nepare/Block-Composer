import { useEffect, useState, type ClipboardEvent, type FormEvent } from "react";
import { toast } from "sonner";
import { getBlock, updateBlock, type BlockDetail } from "@/features/library/api";
import { looksLikeWholeBlock, splitBlockBody } from "@/features/library/blockFields";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Spinner } from "@/shared/ui/Spinner";

interface EditBlockDialogProps {
  blockId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (block: BlockDetail) => void;
}

interface FormState {
  name: string;
  description: string;
  metadata: string;
}

const EMPTY_FORM: FormState = { name: "", description: "", metadata: "" };

function buildBody(form: FormState): string {
  return [`# ${form.name}`, form.description, form.metadata].filter(Boolean).join("\n\n");
}

const textareaClassName =
  "min-h-64 w-full flex-1 resize-y rounded-xl border border-input bg-transparent px-3 py-2 font-mono text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

export function EditBlockDialog({ blockId, open, onOpenChange, onSaved }: EditBlockDialogProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      const detail = await getBlock(blockId);
      if (cancelled) return;
      setForm(splitBlockBody(detail.body));
      setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [open, blockId]);

  function reset() {
    setForm(EMPTY_FORM);
    setError(null);
  }

  function handleNamePaste(event: ClipboardEvent<HTMLInputElement>) {
    const text = event.clipboardData.getData("text");
    if (!looksLikeWholeBlock(text)) return;
    event.preventDefault();
    setForm(splitBlockBody(text));
    toast.info("Detected a whole block — distributed its content across Name, Description, and Details.");
  }

  async function handleCopyFullBlock() {
    await navigator.clipboard.writeText(buildBody(form));
    toast.success("Copied the full block to the clipboard.");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const response = await updateBlock(blockId, { body: buildBody(form) });
      if (!response.ok) {
        setError("Could not save changes. Please try again.");
        return;
      }
      const updated = await getBlock(blockId);
      onSaved?.(updated);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="Edit block"
      description="Description and Details are raw markdown — edit them directly. Paste a whole block into Name to redistribute it."
      contentClassName="sm:max-w-4xl"
    >
      {loading ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Loading...
        </p>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div className="flex h-full flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label htmlFor="edit-block-name" className="text-sm font-medium">
                  Name
                </label>
                <Input
                  id="edit-block-name"
                  value={form.name}
                  onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  onPaste={handleNamePaste}
                />
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-1">
                <label htmlFor="edit-block-description" className="text-sm font-medium">
                  Description
                </label>
                <textarea
                  id="edit-block-description"
                  value={form.description}
                  onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
                  className={textareaClassName}
                />
              </div>
            </div>
            <div className="flex h-full flex-col gap-1">
              <label htmlFor="edit-block-metadata" className="text-sm font-medium">
                Details (Role, Time Period, Environment, Responsibilities, ...)
              </label>
              <textarea
                id="edit-block-metadata"
                value={form.metadata}
                onChange={(event) => setForm((prev) => ({ ...prev, metadata: event.target.value }))}
                className={textareaClassName}
              />
            </div>
          </div>
          {error && <p className="rounded-xl bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</p>}
          <div className="flex items-center justify-between gap-2">
            <Button type="button" variant="ghost" onClick={handleCopyFullBlock}>
              Copy full block
            </Button>
            <Button type="submit" disabled={saving}>
              Save
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
