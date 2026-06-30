import type {
  Assessment,
  AssessmentHistoryRecord,
  CommitRecord,
  DecisionAudit,
  DecisionAuditAction,
  DecisionAuditReason,
  DecisionAuditRule,
  ProviderStatus,
  ScanResponse
} from "../types";

type SourceAvailability = ScanResponse["coverage"]["sourceAvailability"];
type SourceCompleteness = ScanResponse["coverage"]["dataCompleteness"];

const DEMO_MANTLE_YIELD_TOKEN_ADDRESS = "0xb5600dccf7f95ff7e52f67fee192921d0eeb3a56";

export type ScoreDisplay = {
  value: string;
  label: string;
  helper: string;
  showNumeric: boolean;
};

export type ProofCopy = {
  label: string;
  helper: string;
  actionLabel: string;
  status: "replay" | "not_recorded" | "local" | "pending" | "recorded" | "failed" | "unavailable";
};

export type SimulationAvailability = {
  available: boolean;
  label: string;
  reason: string;
};

export type SourceStatusGroups = {
  available: SourceCapabilityStatus[];
  partial: SourceCapabilityStatus[];
  unavailable: SourceCapabilityStatus[];
};

export type SourceCapabilityStatus = {
  provider: string;
  capability: string;
  label: string;
  status: "available" | "partial" | "unavailable";
  reason?: string;
};

const DEFAULT_BLOCKED_ACTIONS: DecisionAuditAction[] = [
  {
    label: "Real revoke",
    reason: "P0 review mode never broadcasts revoke transactions."
  },
  {
    label: "Swap",
    reason: "MantleLens does not trade or rebalance assets in this workflow."
  },
  {
    label: "Transfer",
    reason: "The agent cannot move funds or prepare transfers for signing."
  },
  {
    label: "Auto-signing",
    reason: "Every wallet action requiring a signature is outside the agent boundary."
  },
  {
    label: "Private-key custody",
    reason: "MantleLens never stores, requests, or handles private keys."
  },
  {
    label: "LLM-generated transaction execution",
    reason: "LLM output cannot create, approve, or broadcast transactions."
  }
];

const LLM_BOUNDARY =
  "Rules and evidence run before LLM explanation. LLM explains findings; it does not execute transactions or override hard rules.";

export function getDecisionAudit(assessment: Assessment, scan?: ScanResponse | null): DecisionAudit {
  const decisionType = getDecisionType(assessment, scan || null);
  const actionType = getActionType(decisionType, assessment, scan || null);
  return {
    decisionType,
    actionType,
    decisionLabel: getDecisionLabel(decisionType),
    actionLabel: getActionLabel(actionType),
    why: getDecisionReasons(assessment, scan || null, decisionType),
    hardRules: getHardRules(assessment, scan || null, decisionType),
    blockedActions: getBlockedActions(),
    allowedActions: getAllowedActions(assessment, scan || null, actionType),
    llmBoundary: LLM_BOUNDARY,
    evidenceFirst: true
  };
}

export function getDecisionLabel(decisionType: string): string {
  switch (decisionType) {
    case "PAUSE":
      return "Pause";
    case "REVIEW_APPROVAL":
      return "Review approval";
    case "REVIEW_TRANSFER_EVIDENCE":
      return "Review transfer evidence";
    case "RECORD_ASSESSMENT_ONLY":
      return "Record assessment only";
    case "SIMULATE_ONLY":
      return "Simulate only";
    case "WATCH":
      return "Watch";
    case "SAFE":
      return "Safe";
    default:
      return humanize(decisionType || "review");
  }
}

export function getActionLabel(actionType: string): string {
  switch (actionType) {
    case "SIMULATE_REVOKE_APPROVAL":
      return "Simulate revoke impact";
    case "REVIEW_APPROVAL":
      return "Review approval";
    case "CHECK_SOURCE_COVERAGE_INSPECT_TRANSFER":
      return "Check source coverage / Inspect transfer evidence";
    case "INSPECT_TRANSFER_EVIDENCE":
      return "Inspect transfer evidence";
    case "CHECK_SOURCE_COVERAGE":
      return "Check source coverage";
    case "RECORD_ASSESSMENT_ONLY":
      return "Record assessment hash";
    case "WATCH":
      return "Watch";
    case "NO_ACTION":
      return "No action";
    default:
      return humanize(actionType || "inspect evidence");
  }
}

export function getBlockedActions(): DecisionAuditAction[] {
  return DEFAULT_BLOCKED_ACTIONS.map((action) => ({ ...action }));
}

