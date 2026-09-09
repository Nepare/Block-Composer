import { useEffect, useState } from "react";
import { toast } from "sonner";
import { startCompose, type ComposeStartPayload, type ResultDetail } from "@/features/compose/api";
import { BlockPickerDialog } from "@/features/compose/BlockPickerDialog";
import type { DisplayMode } from "@/features/compose/types";
import type { UseComposeJobResult } from "@/features/compose/useComposeJob";
import { Button } from "@/shared/ui/button";
import { Checkbox } from "@/shared/ui/checkbox";
import { Input } from "@/shared/ui/input";
import { Label } from "@/shared/ui/label";
import { Slider } from "@/shared/ui/slider";
import { Spinner } from "@/shared/ui/Spinner";
import { Textarea } from "@/shared/ui/textarea";

const MIN_COUNT = 1;
const MAX_COUNT = 20;
const DEFAULT_COUNT = 5;

interface SpecificationsPanelProps {
  composeJob: UseComposeJobResult;
  displayMode?: DisplayMode;
  historyDetail?: ResultDetail | null;
  selectedBlockIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
}

export function SpecificationsPanel({
  composeJob,
  displayMode = { type: "fresh" },
  historyDetail = null,
  selectedBlockIds = [],
  onSelectionChange = () => {},
}: SpecificationsPanelProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [specifiers, setSpecifiers] = useState("");
  const [count, setCount] = useState(DEFAULT_COUNT);
  const [countUnknown, setCountUnknown] = useState(false);
  const [restrictGenerate, setRestrictGenerate] = useState(false);
  const [restrictMutate, setRestrictMutate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const isHistory = displayMode.type === "history";
  const isRunning = composeJob.status === "running";
  const hasSelection = selectedBlockIds.length > 0;
  const maxCount = hasSelection ? selectedBlockIds.length : MAX_COUNT;
  const canSubmit = description.trim().length > 0 && !isRunning && !submitting;

  // A fresh block selection forces the count to its cap, per FR-031 ("defaults to that
  // number"); shrinking/growing the selection re-syncs it the same way.
  useEffect(() => {
    if (hasSelection) setCount(selectedBlockIds.length);
  }, [hasSelection, selectedBlockIds.length]);

  useEffect(() => {
    if (hasSelection) setRestrictGenerate(false);
  }, [hasSelection]);

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const payload: ComposeStartPayload = { request: description.trim() };
      if (name.trim()) payload.name = name.trim();
      if (specifiers.trim()) payload.specifiers = specifiers.trim();
      if (!countUnknown) payload.count = count;
      if (restrictGenerate) payload.restrict_generate = true;
      if (restrictMutate) payload.restrict_mutate = true;
      if (hasSelection) payload.from_block_ids = selectedBlockIds;

      const response = await startCompose(payload);
      if (!response.ok) {
        toast.error("Failed to start the composition.");
        return;
      }
      const { job_id } = (await response.json()) as { job_id: string };
      composeJob.start(job_id);
    } finally {
      setSubmitting(false);
    }
  }

  if (isHistory) {
    return (
      <div className="flex flex-col gap-5 p-6">
        <h2 className="text-sm font-semibold">Specifications</h2>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="compose-name">Name</Label>
          <Input id="compose-name" value={historyDetail?.name ?? ""} disabled readOnly />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="compose-description">Description</Label>
          <Textarea id="compose-description" value={historyDetail?.request ?? ""} disabled readOnly />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="compose-specifiers">Specifiers</Label>
          <Textarea id="compose-specifiers" value="" disabled readOnly />
        </div>
        <div className="flex flex-col gap-2">
          <Label>Project count{historyDetail && `: ${historyDetail.slots.length}`}</Label>
          <Slider value={[historyDetail?.slots.length ?? 0]} min={MIN_COUNT} max={MAX_COUNT} step={1} disabled />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 p-6">
      <h2 className="text-sm font-semibold">Specifications</h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="compose-name">Name</Label>
        <Input
          id="compose-name"
          placeholder="Optional — auto-generated if left blank"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="compose-description">Description</Label>
        <Textarea
          id="compose-description"
          placeholder="Describe the composition you want"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="compose-specifiers">Specifiers</Label>
        <Textarea
          id="compose-specifiers"
          placeholder="Optional additional constraints"
          value={specifiers}
          onChange={(event) => setSpecifiers(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label>Project count{!countUnknown && `: ${count}`}</Label>
        <Slider
          value={[count]}
          onValueChange={(value) => setCount(Array.isArray(value) ? value[0] : value)}
          min={MIN_COUNT}
          max={maxCount}
          step={1}
          disabled={countUnknown}
        />
        <Label className="font-normal text-muted-foreground">
          <Checkbox checked={countUnknown} onCheckedChange={(checked) => setCountUnknown(checked)} />
          I don't know
        </Label>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" className="flex-1 justify-start" onClick={() => setPickerOpen(true)}>
            {hasSelection ? `Selected ${selectedBlockIds.length} block${selectedBlockIds.length === 1 ? "" : "s"}` : "Select exact blocks"}
          </Button>
          {hasSelection && (
            <Button
              type="button"
              variant="outline"
              className="border-2 border-destructive text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => onSelectionChange([])}
            >
              Clear selection
            </Button>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {!hasSelection && (
          <Label className="font-normal">
            <Checkbox checked={restrictGenerate} onCheckedChange={(checked) => setRestrictGenerate(checked)} />
            Restrict generation
          </Label>
        )}
        <Label className="font-normal">
          <Checkbox checked={restrictMutate} onCheckedChange={(checked) => setRestrictMutate(checked)} />
          Restrict mutation
        </Label>
      </div>
      {isRunning ? (
        <Button type="button" variant="outline" onClick={() => composeJob.cancel()}>
          Cancel
        </Button>
      ) : (
        <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
          {submitting && <Spinner />}
          Compose
        </Button>
      )}
      <BlockPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        initialSelectedIds={selectedBlockIds}
        onDone={(ids) => {
          onSelectionChange(ids);
          setPickerOpen(false);
        }}
      />
    </div>
  );
}
