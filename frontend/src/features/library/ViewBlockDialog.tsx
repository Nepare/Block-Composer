import { useEffect, useState } from "react";
import { getBlock } from "@/features/library/api";
import { parseBlockBody, titleCaseLabel, type EditFormFields } from "@/features/library/blockFields";
import { FieldRow, FieldValue } from "@/features/library/FieldDisplay";
import { Modal } from "@/shared/ui/Modal";
import { Spinner } from "@/shared/ui/Spinner";
import { Button } from "@/shared/ui/button";

interface ViewBlockDialogProps {
  blockId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit?: () => void;
}

const EMPTY_FIELDS: EditFormFields = {
  name: "",
  description: "",
  role: null,
  timePeriod: null,
  environment: [],
  otherFields: {},
};

export function ViewBlockDialog({ blockId, open, onOpenChange, onEdit }: ViewBlockDialogProps) {
  const [fields, setFields] = useState<EditFormFields>(EMPTY_FIELDS);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      const detail = await getBlock(blockId);
      if (cancelled) return;
      setFields(parseBlockBody(detail.body));
      setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [open, blockId]);

  const otherFieldEntries = Object.entries(fields.otherFields);

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) setFields(EMPTY_FIELDS);
        onOpenChange(next);
      }}
      title={loading ? "Block" : fields.name}
      contentClassName="sm:max-w-4xl"
    >
      {loading ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Loading...
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-[1fr_1.3fr]">
          <div className="flex flex-col gap-4">
            <FieldRow label="Project">
              <p className="text-lg font-semibold text-foreground">{fields.name}</p>
            </FieldRow>
            <FieldRow label="Description">
              <FieldValue value={fields.description} />
            </FieldRow>
          </div>
          <div className="flex flex-col gap-4">
            <FieldRow label="Time Period">
              <FieldValue value={fields.timePeriod ?? ""} />
            </FieldRow>
            <FieldRow label="Role">
              <FieldValue value={fields.role ?? ""} />
            </FieldRow>
            {otherFieldEntries.map(([key, value]) => (
              <FieldRow key={key} label={titleCaseLabel(key)}>
                <FieldValue value={value} />
              </FieldRow>
            ))}
            <FieldRow label="Environment">
              <FieldValue value={fields.environment.join(", ")} />
            </FieldRow>
          </div>
          <div className="flex justify-end sm:col-span-2">
            <Button type="button" onClick={onEdit}>
              Edit
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