export function getAllowedActions(
  assessment: Assessment,
  scan?: ScanResponse | null,
  actionType?: string
): DecisionAuditAction[] {
  const simulation = getSimulationAvailability(assessment);
  const actions: DecisionAuditAction[] = [
    {
      label: "Inspect evidence",
      reason: "Open the evidence bundle and review the records bound to the decision."
    },
    {
      label: "Record assessment hash",
      reason: "Record a hash of this assessment when live proof is available; this does not prove wallet safety."
    },
    {
      label: "Verify assessment",
      reason: "Verify an existing AssessmentRecorded proof against the local assessment hash."
    },
    {
      label: "Check source coverage",
      reason: "Inspect unavailable or partial data sources before treating missing data as risk-free."
    }
  ];
  if (simulation.available || actionType === "SIMULATE_REVOKE_APPROVAL") {
    actions.splice(1, 0, {
      label: "Simulate risk reduction",
      reason: "Estimate revoke or exposure-reduction impact without broadcasting a revoke, swap, or transfer."
    });
  }
  if (scan?.coverage?.sourceAvailability && !actions.some((action) => action.label === "Check source coverage")) {
    actions.push({
      label: "Check source coverage",
      reason: "Source coverage is part of the visible assessment state."
    });
  }
  return actions;
}

export function getDecisionReasons(
  assessment: Assessment,
  scan?: ScanResponse | null,
  decisionType = getDecisionType(assessment, scan || null)
): DecisionAuditReason[] {
  const reasons: DecisionAuditReason[] = [];
  const approvalIds = evidenceIdsForRisk(assessment, ["approval", "allowance", "spender", "unlimited"]);
  const transferIds = evidenceIdsForRisk(assessment, ["transfer", "poison", "dust"]);
  const yieldIds = evidenceIdsForRisk(assessment, ["yield", "concentration", "meth", "cmeth", "portfolio", "exposure"]);
  const coverageIds = evidenceIdsForRisk(assessment, ["source", "coverage", "partial", "unknown", "indexed"]);

  if (decisionType === "PAUSE") {
    reasons.push({
      label: "Hard red flag triggered",
      description: "A critical or blocking risk signal requires human review before any next action.",
      evidenceIds: uniqueIds([...approvalIds, ...transferIds, ...yieldIds]).slice(0, 4),
      ruleIds: ["rule:p0_real_execution_blocked"],
      severity: "critical"
    });
  }

  if (hasApprovalSignal(assessment, scan || null)) {
    reasons.push({
      label: "Active allowance confirmed",
      description: "Approval evidence is present, so the safest next step is review and simulation rather than execution.",
      evidenceIds: approvalIds,
      ruleIds: ["rule:p0_real_execution_blocked"],
      severity: "high"
    });
    reasons.push({
      label: "Spender label unavailable",
      description: "Unknown spender labels remain unknown, not safe.",
      evidenceIds: approvalIds,
      ruleIds: ["rule:unknown_spender_not_safe"],
      severity: "warning"
    });
  }

  if (tokenBalanceExists(scan || null)) {
    reasons.push({
      label: "Token balance exists",
      description: "Visible inventory indicates there is value or token exposure to review.",
      evidenceIds: inventoryEvidenceIds(scan || null),
      severity: "info"
    });
  }

  if (decisionType === "REVIEW_TRANSFER_EVIDENCE" || transferIds.length) {
    reasons.push({
      label: "Transfer evidence requires review",
      description: "Suspicious transfer or address-poisoning evidence is present, so the workflow inspects transfer evidence instead of approval actions.",
      evidenceIds: transferIds,
      ruleIds: ["rule:evidence_first"],
      severity: "warning"
    });
  }

  if (yieldIds.length) {
    reasons.push({
      label: "Additional risk evidence present",
      description: "Mantle yield-concentration evidence is also bound to this assessment.",
      evidenceIds: yieldIds,
      severity: "warning"
    });
  }

  if (isCoverageOnlyAssessment(assessment) || isPartialOrUnknown(assessment.dataStatus)) {
    reasons.push({
      label: "Unknown coverage cannot be marked safe",
      description: "No direct approval, transfer, or yield evidence may still mean missing indexed data, not wallet safety.",
      evidenceIds: coverageIds,
      ruleIds: ["rule:missing_data_unknown_not_safe"],
      severity: "warning"
    });
  }

  if (!directSignalCount(assessment) && hasSufficientCoverage(assessment)) {
    reasons.push({
      label: "No direct risk signal in sufficient evidence",
      description: "Available evidence does not show active approval, transfer, or yield-risk signals, so the workflow watches rather than executes.",
      ruleIds: ["rule:evidence_first"],
      severity: "info"
    });
  }

  if (!reasons.length) {
    reasons.push({
      label: "Evidence review required",
      description: "The decision remains evidence-first; missing or ambiguous data cannot be converted into a safety claim.",
      ruleIds: ["rule:evidence_first"],
      severity: "info"
    });
  }

  return reasons.slice(0, 5);
}

