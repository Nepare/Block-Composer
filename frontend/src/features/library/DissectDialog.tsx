import { useState, type FormEvent } from "react";
import { startDissect } from "@/features/library/api";
import * as session from "@/shared/session";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

// Mirrors docs_api.resolve_doc_id's accepted shapes: a URL containing "/document/d/<id>",
// or a bare id-looking string, since the backend does its own extraction either way.
const DOC_URL_RE = /\/document\/d\/[a-zA-Z0-9_-]+/;
const BARE_ID_RE = /^[a-zA-Z0-9_-]{10,}$/;

function isValidDocReference(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  return DOC_URL_RE.test(trimmed) || BARE_ID_RE.test(trimmed);
}

interface DissectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onJobStarted: (jobId: string, preserveRequested: boolean) => void;
}

export function DissectDialog({ open, onOpenChange, onJobStarted }: DissectDialogProps) {
  const [doc, setDoc] = useState("");
  const [preserve, setPreserve] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = isValidDocReference(doc);

  function reset() {
    setDoc("");
    setPreserve(true);
    setError(null);
  }

  function handleConnect() {
    const url = `/auth/google/login?key=${encodeURIComponent(session.get() ?? "")}`;
    window.open(url, "_blank");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!valid || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const response = await startDissect({ doc });
      if (!response.ok) {
        setError("Could not start the import. Please try again.");
        return;
      }
      const { job_id } = (await response.json()) as { job_id: string };
      onJobStarted(job_id, preserve);
      reset();
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="Populate from Google Docs"
      description="Import blocks from a Google Doc. Closing this dialog does not stop the import."
    >
      <div className="flex flex-col gap-4">
        <Button type="button" variant="outline" onClick={handleConnect}>
          Connect Google Account
        </Button>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="dissect-doc" className="text-sm font-medium">
              Document link or ID
            </label>
            <Input
              id="dissect-doc"
              value={doc}
              onChange={(event) => setDoc(event.target.value)}
              placeholder="https://docs.google.com/document/d/..."
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={preserve}
              onChange={(event) => setPreserve(event.target.checked)}
              className="size-4 rounded border-input"
            />
            Add as preserved
          </label>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={!valid || submitting}>
            Populate
          </Button>
        </form>
      </div>
    </Modal>
  );
}
