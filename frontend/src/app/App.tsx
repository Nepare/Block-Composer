import { useEffect, useState } from "react";
import { ComposePane } from "@/features/compose/ComposePane";
import { LibraryPane } from "@/features/library/LibraryPane";
import { LoginScreen } from "@/shared/LoginScreen";
import { apiFetch, setUnauthorizedHandler } from "@/shared/api";
import * as session from "@/shared/session";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs";

type SessionState = "checking" | "unauthenticated" | "authenticated";
type ActiveTab = "compose" | "library";

function App() {
  const [sessionState, setSessionState] = useState<SessionState>("checking");
  const [activeTab, setActiveTab] = useState<ActiveTab>("compose");
  const [notice, setNotice] = useState<string | undefined>();

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

  if (sessionState === "checking") {
    return <div className="p-6 text-muted-foreground">Checking session...</div>;
  }

  if (sessionState === "unauthenticated") {
    return <LoginScreen onValidated={handleValidated} notice={notice} />;
  }

  return (
    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ActiveTab)}>
      <TabsList>
        <TabsTrigger value="compose">Compose</TabsTrigger>
        <TabsTrigger value="library">Library</TabsTrigger>
      </TabsList>
      <TabsContent value="compose">
        <ComposePane />
      </TabsContent>
      <TabsContent value="library">
        <LibraryPane />
      </TabsContent>
    </Tabs>
  );
}

export default App;