export function getHardRules(
  assessment: Assessment,
  scan?: ScanResponse | null,
  decisionType = getDecisionType(assessment, scan || null)
): DecisionAuditRule[] {
  const hasApproval = hasApprovalSignal(assessment, scan || null);
  const hasUnknownCoverage = isCoverageOnlyAssessment(assessment) || isPartialOrUnknown(assessment.dataStatus);
  return [
    {
      id: "rule:evidence_first",
      label: "Evidence before explanation",
      description: "Rules and evidence are evaluated before any LLM explanation is shown.",
      triggered: true
    },
    {
      id: "rule:unknown_spender_not_safe",
      label: "Unknown spender is not safe",
      description: "LLM cannot mark an unknown spender as safe.",
      triggered: hasApproval
    },
    {
      id: "rule:missing_data_unknown_not_safe",
      label: "Missing data is unknown",
      description: "Missing indexed data cannot reduce risk to safe.",
      triggered: hasUnknownCoverage || decisionType === "RECORD_ASSESSMENT_ONLY"
    },
    {
      id: "rule:p0_real_execution_blocked",
      label: "Real execution blocked",
      description: "Simulation-only means no revoke, swap, transfer, or auto-signing is broadcast.",
      triggered: true
    },
    {
      id: "rule:proof_hash_not_safety",
      label: "Proof is not safety",
      description: "Assessment hash proof verifies the assessment record, not wallet safety.",
      triggered: true
    }
  ];
}

export function getScoreDisplay(assessment: Assessment): ScoreDisplay {
  if (isCoverageOnlyAssessment(assessment)) {
    return {
      value: "Not enough data",
      label: "Signal Risk Index",
      helper: "0 detected risk signals · not a safety score",
      showNumeric: false
    };
  }
  return {
    value: `${Math.round(Number(assessment.walletRiskScore) || 0)} / 100`,
    label: "Signal Risk Index",
    helper: "Evidence-backed risk severity, not a guarantee of wallet safety.",
    showNumeric: true
  };
}

export function getRiskHeadline(assessment: Assessment, signalCount?: number): string {
  if (isCoverageOnlyAssessment(assessment)) return "Live scan completed, but risk remains unknown";
  if (directSignalCount(assessment) === 0) return "No direct on-chain risk signals found";
  const count = signalCount ?? directSignalCount(assessment);
  if (count === 1) return "1 suspicious on-chain signal detected";
  return `${count} suspicious on-chain signals detected`;
}

export function getRiskSubtitle(assessment: Assessment, signalTitles: string[] = []): string {
  if (isCoverageOnlyAssessment(assessment)) {
    return "No direct approval, transfer, or yield-risk evidence was found. However, source coverage is partial, so this wallet cannot be marked safe.";
  }
  if (directSignalCount(assessment) === 0) {
    return "No direct approval, transfer, or yield-risk evidence was found in available data. Missing indexed data remains unknown.";
  }
  if (signalTitles.length >= 3) {
    return "The agent found risky approval behavior, a possible address poisoning pattern, and concentrated Mantle yield exposure.";
  }
  return `The scan found ${humanList(signalTitles.map((item) => item.toLowerCase()))} with evidence-bound review steps.`;
}

export function getCoverageLabel(status?: string | null, mode?: string | null): string {
  if (isDemoMode(mode)) return "Demo replay · fixture data";
  const normalized = normalize(status);
  if (!normalized) return "Coverage unknown";
  if (normalized.includes("partial") && normalized.includes("unknown")) return "Partial scan · unknown fields present";
  if (normalized.includes("partial")) return "Partial scan";
  if (normalized.includes("source_failed") || normalized.includes("failed") || normalized.includes("error")) return "Source unavailable";
  if (normalized.includes("unavailable")) return "Unavailable";
  if (normalized.includes("full") || normalized.includes("complete") || normalized.includes("available")) return "Available";
  if (normalized.includes("safe")) return "Available evidence only";
  return humanize(status || "unknown");
}

