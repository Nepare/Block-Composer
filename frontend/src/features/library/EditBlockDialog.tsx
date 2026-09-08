import { useEffect, useState, type ClipboardEvent, type FormEvent } from "react";
import { toast } from "sonner";
import { getBlock, updateBlock, type BlockDetail } from "@/features/library/api";
import {
  looksLikeWholeBlock,
  parseBlockBody,
  reassembleBlockBody,
  titleCaseLabel,
  type EditFormFields,
} from "@/features/library/blockFields";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

interface EditBlockDialogProps {
  blockId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (block: BlockDetail) => void;
}

interface FormState {
  name: string;
  description: string;
  role: string;
  timePeriod: string;
  environment: string;
  otherFields: Record<string, string[] | string>;
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  role: "",
  timePeriod: "",
  environment: "",
  otherFields: {},
};

function toFormState(fields: EditFormFields): FormState {
  return {
    name: fields.name,
    description: fields.description,
    role: fields.role ?? "",
    timePeriod: fields.timePeriod ?? "",
    environment: fields.environment.join(", "),
    otherFields: fields.otherFields,
  };
}

function toEditFields(form: FormState): EditFormFields {
  return {
    name: form.name,
    description: form.description,
    role: form.role.trim() || null,
    timePeriod: form.timePeriod.trim() || null,
    environment: form.environment
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
    otherFields: form.otherFields,
  };
}

function otherFieldToText(value: string[] | string): string {
  return Array.isArray(value) ? value.join("\n") : value;
}

const textareaClassName =
  "min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

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
      setForm(toFormState(parseBlockBody(detail.body)));
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

  function distribute(text: string) {
    setForm(toFormState(parseBlockBody(text)));
    toast.info("Detected a whole block — distributed its content across every field.");
  }

  function handlePaste(event: ClipboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    const text = event.clipboardData.getData("text");
    if (!looksLikeWholeBlock(text)) return;
    event.preventDefault();
    distribute(text);
  }

  async function handleCopyFullBlock() {
    const body = reassembleBlockBody(toEditFields(form));
    await navigator.clipboard.writeText(body);
    toast.success("Copied the full block to the clipboard.");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body = reassembleBlockBody(toEditFields(form));
      const response = await updateBlock(blockId, { body });
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

  const otherFieldEntries = Object.entries(form.otherFields);

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="Edit block"
      description="Each piece of content has its own field. Copy or paste the whole block at once from any field."
    >
      {loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-block-name" className="text-sm font-medium">
              Name
            </label>
            <Input
              id="edit-block-name"
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              onPaste={handlePaste}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-block-description" className="text-sm font-medium">
              Description
            </label>
            <textarea
              id="edit-block-description"
              value={form.description}
              onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
              onPaste={handlePaste}
              className={textareaClassName}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-block-role" className="text-sm font-medium">
              Role
            </label>
            <Input
              id="edit-block-role"
              value={form.role}
              onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))}
              onPaste={handlePaste}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-block-time-period" className="text-sm font-medium">
              Time Period
            </label>
            <Input
              id="edit-block-time-period"
              value={form.timePeriod}
              onChange={(event) => setForm((prev) => ({ ...prev, timePeriod: event.target.value }))}
              onPaste={handlePaste}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-block-environment" className="text-sm font-medium">
              Environment (comma-separated)
            </label>
            <Input
              id="edit-block-environment"
              value={form.environment}
              onChange={(event) => setForm((prev) => ({ ...prev, environment: event.target.value }))}
              onPaste={handlePaste}
            />
          </div>
          {otherFieldEntries.map(([key, value]) => (
            <div key={key} className="flex flex-col gap-1">
              <label htmlFor={`edit-block-other-${key}`} className="text-sm font-medium">
                {titleCaseLabel(key)}
              </label>
              <textarea
                id={`edit-block-other-${key}`}
                value={otherFieldToText(value)}
                onChange={(event) => {
                  const text = event.target.value;
                  setForm((prev) => ({
                    ...prev,
                    otherFields: {
                      ...prev.otherFields,
                      [key]: Array.isArray(prev.otherFields[key]) ? text.split("\n") : text,
                    },
                  }));
                }}
                onPaste={handlePaste}
                className={textareaClassName}
              />
            </div>
          ))}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex items-center justify-between gap-2">
            <Button type="button" variant="outline" onClick={handleCopyFullBlock}>
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
