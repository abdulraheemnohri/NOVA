import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

function navigationLabels(): string[] {
  const match = appSource.match(/const nav=\[(.*?)\] as const/s);
  if (!match) throw new Error("Navigation declaration not found");
  return [...match[1].matchAll(/\["([^"]+)"/g)].map((item) => item[1]);
}

function renderedPageLabels(): Set<string> {
  return new Set([...appSource.matchAll(/page\s*===\s*"([^"]+)"/g)].map((item) => item[1]));
}

describe("workspace navigation wiring", () => {
  it("does not expose navigation items without an intentional page renderer", () => {
    const rendered = renderedPageLabels();
    // Dashboard is the deliberate final fallback; every other navigation item
    // must have a dedicated render branch.
    const unrouted = navigationLabels().filter((label) => label !== "Dashboard" && !rendered.has(label));
    expect(unrouted).toEqual([]);
  });

  it("routes every quick-action destination to a known workspace page", () => {
    const labels = new Set(navigationLabels());
    const targets = [...appSource.matchAll(/\[[^\[\]]*?,\s*"[^"]+",\s*"[^"]+",\s*"([^"]+)"\]/g)]
      .map((item) => item[1])
      .filter((target) => ["Chat", "Knowledge Base", "Documents", "Goals", "Agent Console"].includes(target));
    expect(targets.length).toBeGreaterThan(0);
    expect(targets.filter((target) => !labels.has(target))).toEqual([]);
    expect(targets).not.toContain("Agent Console");
  });
});
