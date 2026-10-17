import { describe, expect, it } from "vitest";
import { validateTextImportFile } from "../src/lib/documentImport";

describe("validateTextImportFile", () => {
  it.each(["notes.txt", "notes.md", "notes.markdown", "data.csv", "data.json", "page.html", "page.htm"])(
    "accepts supported text extension %s",
    (name) => {
      expect(validateTextImportFile({ name, size: 100 })).toBeNull();
    },
  );

  it.each(["archive.zip", "script.js", "document.pdf", "no-extension"])(
    "rejects unsupported extension %s",
    (name) => {
      expect(validateTextImportFile({ name, size: 100 })).toContain("Unsupported file type");
    },
  );

  it("rejects files larger than 2 MB", () => {
    expect(validateTextImportFile({ name: "large.txt", size: 2_000_001 })).toContain("2 MB");
  });

  it("accepts a file exactly at the 2 MB limit", () => {
    expect(validateTextImportFile({ name: "limit.txt", size: 2_000_000 })).toBeNull();
  });

  it("checks extensions case-insensitively", () => {
    expect(validateTextImportFile({ name: "NOTES.MD", size: 0 })).toBeNull();
  });
});
