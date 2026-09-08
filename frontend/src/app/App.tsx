import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Boxes } from "lucide-react";
import { ComposePane } from "@/features/compose/ComposePane";
import { preserveBlock } from "@/features/library/api";
import { LibraryPane } from "@/features/library/LibraryPane";
import { readStoredJobs, useLibraryJobs, type DissectOutcome, type JobKind } from "@/features/library/useLibraryJobs";
import { LoginScreen } from "@/shared/LoginScreen";
import { apiFetch, setUnauthorizedHandler } from "@/shared/api";
import * as session from "@/shared/session";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs";
import { Toaster } from "@/shared/ui/sonner";
import { TooltipProvider } from "@/shared/ui/tooltip";

type SessionState = "checking" | "unauthenticated" | "authenticated";
type ActiveTab = "compose" | "library";

function App() {
  const [sessionState, setSessionState] = useState<SessionState>("checking");
  const [activeTab, setActiveTab] = useState<ActiveTab>("compose");
  const [notice, setNotice] = useState<string | undefined>();
  const [refetchToken, setRefetchToken] = useState(0);

  const libraryJobs = useLibraryJobs({
    onRefetchNeeded: () => setRefetchToken((token) => token + 1),
    onDuplicate: (kind: JobKind, duplicateOf: string | null) => {
      const label = kind === "mutate" ? "Mutation" : "Generation";
      toast.info(`${label} matched an existing block${duplicateOf ? ` (${duplicateOf})` : ""} — nothing new was added.`);
    },
    onDissectComplete: async (_jobId: string, outcome: DissectOutcome, preserveRequested: boolean) => {
      if (preserveRequested) {
        const ids = [...outcome.saved.map((b) => b.block_id), ...outcome.variants.map((v) => v.block_id)];
        // Stopgap per research.md: a client-side preserve loop until dissect accepts a preserve param directly.
        await Promise.all(ids.map((id) => preserveBlock(id)));
      }
      toast.success(
        `Imported ${outcome.saved.length} block(s), skipped ${outcome.skipped_duplicates.length} duplicate(s), ${outcome.variants.length} variant(s).`
      );
    },
    onDissectError: (_jobId: string, message: string) => {
      toast.error(message);
    },
  });

  function handleValidated(key: string) {
    session.set(key);
    setNotice(undefined);
    setSessionState("authenticated");
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      session.clear();
      setNotice("Your session was rejected. Please sign in again.");
      setSessionState("unauthenticated");
    });

    const key = session.get();
    if (!key) {
      setSessionState("unauthenticated");
      return () => setUnauthorizedHandler(null);
    }

    apiFetch("/auth/check").then((response) => {
      if (response.ok) {
        setSessionState("authenticated");
      }
    });

    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    for (const { jobId, kind } of readStoredJobs()) {
      libraryJobs.reconnect(kind, jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (sessionState === "checking") {
    return (
      <>
        <div className="p-6 text-muted-foreground">Checking session...</div>
        <Toaster />
      </>
    );
  }

  if (sessionState === "unauthenticated") {
    return (
      <>
        <LoginScreen onValidated={handleValidated} notice={notice} />
        <Toaster />
      </>
    );
  }

  return (
    <TooltipProvider>
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as ActiveTab)}
        className="h-full gap-0"
      >
        <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-background px-5">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Boxes className="size-4" />
            </div>
            <span className="text-[15px] font-medium">cvdocs</span>
          </div>
          <TabsList variant="line" className="h-full gap-1 self-stretch">
            <TabsTrigger value="compose" className="text-sm">
              Compose
            </TabsTrigger>
            <TabsTrigger value="library" className="text-sm">
              Library
            </TabsTrigger>
          </TabsList>
        </header>
        <TabsContent value="compose" className="min-h-0 flex-1 overflow-y-auto">
          <ComposePane />
        </TabsContent>
        <TabsContent value="library" className="min-h-0 flex-1 overflow-y-auto">
          <LibraryPane libraryJobs={libraryJobs} refetchToken={refetchToken} />
        </TabsContent>
      </Tabs>
      <Toaster />
    </TooltipProvider>
  );
}

export default App;
