import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/compliance", () => ({
  persistViolationStatuses: vi.fn(),
}));

import { persistViolationStatuses } from "../api/compliance";
import { getFilteredViolations, useComplianceStore, violationKey } from "./complianceStore";
import { useTaskStore } from "./taskStore";
import type { ComplianceReport, Violation } from "../types/compliance";

const violation = (id: string, over: Partial<Violation> = {}): Violation => ({
  id,
  rule_id: 1,
  rule_content: "规则",
  reason: "原因",
  severity: "high",
  confidence: 0.9,
  status: "pending",
  source: "transcript",
  evidence_url: null,
  evidence_text: null,
  rule_ref: null,
  timestamp: "00:01",
  timestamp_ms: 1000,
  end_ms: 2000,
  speaker: "A",
  original_text: "原文",
  ...over,
});

const report = (violations: Violation[]): ComplianceReport => ({
  total_rules: 1,
  total_segments_checked: 1,
  violations,
  summary: "",
  compliance_score: 80,
});

const flushPersist = async () => {
  await vi.advanceTimersByTimeAsync(600); // 500ms 防抖
  await vi.advanceTimersByTimeAsync(0); // 让懒加载的 import 与 await 完成
};

describe("violationKey", () => {
  it("is unique even for two violations at the same time under the same rule", () => {
    const a = violation("v0001");
    const b = violation("v0002"); // timestamp_ms 与 rule_id 都相同
    expect(violationKey(a)).not.toBe(violationKey(b));
  });
});

describe("setViolationStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(persistViolationStatuses).mockReset();
    useTaskStore.setState({ taskId: "task-1" });
    useComplianceStore.getState().reset();
  });
  afterEach(() => vi.useRealTimers());

  it("updates only the targeted violation, even when a twin shares time and rule", () => {
    const a = violation("v0001");
    const b = violation("v0002");
    useComplianceStore.getState().setReport(report([a, b]), []);

    useComplianceStore.getState().setViolationStatus(a, "confirmed");

    const [ra, rb] = useComplianceStore.getState().report!.violations;
    expect(ra.status).toBe("confirmed");
    expect(rb.status).toBe("pending");
  });

  it("records review time and note locally, and clears them when reset to pending", () => {
    const a = violation("v0001");
    useComplianceStore.getState().setReport(report([a]), []);

    useComplianceStore.getState().setViolationStatus(a, "rejected", " 误报 ");
    const rejected = useComplianceStore.getState().report!.violations[0];
    expect(rejected.review_note).toBe("误报");
    expect(rejected.reviewed_at).toBeTruthy();

    useComplianceStore.getState().setViolationStatus(rejected, "pending");
    const reset = useComplianceStore.getState().report!.violations[0];
    expect(reset.reviewed_at).toBeNull();
    expect(reset.review_note).toBeNull();
  });

  it("keeps the selected and detail copies in sync", () => {
    const a = violation("v0001");
    const store = useComplianceStore.getState();
    store.setReport(report([a]), []);
    store.selectViolation(useComplianceStore.getState().report!.violations[0]);
    store.openEvidenceDetail(useComplianceStore.getState().report!.violations[0]);

    useComplianceStore.getState().setViolationStatus(a, "confirmed");

    const s = useComplianceStore.getState();
    expect(s.selectedViolation?.status).toBe("confirmed");
    expect(s.evidenceDetail?.status).toBe("confirmed");
  });

  it("debounces persistence into one call keyed by violation id and applies the server score", async () => {
    const a = violation("v0001");
    const b = violation("v0002");
    useComplianceStore.getState().setReport(report([a, b]), []);
    vi.mocked(persistViolationStatuses).mockResolvedValue(93);

    useComplianceStore.getState().setViolationStatus(a, "confirmed", "属实");
    useComplianceStore.getState().setViolationStatus(b, "rejected");
    await flushPersist();

    expect(persistViolationStatuses).toHaveBeenCalledTimes(1);
    expect(persistViolationStatuses).toHaveBeenCalledWith("task-1", [
      { violation_id: "v0001", status: "confirmed", note: "属实" },
      { violation_id: "v0002", status: "rejected", note: undefined },
    ]);
    expect(useComplianceStore.getState().report!.compliance_score).toBe(93);
  });

  it("coalesces repeated changes to the same violation, keeping the last", async () => {
    const a = violation("v0001");
    useComplianceStore.getState().setReport(report([a]), []);
    vi.mocked(persistViolationStatuses).mockResolvedValue(100);

    useComplianceStore.getState().setViolationStatus(a, "confirmed");
    useComplianceStore.getState().setViolationStatus(a, "rejected");
    await flushPersist();

    const [, updates] = vi.mocked(persistViolationStatuses).mock.calls[0];
    expect(updates).toHaveLength(1);
    expect(updates[0].status).toBe("rejected");
  });
});

describe("getFilteredViolations", () => {
  beforeEach(() => useComplianceStore.getState().reset());

  it("combines severity, status and search filters", () => {
    const store = useComplianceStore.getState();
    store.setReport(
      report([
        violation("v1", { severity: "high", reason: "承诺收益" }),
        violation("v2", { severity: "low", reason: "承诺收益" }),
        violation("v3", { severity: "high", reason: "夸大宣传", status: "confirmed" }),
      ]),
      [],
    );
    store.setSeverityFilter("high");
    store.setSearchQuery("收益");

    expect(getFilteredViolations(useComplianceStore.getState()).map((v) => v.id)).toEqual(["v1"]);

    useComplianceStore.getState().setSearchQuery("");
    useComplianceStore.getState().setStatusFilter("confirmed");
    expect(getFilteredViolations(useComplianceStore.getState()).map((v) => v.id)).toEqual(["v3"]);
  });
});