export function getSourceStatusLabel(status?: string | null): string {
  const normalized = normalize(status || "unknown");
  if (normalized === "available") return "available";
  if (normalized.includes("partial") || normalized.includes("limited")) return "partial";
  if (normalized.includes("not_supported") || normalized.includes("unavailable") || normalized.includes("failed")) return "unavailable";
  if (normalized.includes("unknown")) return "unknown";
  return humanize(status || "unknown");
}

export function getProofLabel(
  assessment: Assessment,
  record: CommitRecord | null,
  providerStatus?: ProviderStatus | null
): ProofCopy {
  if (record?.assessmentTx && record.status === "recorded") {
    return {
      label: "Recorded on Mantle",
      helper: "This proves the assessment hash, not wallet safety.",
      actionLabel: "View on-chain proof",
      status: "recorded"
    };
  }
  if (record?.status === "recorded_local") {
    return {
      label: "Local draft",
      helper: "Saved locally only. No Mantle transaction proof was created.",
      actionLabel: "View local record",
      status: "local"
    };
  }
  if (record && normalize(record.status).includes("pending")) {
    return {
      label: "Pending",
      helper: "Assessment hash record is pending. This is not a wallet safety proof.",
      actionLabel: "View proof status",
      status: "pending"
    };
  }
  if (assessment.dataMode !== "live") {
    return {
      label: "Replay proof only",
      helper: "Demo replay does not create Mantle transaction proof. Live scan required before recording an assessment hash.",
      actionLabel: "View replay proof",
      status: "replay"
    };
  }
  if (providerStatus?.assessmentLogger?.status === "configured") {
    return {
      label: "Not recorded on-chain yet",
      helper: "Ready to record assessment hash. This proves the assessment hash, not wallet safety.",
      actionLabel: "Record assessment hash",
      status: "not_recorded"
    };
  }
  return {
    label: "Recorder unavailable",
    helper: "Assessment hash cannot be recorded on this target right now.",
    actionLabel: "View proof status",
    status: "unavailable"
  };
}

export function getRecordStatusLabel(record?: AssessmentHistoryRecord | CommitRecord | null): string {
  if (!record) return "Local draft";
  const commitTxHash = "commitTxHash" in record ? record.commitTxHash : "assessmentTx" in record ? record.assessmentTx : undefined;
  const commitStatus = "commitStatus" in record ? record.commitStatus : "status" in record ? record.status : undefined;
  if (commitTxHash || commitStatus === "recorded") return "Recorded on Mantle";
  if (normalize(commitStatus).includes("pending")) return "Pending";
  if (normalize(commitStatus).includes("failed") || normalize(commitStatus).includes("retry")) return "Failed";
  return "Local draft";
}

export function getOutcomeLabel(record?: AssessmentHistoryRecord | null, duplicateCount = 1): string {
  if (!record) return "Pending review";
  if (record.commitTxHash || record.commitStatus === "recorded") return "Recorded";
  if (duplicateCount > 1) return "Unchanged";
  if (isPartialOrUnknown(record.status)) return "Pending review";
  return "Pending review";
}

export function getSimulationAvailability(assessment: Assessment, _scan?: ScanResponse | null): SimulationAvailability {
  const haystack = topRiskText(assessment);
  const hasApproval = hasDirectRisk(assessment, ["approval", "allowance", "spender", "unlimited"]);
  const hasYield = hasDirectRisk(assessment, ["yield", "concentration", "meth", "cmeth", "portfolio", "exposure"]);
  if (hasApproval || hasYield) {
    return {
      available: true,
      label: "Simulate risk reduction",
      reason: hasApproval
        ? "Approval evidence is present, so MantleLens can simulate revoke impact without broadcasting a transaction."
        : "Yield/concentration evidence is present, so MantleLens can simulate lower exposure without trading."
    };
  }
  const coverageOnly = isCoverageOnlyAssessment(assessment) || haystack.includes("coverage");
  return {
    available: false,
    label: "Simulation unavailable",
    reason: coverageOnly
      ? "No active approval or yield action found to simulate. Coverage gaps are review-only."
      : "No active approval or yield action found to simulate."
  };
}

export function getPrimaryNextStep(
  assessment: Assessment,
  record?: CommitRecord | null,
  providerStatus?: ProviderStatus | null
): string {
  const proof = getProofLabel(assessment, record || null, providerStatus);
  if (proof.status === "recorded") return "Verify assessment";
  if (isCoverageOnlyAssessment(assessment)) return "Check source coverage";
  const text = topRiskText(assessment);
  if (text.includes("approval") || text.includes("allowance")) return "Review approval evidence";
  if (text.includes("transfer") || text.includes("poison") || text.includes("dust")) return "Review transfer evidence";
  if (text.includes("yield") || text.includes("concentration") || text.includes("meth") || text.includes("cmeth")) return "Inspect yield evidence";
  return "Inspect evidence";
}

