import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { ThemeName } from "@/constants/tokens";

const THEME_STORAGE_KEY = "logline_theme";

interface ThemeContextValue {
  theme: ThemeName;
  setLight: () => void;
  setDark: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function readStoredTheme(): ThemeName {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "dark" ? "dark" : "light";
}

/**
 * Global theme state — the app-wide counterpart to the local toggle on
 * `/styleguide`. index.css's palette variables are scoped to
 * `:root[data-theme=...]` (the `<html>` element), so this is the one place
 * that attribute gets set for the authenticated app; the Account & Settings
 * modal (see `molecules/AccountSettingsModal.tsx`) is the only UI that calls
 * `setLight`/`setDark`, matching the handoff.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeName>(readStoredTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const value: ThemeContextValue = {
    theme,
    setLight: () => setTheme("light"),
    setDark: () => setTheme("dark"),
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
