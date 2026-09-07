import { useState, type FormEvent } from "react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

interface LoginScreenProps {
  onValidated: (key: string) => void;
  notice?: string;
}

export function LoginScreen({ onValidated, notice }: LoginScreenProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const key = value.trim();
    if (!key) {
      setError("Enter your secret to continue.");
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch(`/auth/check?key=${encodeURIComponent(key)}`);
      if (!response.ok) {
        setError("That secret was rejected. Check it and try again.");
        return;
      }
      onValidated(key);
    } catch {
      setError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        {notice && <p className="text-sm text-muted-foreground">{notice}</p>}
        <div className="space-y-1.5">
          <label htmlFor="secret" className="text-sm font-medium">
            Secret
          </label>
          <Input
            id="secret"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Paste your API secret"
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Checking..." : "Continue"}
        </Button>
      </form>
    </div>
  );
}
