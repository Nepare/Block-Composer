import { BlockGrid } from "@/features/library/BlockGrid";
import type { UseLibraryJobsResult } from "@/features/library/useLibraryJobs";

interface LibraryPaneProps {
  libraryJobs: UseLibraryJobsResult;
  refetchToken: number;
}

export function LibraryPane({ libraryJobs, refetchToken }: LibraryPaneProps) {
  return (
    <BlockGrid
      pendingJobs={libraryJobs.jobs}
      onDismissJob={libraryJobs.dismiss}
      onJobStarted={libraryJobs.start}
      onJobResolved={libraryJobs.confirmResolved}
      refetchToken={refetchToken}
    />
  );
}