export function getReviewWorkflow(assessment: Assessment, record?: CommitRecord | null): string {
  if (record?.assessmentTx && record.status === "recorded") return "Inspect evidence → Verify assessment → View on-chain proof";
  if (assessment.dataMode !== "live") return "Inspect evidence → Simulate risk reduction → Record live assessment hash";
  if (isCoverageOnlyAssessment(assessment)) return "Inspect coverage evidence → Check source coverage → View on-chain proof if recorded";
  return "Inspect evidence → Simulate risk reduction if available → Record assessment hash";
}

export function getSourceStatusGroups(
  sourceAvailability: SourceAvailability,
  scan?: ScanResponse | null
): SourceStatusGroups {
  const groups: SourceStatusGroups = { available: [], partial: [], unavailable: [] };
  for (const item of getSourceCapabilityStatuses(sourceAvailability || {}, scan?.coverage?.dataCompleteness || {})) {
    groups[item.status].push(item);
  }
  return groups;
}

export function getCoverageWarningCopy(scan?: ScanResponse | null) {
  const unknownFields = unknownCoverageFields(scan);
  return {
    title: "Source coverage",
    statusHeadline: "Comparable with caution",
    body:
      "Source availability is stable across recent scans, so trend comparison is allowed. Some indexed sources are still incomplete, so missing data is treated as unknown, not safe.",
    whatHappened: "Some indexed sources were unavailable or incomplete.",
    unknownFields,
    hiddenRisk: "Missing indexed data may hide older approvals, unknown tokens, or transfer history.",
    whyItMatters: "Missing data is treated as unknown, not safe.",
    recommendedAction: "Check source coverage or rescan with indexed sources enabled."
  };
}

export function getSafeDisclaimer(assessment?: Assessment | null): string {
  if (assessment?.dataMode === "live") {
    return "Missing indexed data is treated as unknown, not safe. Assessment hash proves this assessment record, not wallet safety.";
  }
  return "Demo replay uses fixture data. Missing indexed data is still treated as unknown, not safe.";
}

export function isDemoMantleYieldLikeToken(symbol?: string | null, tokenAddress?: string | null): boolean {
  return normalize(symbol) === "mldt" || normalize(tokenAddress) === DEMO_MANTLE_YIELD_TOKEN_ADDRESS;
}

export function isOfficialMantleYieldToken(symbol?: string | null): boolean {
  const normalized = normalize(symbol);
  return normalized === "meth" || normalized === "cmeth";
}

export function getMantleTokenLabel(symbol?: string | null, tokenAddress?: string | null): string {
  const display = tokenDisplaySymbol(symbol, tokenAddress);
  if (isDemoMantleYieldLikeToken(symbol, tokenAddress)) return `${display} · Sepolia test token`;
  if (isOfficialMantleYieldToken(symbol)) return `${display} · Mantle yield asset`;
  if (["usdy", "musd"].includes(normalize(symbol))) return `${display} · Mantle ecosystem yield context`;
  return display;
}

export function getMantleTokenLimitation(symbol?: string | null, tokenAddress?: string | null): string {
  if (isDemoMantleYieldLikeToken(symbol, tokenAddress)) {
    return "Demo Mantle yield-like token, not official mETH/cmETH.";
  }
  if (isOfficialMantleYieldToken(symbol)) {
    return "Mantle yield asset context; not RWA and not investment advice.";
  }
  return "Unknown protocol labels remain unknown, not safe.";
}

export function getMantleProofSourceLabel(chainId?: number | null): string {
  if (Number(chainId) === 5003) return "Mantle Sepolia AssessmentLogger";
  if (Number(chainId) === 5000) return "Mantle Mainnet AssessmentLogger";
  return "Mantle AssessmentLogger";
}

export function getMantleProofNetworkLabel(chainId?: number | null): string {
  if (Number(chainId) === 5003) return "Mantle Sepolia · chainId 5003";
  if (Number(chainId) === 5000) return "Mantle Mainnet · chainId 5000";
  return `Mantle chain · chainId ${chainId || "unknown"}`;
}

