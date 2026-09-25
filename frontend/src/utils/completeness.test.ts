import { describe, expect, it } from "vitest";
import { evaluationIncompleteness, reportIncompleteness } from "./completeness";
import type { ComplianceReport } from "../types/compliance";

const report = (over: Partial<ComplianceReport> = {}): ComplianceReport => ({
  total_rules: 1,
  total_segments_checked: 10,
  violations: [],
  summary: "",
  compliance_score: 100,
  ...over,
});

describe("reportIncompleteness", () => {
  it("is empty for a complete report, including legacy data without the new fields", () => {
    expect(reportIncompleteness(report())).toEqual([]);
  });

  it("reports truncation with checked/total counts", () => {
    const notes = reportIncompleteness(report({ truncated: true, total_segments: 50 }));
    expect(notes).toHaveLength(1);
    expect(notes[0]).toContain("10 / 50");
  });

  it("reports failed chunks", () => {
    const notes = reportIncompleteness(report({ failed_chunks: 2, total_chunks: 5 }));
    expect(notes[0]).toContain("2 / 5");
  });

  it("can report both problems at once", () => {
    const notes = reportIncompleteness(
      report({ truncated: true, total_segments: 50, failed_chunks: 1, total_chunks: 3 }),
    );
    expect(notes).toHaveLength(2);
  });
});

describe("evaluationIncompleteness", () => {
  it("is empty when complete", () => {
    expect(evaluationIncompleteness({ title: "", formatted_content: "" })).toEqual([]);
  });

  it("flags truncation and degraded chunks", () => {
    const notes = evaluationIncompleteness({
      title: "",
      formatted_content: "",
      truncated: true,
      degraded_chunks: 3,
    });
    expect(notes).toHaveLength(2);
    expect(notes[1]).toContain("3");
  });
});
