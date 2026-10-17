const MAX_TEXT_IMPORT_BYTES = 2_000_000;
const ALLOWED_TEXT_EXTENSIONS = new Set([".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm"]);

export type LocalImportFile = Pick<File, "name" | "size">;

/** Validate a local text document before reading or sending its content to the API. */
export function validateTextImportFile(file: LocalImportFile): string | null {
  const extension = file.name.includes(".")
    ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
    : "";

  if (!ALLOWED_TEXT_EXTENSIONS.has(extension)) {
    return "Unsupported file type. Choose TXT, Markdown, CSV, JSON, or HTML.";
  }
  if (file.size > MAX_TEXT_IMPORT_BYTES) {
    return "File exceeds the 2 MB text import limit.";
  }
  return null;
}