export function normalizeUserFacingLabel(value?: string | null): string {
  const text = String(value || "");
  if (!text) return "";
  return text
    .replaceAll("PARTIAL_OR_UNKNOWN", "Partial scan · unknown fields present")
    .replaceAll("REPLAY_ONLY", "Replay proof only")
    .replaceAll("LIVE_READY", "Live-ready")
    .replaceAll("SOURCE_COVERAGE_WARNING", "Source coverage warning")
    .replaceAll("rule:rwa_yield_exposure", "Rule-based yield exposure check")
    .replaceAll("RwaYieldExposure", "Yield exposure data")
    .replaceAll("rwa_yield_exposure", "yield exposure check")
    .replaceAll("local_recorded", "Local fallback record")
    .replaceAll("Rwa Yield evidence", "Yield exposure evidence")
    .replaceAll("source evidence weighted by confidence", "Based on verified evidence")
    .replaceAll("fullTokenInventory", "full token inventory");
}

export function isCoverageOnlyAssessment(assessment: Assessment): boolean {
  return assessment.dataMode === "live" && isPartialOrUnknown(assessment.dataStatus) && directSignalCount(assessment) === 0;
}

export function directSignalCount(assessment: Assessment): number {
  return (assessment.topRisks || []).filter((risk) => !isCoverageRiskText(riskText(risk))).length;
}

export function isPartialOrUnknown(status?: string | null): boolean {
  const normalized = normalize(status);
  return (
    normalized.includes("partial") ||
    normalized.includes("unknown") ||
    normalized.includes("source_failed") ||
    normalized.includes("failed") ||
    normalized.includes("unavailable")
  );
}

function hasDirectRisk(assessment: Assessment, keywords: string[]): boolean {
  return (assessment.topRisks || []).some((risk) => {
    const text = riskText(risk);
    return !isCoverageRiskText(text) && keywords.some((keyword) => text.includes(keyword));
  });
}

function topRiskText(assessment: Assessment): string {
  return (assessment.topRisks || []).map(riskText).join(" ");
}

function riskText(risk: Assessment["topRisks"][number]): string {
  return `${risk.type || ""} ${risk.category || ""} ${risk.title || ""} ${risk.claimText || ""} ${risk.explanation || ""} ${(risk.unknowns || []).join(" ")}`.toLowerCase();
}

function isCoverageRiskText(text: string): boolean {
  return (
    text.includes("source") ||
    text.includes("coverage") ||
    text.includes("partial") ||
    text.includes("unknown") ||
    text.includes("unavailable") ||
    text.includes("indexed")
  );
}

function unknownCoverageFields(scan?: ScanResponse | null): string[] {
  const completeness = scan?.coverage?.dataCompleteness || {};
  const labels = Object.entries(completeness)
    .filter(([, value]) => isPartialOrUnknown(String(value)) || normalize(value).includes("not_supported"))
    .map(([key]) => coverageFieldLabel(key));
  if (labels.length) return Array.from(new Set(labels)).slice(0, 5);
  return ["Full token inventory", "Approval history", "Spender labels", "Transfer history"];
}

function coverageFieldLabel(key: string): string {
  const normalized = normalize(key);
  if (normalized.includes("inventory")) return "Full token inventory";
  if (normalized.includes("approval")) return "Approval history";
  if (normalized.includes("spender")) return "Spender labels";
  if (normalized.includes("transfer") || normalized.includes("transaction")) return "Transfer history";
  if (normalized.includes("defi")) return "DeFi positions";
  if (normalized.includes("security")) return "Token security labels";
  return humanize(key);
}

function sourceDisplayName(name: string): string {
  const normalized = normalize(name);
  if (normalized.includes("coingecko")) return "CoinGecko";
  if (normalized.includes("defillama")) return "DeFiLlama";
  if (normalized.includes("goplus")) return "GoPlus";
  if (normalized.includes("mantle") && normalized.includes("rpc")) return "Mantle RPC";
  if (normalized.includes("moralis") && (normalized.includes("balance") || normalized.includes("token"))) return "Moralis balances";
  if (normalized.includes("moralis") && (normalized.includes("history") || normalized.includes("transfer") || normalized.includes("wallet"))) {
    return "Moralis wallet history";
  }
  if (normalized.includes("moralis")) return "Moralis";
  if (normalized.includes("etherscan")) return "Etherscan V2";
  if (normalized.includes("mantlescan")) return "Mantlescan";
  if (normalized.includes("assessmentlogger")) return "AssessmentLogger";
  if (normalized.includes("txsimulation")) return "TxSimulation";
  return humanize(name);
}

