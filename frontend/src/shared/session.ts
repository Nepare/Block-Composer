const STORAGE_KEY = "cvdocs.apiKey";

export function get(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function set(key: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // storage unavailable — session simply won't persist
  }
}

export function clear(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable — nothing to clear
  }
}
