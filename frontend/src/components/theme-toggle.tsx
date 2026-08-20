"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const persisted = window.localStorage.getItem("flow-agent-theme");
    const nextTheme: Theme = persisted === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    setTheme(nextTheme);
  }, []);

  function toggleTheme() {
    const nextTheme: Theme = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    window.localStorage.setItem("flow-agent-theme", nextTheme);
    setTheme(nextTheme);
  }

  return (
    <button aria-label="切换深浅主题" className="theme-toggle" onClick={toggleTheme} type="button">
      {theme === "light" ? "深色" : "浅色"}
    </button>
  );
}