function getSourceCapabilityStatuses(sourceAvailability: SourceAvailability, completeness: SourceCompleteness): SourceCapabilityStatus[] {
  const items: SourceCapabilityStatus[] = [];
  for (const [name, source] of Object.entries(sourceAvailability || {})) {
    const normalized = normalize(name);
    if (normalized.includes("moralis") && !normalized.includes("rpc")) {
      const balancesStatus = strongestCoverageStatus(
        [completeness.fullTokenInventory, completeness.knownTokenBalances],
        source.status
      );
      const historyStatus = strongestCoverageStatus(
        [completeness.transferLogs, completeness.approvalHistory, completeness.approvalEvents],
        source.status
      );
      items.push({
        provider: "Moralis",
        capability: "balances",
        label: "Moralis balances",
        status: balancesStatus,
        reason: source.limitation || "Moralis token-balance coverage for this scan."
      });
      items.push({
        provider: "Moralis",
        capability: "wallet history",
        label: "Moralis wallet history",
        status: historyStatus,
        reason: source.limitation || "Moralis indexed wallet-history coverage for this scan."
      });
      continue;
    }
    const label = sourceDisplayName(name);
    items.push({
      provider: label.split(" ")[0] || label,
      capability: label,
      label,
      status: sourceStatusGroupStatus(source.status),
      reason: source.limitation
    });
  }
  return dedupeSourceCapabilities(items);
}

function strongestCoverageStatus(values: Array<string | undefined>, fallback?: string): SourceCapabilityStatus["status"] {
  const statuses = values.filter(Boolean).map((value) => sourceStatusGroupStatus(value));
  if (!statuses.length) return sourceStatusGroupStatus(fallback);
  if (statuses.includes("unavailable")) return "unavailable";
  if (statuses.includes("partial")) return "partial";
  return "available";
}

function sourceStatusGroupStatus(status?: string | null): SourceCapabilityStatus["status"] {
  const label = getSourceStatusLabel(status);
  if (label === "available") return "available";
  if (label === "unavailable") return "unavailable";
  return "partial";
}

