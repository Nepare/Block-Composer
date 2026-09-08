import { useEffect, useState, type FormEvent } from "react";
import { getBlock, startGenerate, startMutate, type BlockDetail } from "@/features/library/api";
import type { LibraryBlockRecord } from "@/features/library/BlockTile";
import type { JobKind } from "@/features/library/useLibraryJobs";
import { Modal } from "@/shared/ui/Modal";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

interface GenerateMutateDialogBaseProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onJobStarted: (kind: JobKind, jobId: string) => void;
}

interface GenerateDialogProps extends GenerateMutateDialogBaseProps {
  mode: "generate";
}

interface MutateDialogProps extends GenerateMutateDialogBaseProps {
  mode: "mutate";
  sourceBlock: LibraryBlockRecord;
}

type GenerateMutateDialogProps = GenerateDialogProps | MutateDialogProps;

export function GenerateMutateDialog(props: GenerateMutateDialogProps) {
  const { mode, open, onOpenChange, onJobStarted } = props;
  const [criteria, setCriteria] = useState("");
  const [name, setName] = useState("");
  const [preserve, setPreserve] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceDetail, setSourceDetail] = useState<BlockDetail | null>(null);

  const sourceBlockId = props.mode === "mutate" ? props.sourceBlock.id : null;

  useEffect(() => {
    if (!open || !sourceBlockId) return;
    let cancelled = false;
    getBlock(sourceBlockId).then((detail) => {
      if (!cancelled) setSourceDetail(detail);
    });
    return () => {
      cancelled = true;
    };
  }, [open, sourceBlockId]);

  function reset() {
    setCriteria("");
    setName("");
    setPreserve(false);
    setSourceDetail(null);
    setError(null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmedCriteria = criteria.trim();
    if (!trimmedCriteria || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const response =
        props.mode === "mutate"
          ? await startMutate({
              block_id: props.sourceBlock.id,
              criteria: trimmedCriteria,
              name: name.trim() || undefined,
              preserve,
            })
          : await startGenerate({
              criteria: trimmedCriteria,
              name: name.trim() || undefined,
              preserve,
            });
      if (!response.ok) {
        setError(`Could not start ${mode === "mutate" ? "mutation" : "generation"}. Please try again.`);
        return;
      }
      const { job_id } = (await response.json()) as { job_id: string };
      onJobStarted(mode, job_id);
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
      title={mode === "mutate" ? "Mutate a block" : "Generate a block"}
      description={
        mode === "mutate"
          ? "Describe the change. The result appears in the library shortly after you submit."
          : "Describe what you want. It appears in the library shortly after you submit."
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        {props.mode === "mutate" && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Source block
            </span>
            <div className="rounded-xl border bg-muted/50 px-3.5 py-2.5">
              <p className="text-sm font-semibold">{props.sourceBlock.name}</p>
            </div>
            <textarea
              readOnly
              disabled
              value={sourceDetail?.body ?? ""}
              aria-label="Source block content"
              className="min-h-24 w-full rounded-xl border border-input bg-muted px-3 py-2 text-sm text-muted-foreground"
            />
          </div>
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor="generate-criteria" className="text-sm font-medium">
            Criteria
          </label>
          <textarea
            id="generate-criteria"
            required
            value={criteria}
            onChange={(event) => setCriteria(event.target.value)}
            className="min-h-20 w-full rounded-xl border border-input bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            placeholder="What should this block describe?"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="generate-name" className="text-sm font-medium">
            Name (optional)
          </label>
          <Input id="generate-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={preserve}
            onChange={(event) => setPreserve(event.target.checked)}
            className="size-4 rounded border-input accent-primary"
          />
          Preserve immediately
        </label>
        {error && <p className="rounded-xl bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={!criteria.trim() || submitting} className="w-full">
          {mode === "mutate" ? "Mutate" : "Generate"}
        </Button>
      </form>
    </Modal>
  );
}
