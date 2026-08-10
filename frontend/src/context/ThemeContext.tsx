import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { ThemeName } from "@/constants";

const THEME_STORAGE_KEY = "logline_theme";

interface ThemeContextValue {
  theme: ThemeName;
  setLight: () => void;
  setDark: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset.theme = "light";
    localStorage.setItem(THEME_STORAGE_KEY, "light");
  }, []);

  const value: ThemeContextValue = {
    theme: "light",
    setLight: () => { },
    setDark: () => { },
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