function dedupeSourceCapabilities(items: SourceCapabilityStatus[]): SourceCapabilityStatus[] {
  const rank: Record<SourceCapabilityStatus["status"], number> = { available: 1, partial: 2, unavailable: 3 };
  const merged = new Map<string, SourceCapabilityStatus>();
  for (const item of items) {
    const existing = merged.get(item.label);
    if (!existing || rank[item.status] > rank[existing.status]) {
      merged.set(item.label, item);
    }
  }
  return Array.from(merged.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function isDemoMode(mode?: string | null): boolean {
  return normalize(mode).includes("demo");
}

function normalize(value?: string | null): string {
  return String(value || "").toLowerCase();
}

function tokenDisplaySymbol(symbol?: string | null, tokenAddress?: string | null): string {
  if (symbol && symbol.trim()) return symbol.trim();
  if (!tokenAddress) return "Token";
  const text = tokenAddress.trim();
  return text.length > 12 ? `${text.slice(0, 6)}...${text.slice(-4)}` : text;
}

function humanize(value: string): string {
  return String(value || "")
    .replace(/^ev_/, "")
    .replace(/^risk_/, "")
    .replace(/^act_/, "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function humanList(items: string[]): string {
  const clean = items.filter(Boolean);
  if (clean.length <= 1) return clean[0] || "risk evidence";
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(", ")}, and ${clean[clean.length - 1]}`;
}

function getDecisionType(assessment: Assessment, scan?: ScanResponse | null): string {
  if (hasCriticalRedFlag(assessment)) return "PAUSE";
  if (hasApprovalSignal(assessment, scan || null)) return "REVIEW_APPROVAL";
  if (hasTransferSignal(assessment)) return "REVIEW_TRANSFER_EVIDENCE";
  if (isCoverageOnlyAssessment(assessment) || isPartialOrUnknown(assessment.dataStatus)) return "RECORD_ASSESSMENT_ONLY";
  if (!directSignalCount(assessment) && hasSufficientCoverage(assessment)) return "WATCH";
  return "RECORD_ASSESSMENT_ONLY";
}

function getActionType(decisionType: string, assessment: Assessment, scan?: ScanResponse | null): string {
  const simulation = getSimulationAvailability(assessment, scan || null);
  if (decisionType === "PAUSE") return "REVIEW_APPROVAL";
  if (decisionType === "REVIEW_APPROVAL") {
    if (simulation.available) return "SIMULATE_REVOKE_APPROVAL";
    if (hasTransferSignal(assessment)) return isPartialOrUnknown(assessment.dataStatus) ? "CHECK_SOURCE_COVERAGE_INSPECT_TRANSFER" : "INSPECT_TRANSFER_EVIDENCE";
    return isPartialOrUnknown(assessment.dataStatus) ? "CHECK_SOURCE_COVERAGE" : "REVIEW_APPROVAL";
  }
  if (decisionType === "REVIEW_TRANSFER_EVIDENCE") {
    return isPartialOrUnknown(assessment.dataStatus) ? "CHECK_SOURCE_COVERAGE_INSPECT_TRANSFER" : "INSPECT_TRANSFER_EVIDENCE";
  }
  if (decisionType === "RECORD_ASSESSMENT_ONLY") {
    return isCoverageOnlyAssessment(assessment) || isPartialOrUnknown(assessment.dataStatus) ? "CHECK_SOURCE_COVERAGE" : "RECORD_ASSESSMENT_ONLY";
  }
  if (decisionType === "WATCH") return "WATCH";
  if (simulation.available || hasApprovalSignal(assessment, scan || null)) return "SIMULATE_REVOKE_APPROVAL";
  return "NO_ACTION";
}

function hasCriticalRedFlag(assessment: Assessment): boolean {
  const riskLevel = normalize(assessment.riskLevel);
  return (
    riskLevel.includes("critical") ||
    (assessment.topRisks || []).some((risk) => normalize(risk.severity || risk.severity_v2).includes("critical") || Boolean(risk.isBlocking || risk.is_blocking))
  );
}

function hasApprovalSignal(assessment: Assessment, scan?: ScanResponse | null): boolean {
  if (scan) return hasActiveApprovalEvidence(scan, evidenceIdsForRisk(assessment, ["approval", "allowance", "spender", "unlimited"]));
  if (hasDirectRisk(assessment, ["approval", "allowance", "spender", "unlimited"])) return true;
  return false;
}

function hasTransferSignal(assessment: Assessment): boolean {
  return hasDirectRisk(assessment, ["transfer", "poison", "dust", "lookalike"]);
}

function hasActiveApprovalEvidence(scan: ScanResponse, evidenceIds: string[]): boolean {
  const ids = new Set(evidenceIds);
  const hasScopedIds = ids.size > 0;
  const approvalRows = scan.history?.approvalHistory?.items || [];
  if (
    approvalRows.some((item) => {
      const rowEvidenceIds = [item.evidenceId, ...(item.evidenceIds || [])].filter(Boolean) as string[];
      const matches = !hasScopedIds || rowEvidenceIds.some((id) => ids.has(id));
      return matches && item.isActive !== false && Boolean(item.allowanceConfirmed || item.isUnlimited || item.isActive);
    })
  ) {
    return true;
  }
  return (scan.evidenceBundle?.evidence || []).some((item) => {
    const matches = !hasScopedIds || ids.has(item.evidenceId);
    const text = `${item.type || ""} ${item.source || ""} ${item.claimText || ""} ${item.endpoint || ""}`.toLowerCase();
    return (
      matches &&
      (text.includes("approval") || text.includes("allowance")) &&
      Boolean(item.allowanceConfirmed || text.includes("active allowance") || text.includes("unlimited approval"))
    );
  });
}

function hasSufficientCoverage(assessment: Assessment): boolean {
  const normalized = normalize(assessment.dataStatus);
  return Boolean(normalized.includes("full") || normalized.includes("complete") || normalized.includes("available"));
}

function evidenceIdsForRisk(assessment: Assessment, keywords: string[]): string[] {
  return uniqueIds(
    (assessment.topRisks || [])
      .filter((risk) => {
        const text = riskText(risk);
        return keywords.some((keyword) => text.includes(keyword));
      })
      .flatMap((risk) => risk.evidenceIds || risk.evidence_ids || [])
  );
}

function inventoryEvidenceIds(scan?: ScanResponse | null): string[] {
  return uniqueIds((scan?.inventory?.tokens || []).flatMap((token) => [token.evidenceId, ...(token.evidenceIds || [])].filter(Boolean) as string[]));
}

function tokenBalanceExists(scan?: ScanResponse | null): boolean {
  return Boolean(
    scan?.inventory?.tokens?.some((token) => {
      const numericBalance = Number(token.balance || 0);
      return numericBalance > 0 || Boolean(token.balanceRaw && token.balanceRaw !== "0");
    })
  );
}

function uniqueIds(values: Array<string | undefined | null>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value && value.trim()))));
}
