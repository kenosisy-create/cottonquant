import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.argv[2];
if (!root) throw new Error("Usage: validate_spreadsheet_artifacts.mjs <project-root>");

const csvRoots = ["01_registry", "04_indicators", "07_events", "09_audit"];
const explicitCsv = ["06_weekly/view_ledger.csv"];

async function listCsv(directory) {
  const output = [];
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) output.push(...await listCsv(full));
    else if (entry.isFile() && entry.name.toLowerCase().endsWith(".csv")) output.push(full);
  }
  return output;
}

const csvFiles = [];
for (const relative of csvRoots) csvFiles.push(...await listCsv(path.join(root, relative)));
for (const relative of explicitCsv) csvFiles.push(path.join(root, relative));
csvFiles.sort((a, b) => a.localeCompare(b, "zh-CN"));

const csvResults = [];
for (const file of csvFiles) {
  const bytes = await fs.readFile(file);
  if (!(bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf)) {
    throw new Error(`CSV is missing UTF-8 BOM: ${file}`);
  }
  const csvText = bytes.toString("utf8");
  const workbook = await Workbook.fromCSV(csvText, { sheetName: "Data" });
  const inspected = await workbook.inspect({
    kind: "sheet,region",
    sheetId: "Data",
    range: "A1:F6",
    maxChars: 1800,
    tableMaxRows: 6,
    tableMaxCols: 6,
  });
  csvResults.push({
    path: path.relative(root, file).replaceAll("\\", "/"),
    bytes: bytes.length,
    inspection_available: Boolean(inspected?.ndjson),
  });
}

const pendingDir = path.join(root, "00_inbox", "pending_review");
const xlsxName = (await fs.readdir(pendingDir)).find((name) => name.toLowerCase().endsWith(".xlsx"));
if (!xlsxName) throw new Error("Pending-review workbook is missing");
const xlsxPath = path.join(pendingDir, xlsxName);
const input = await FileBlob.load(xlsxPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const workbookSummary = await workbook.inspect({
  kind: "workbook,sheet",
  maxChars: 3000,
  tableMaxRows: 4,
  tableMaxCols: 4,
});
const errorRegion = await workbook.inspect({
  kind: "region,formula",
  sheetId: "首页",
  range: "A55:D62",
  maxChars: 3500,
  options: { maxResults: 30 },
});
const errorRange = workbook.worksheets.getItem("首页").getRange("A55:D62");

console.log(JSON.stringify({
  csv_count: csvResults.length,
  csv_results: csvResults,
  workbook: {
    path: path.relative(root, xlsxPath).replaceAll("\\", "/"),
    summary_inspection_available: Boolean(workbookSummary?.ndjson),
    b59_region_inspection_available: Boolean(errorRegion?.ndjson),
    b59_region_excerpt: errorRegion?.ndjson?.slice(0, 1800) ?? "",
    a55_d62_values: errorRange.values,
    a55_d62_formulas: errorRange.formulas,
  },
}, null, 2));
