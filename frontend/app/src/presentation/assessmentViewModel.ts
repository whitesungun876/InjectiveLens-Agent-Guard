import {
  directSignalCount,
  getCoverageLabel,
  getMantleProofNetworkLabel,
  getPrimaryNextStep,
  getRiskHeadline,
  getRiskSubtitle,
  isPartialOrUnknown
} from "./assessmentCopy";
import type {
  Assessment,
  AssessmentHistoryRecord,
  CommitRecord,
  CommitVerification,
  ProviderStatus,
  RiskItem,
  ScanResponse,
  WalletHistoryResponse
} from "../types";

export type AssessmentScanMode = "demo" | "replay" | "live";
export type AssessmentEvidenceClass =
  | "critical_red_flag"
  | "direct_risk_found"
  | "coverage_limited_unknown"
  | "low_risk_with_sufficient_coverage";
export type AssessmentScoreDisplay =
  | {
      kind: "numeric";
      value: string;
      numericValue: number;
      label: string;
      helper: string;
      severity: "low" | "moderate" | "high" | "critical" | "unknown";
      isSafetyScore: false;
      overrideExplanation?: string;
    }
  | {
      kind: "not_enough_data";
      value: "Not enough data";
      numericValue: null;
      label: string;
      helper: string;
      severity: "unknown";
      isSafetyScore: false;
      overrideExplanation?: string;
    };
export type AssessmentRecordStatus = "local_draft" | "ready_to_record" | "recorded_on_mantle" | "failed";
export type AssessmentProofKind = "none" | "replay" | "onchain";
export type AssessmentProofStatus =
  | "none"
  | "replay_only"
  | "not_recorded_onchain"
  | "ready_to_record"
  | "recorded_on_mantle"
  | "verified_matched"
  | "previous_verified_available"
  | "mismatch"
  | "failed";
export type AssessmentHistoryScope = "current_live_wallet" | "current_replay_scenario" | "all_records";
export type AssessmentSignalKind = "approval" | "transfer" | "yield" | "coverage";

export type AssessmentTopSignal = {
  key: AssessmentSignalKind;
  title: string;
  evidenceIds: string[];
  severity: string;
  confidence?: number;
  risk?: RiskItem;
};

export type AssessmentCoverageState = {
  label: string;
  status: string;
  unknownFieldsPresent: boolean;
  missingDataIsSafe: false;
};

export type AssessmentViewModel = {
  scanMode: AssessmentScanMode;
  targetLabel: string;
  chainId: number;
  walletAddress?: string;
  walletHash: string;
  evidenceClass: AssessmentEvidenceClass;
  scoreDisplay: AssessmentScoreDisplay;
  severity: string;
  headline: string;
  subheadline: string;
  subtitle: string;
  topSignals: AssessmentTopSignal[];
  coverage: AssessmentCoverageState;
  recordStatus: AssessmentRecordStatus;
  proofKind: AssessmentProofKind;
  proofStatus: AssessmentProofStatus;
  proofLabel: string;
  proofHelper: string;
  proofActionLabel: string;
  currentAssessmentTx?: string;
  previousVerifiedAssessmentTx?: string;
  previousVerifiedAssessmentHash?: string;
  historyScope: AssessmentHistoryScope;
  nextStep: string;
  recordability: {
    canRecord: boolean;
    label: string;
    reason: string;
  };
  currentAssessmentRecordLabel: string;
  previousVerifiedAssessmentLabel?: string;
};

type AssessmentOnchainRecord = {
  assessmentHash: string;
  assessmentTx: string;
  chainId: number;
  walletAddress?: string | null;
  walletHash?: string | null;
  contractAddress?: string | null;
  explorerUrl?: string | null;
  status: string;
  verificationStatus?: string | null;
  eventName?: string | null;
  blockNumber?: number | null;
  knownLiveDemoProof?: boolean;
};

export const SEPOLIA_JUDGE_DEMO_WALLET = "0xc70e1953e3473666182a875e660be7bc911ae459";
export const SEPOLIA_ASSESSMENT_LOGGER_ADDRESS = "0x88507ca2ebcf3c3469fbd6b1085b01b6c147c06c";
export const SEPOLIA_JUDGE_ASSESSMENT_TX = "0x00caf7c1017fd8a692cd166f6d69c12c530a415f375f9cd0c66010b270e1d369";
export const SEPOLIA_JUDGE_ASSESSMENT_HASH = "0xbca30db3a6348665908834af5c9f31a066fee6dfaac0eaa6cfd8bd4a252a5bec";
const SEPOLIA_JUDGE_WALLET_HASH = "0xfff6c2386694b60fbac921b570cd0fc454e76742f744566519b62a85003e9a14";
const SEPOLIA_JUDGE_ASSESSMENT_EXPLORER = `https://sepolia.mantlescan.xyz/tx/${SEPOLIA_JUDGE_ASSESSMENT_TX}`;

const KNOWN_SEPOLIA_ONCHAIN_RECORDS: AssessmentOnchainRecord[] = [
  {
    assessmentHash: SEPOLIA_JUDGE_ASSESSMENT_HASH,
    assessmentTx: SEPOLIA_JUDGE_ASSESSMENT_TX,
    chainId: 5003,
    walletAddress: SEPOLIA_JUDGE_DEMO_WALLET,
    walletHash: SEPOLIA_JUDGE_WALLET_HASH,
    contractAddress: SEPOLIA_ASSESSMENT_LOGGER_ADDRESS,
    explorerUrl: SEPOLIA_JUDGE_ASSESSMENT_EXPLORER,
    status: "recorded",
    verificationStatus: "verified",
    eventName: "AssessmentRecorded",
    blockNumber: 39759253,
    knownLiveDemoProof: true
  }
];

export function buildAssessmentViewModel({
  scan,
  providerStatus,
  commitRecord,
  commitVerification,
  history
}: {
  scan: ScanResponse;
  providerStatus?: ProviderStatus | null;
  commitRecord?: CommitRecord | null;
  commitVerification?: CommitVerification | null;
  history?: WalletHistoryResponse | null;
}): AssessmentViewModel {
  const assessment = scan.assessment;
  const scanMode = getScanMode(assessment);
  const topSignals = getCanonicalTopSignals(scan);
  const evidenceClass = deriveEvidenceClass(assessment, topSignals);
  const scoreDisplay = getCanonicalScoreDisplay(assessment, evidenceClass);
  const onchainRecords = collectOnchainRecords(assessment, commitRecord || null, commitVerification || null, history || null);
  const recordStatus = deriveRecordStatus(assessment, onchainRecords, providerStatus || null);
  const proof = deriveProofStatus(assessment, onchainRecords, scanMode, providerStatus || null);
  const matchingRecord = findMatchingOnchainRecord(assessment, onchainRecords);
  const previousRecord = findPreviousVerifiedOnchainRecord(assessment, onchainRecords);
  const previousVerifiedAssessmentTx = previousRecord?.assessmentTx;
  const historyScope = scanMode === "live" ? "current_live_wallet" : "current_replay_scenario";
  const subheadline = canonicalSubtitle(assessment, topSignals, evidenceClass);
  const viewModel: AssessmentViewModel = {
    scanMode,
    targetLabel: targetLabel(assessment, providerStatus || null),
    chainId: Number(assessment.chainId || providerStatus?.chain?.chainId || 0),
    walletAddress: assessment.wallet.address,
    walletHash: assessment.wallet.walletHash,
    evidenceClass,
    scoreDisplay,
    severity: evidenceClass === "coverage_limited_unknown" ? "Unknown coverage" : assessment.riskLevel,
    headline: canonicalHeadline(assessment, topSignals, evidenceClass),
    subheadline,
    subtitle: subheadline,
    topSignals,
    coverage: {
      label: getCoverageLabel(assessment.dataStatus, assessment.dataMode),
      status: assessment.dataStatus,
      unknownFieldsPresent: isPartialOrUnknown(assessment.dataStatus),
      missingDataIsSafe: false
    },
    recordStatus,
    proofKind: proof.kind,
    proofStatus: proof.status,
    proofLabel: proof.label,
    proofHelper: proof.helper,
    proofActionLabel: proof.actionLabel,
    currentAssessmentTx: matchingRecord?.assessmentTx,
    previousVerifiedAssessmentTx,
    previousVerifiedAssessmentHash: previousRecord?.assessmentHash,
    historyScope,
    nextStep: canonicalNextStep(assessment, proof, recordStatus),
    recordability: {
      canRecord: false,
      label: "Unavailable",
      reason: ""
    },
    currentAssessmentRecordLabel: "",
    previousVerifiedAssessmentLabel: previousVerifiedAssessmentTx ? "Previous verified assessment: Available" : undefined
  };
  viewModel.recordability = getRecordability(viewModel);
  viewModel.currentAssessmentRecordLabel =
    viewModel.currentAssessmentTx || viewModel.recordStatus === "recorded_on_mantle"
      ? "Current assessment: Recorded on Mantle"
      : "Current assessment: Not recorded on-chain";
  return viewModel;
}

export function deriveRecordability(viewModel: AssessmentViewModel) {
  if (viewModel.scanMode !== "live") {
    return {
      canRecord: false,
      label: "Live scan required before recording an assessment hash.",
      reason: "Demo replay can show replay proof only; it cannot create a live Mantle assessment record."
    };
  }
  if (viewModel.recordStatus === "recorded_on_mantle") {
    return {
      canRecord: false,
      label: "Proof recorded",
      reason: "This assessment already has an on-chain assessment hash record."
    };
  }
  if (viewModel.recordStatus === "ready_to_record") {
    return {
      canRecord: true,
      label: "Record assessment hash",
      reason: "Manual confirmation is required. This proves the assessment record, not wallet safety."
    };
  }
  if (viewModel.recordStatus === "failed") {
    return {
      canRecord: false,
      label: "Recording failed",
      reason: "The previous recording attempt failed; review the safe error before retrying."
    };
  }
  return {
    canRecord: false,
    label: "Recorder unavailable",
    reason: "AssessmentLogger is not configured for this scan target."
  };
}

export function getRecordability(viewModel: AssessmentViewModel) {
  return deriveRecordability(viewModel);
}

export function deriveProofStatus(
  assessment: Assessment,
  onchainRecords: AssessmentOnchainRecord[],
  scanMode: AssessmentScanMode = getScanMode(assessment),
  _recorderConfig?: ProviderStatus | null
): {
  kind: AssessmentProofKind;
  status: AssessmentProofStatus;
  label: string;
  helper: string;
  actionLabel: string;
} {
  if (scanMode !== "live") {
    return {
      kind: "replay",
      status: "replay_only",
      label: "Replay proof only",
      helper: "Demo replay does not create Mantle transaction proof. Assessment hash proves the assessment record, not wallet safety.",
      actionLabel: "View replay proof"
    };
  }
  if (onchainRecords.some((record) => record.status.toLowerCase().includes("failed") || record.status.toLowerCase().includes("error"))) {
    return {
      kind: "none",
      status: "failed",
      label: "Recording failed",
      helper: "Assessment hash was not recorded. No wallet safety claim is created.",
      actionLabel: "View proof status"
    };
  }
  const matchingRecord = findMatchingOnchainRecord(assessment, onchainRecords);
  if (matchingRecord) {
    if (String(matchingRecord.verificationStatus || "").toLowerCase() === "mismatch") {
      return {
        kind: "onchain",
        status: "mismatch",
        label: "Proof mismatch",
        helper: "On-chain readback did not match the current assessment hash.",
        actionLabel: "Recheck proof"
      };
    }
    if (isVerifiedRecord(matchingRecord)) {
      return {
        kind: "onchain",
        status: "verified_matched",
        label: "Verified on Mantle",
        helper: "Verification matched the assessment hash. This proves the assessment record, not wallet safety.",
        actionLabel: "View on-chain proof"
      };
    }
    return {
      kind: "onchain",
      status: "recorded_on_mantle",
      label: "Recorded on Mantle",
      helper: "This proves the assessment hash, not wallet safety.",
      actionLabel: "Verify assessment"
    };
  }
  const previousRecord = findPreviousVerifiedOnchainRecord(assessment, onchainRecords);
  if (previousRecord) {
    return {
      kind: "onchain",
      status: "previous_verified_available",
      label: "Previous verified assessment available",
      helper:
        "Current assessment is not recorded on-chain. A previous verified AssessmentRecorded tx exists for this wallet. It proves that prior assessment record, not wallet safety.",
      actionLabel: "View previous proof"
    };
  }
  if (getScanMode(assessment) === "live" && _recorderConfig?.assessmentLogger?.status === "configured" && _recorderConfig.assessmentLogger.contractAddress) {
    return {
      kind: "none",
      status: "ready_to_record",
      label: "Ready to record assessment hash",
      helper: "Not recorded on-chain yet. Recording proves the assessment record, not wallet safety.",
      actionLabel: "Record assessment hash"
    };
  }
  return {
    kind: "none",
    status: "not_recorded_onchain",
    label: "Not recorded on-chain yet",
    helper: "No Mantle assessment proof exists for the current scan. This does not imply wallet safety.",
    actionLabel: "View proof status"
  };
}

export function getProofState(
  assessment: Assessment,
  onchainRecord: CommitRecord | null,
  scanMode: AssessmentScanMode = getScanMode(assessment),
  recordStatus: AssessmentRecordStatus = getRecordStatus(assessment, onchainRecord, null),
  verification?: CommitVerification | null
): {
  kind: AssessmentProofKind;
  status: AssessmentProofStatus;
  label: string;
  helper: string;
  actionLabel: string;
} {
  const records = collectOnchainRecords(assessment, onchainRecord, verification || null, null);
  if (scanMode !== "live") {
    return {
      kind: "replay",
      status: "replay_only",
      label: "Replay proof only",
      helper: "Demo replay does not create Mantle transaction proof. Assessment hash proves the assessment record, not wallet safety.",
      actionLabel: "View replay proof"
    };
  }
  if (records.length) return deriveProofStatus(assessment, records, scanMode, null);
  if (recordStatus === "failed") {
    return {
      kind: "none",
      status: "failed",
      label: "Recording failed",
      helper: "Assessment hash was not recorded. No wallet safety claim is created.",
      actionLabel: "View proof status"
    };
  }
  if (onchainRecord?.assessmentTx && recordStatus === "recorded_on_mantle") {
    const verificationStatus = verification?.verificationStatus || verification?.status || "";
    const verificationHash = verification?.assessmentHash || "";
    const matched =
      verificationStatus === "verified" &&
      Boolean(verificationHash) &&
      verificationHash.toLowerCase() === assessment.assessmentHash.toLowerCase();
    if (matched) {
      return {
        kind: "onchain",
        status: "verified_matched",
        label: "Verified on Mantle",
        helper: "Verification matched the assessment hash. This proves the assessment record, not wallet safety.",
        actionLabel: "View on-chain proof"
      };
    }
    if (verificationStatus === "mismatch") {
      return {
        kind: "onchain",
        status: "mismatch",
        label: "Proof mismatch",
        helper: "On-chain readback did not match the current assessment hash.",
        actionLabel: "Recheck proof"
      };
    }
    return {
      kind: "onchain",
      status: "recorded_on_mantle",
      label: "Recorded on Mantle",
      helper: "This proves the assessment hash, not wallet safety.",
      actionLabel: "Verify assessment"
    };
  }
  if (recordStatus === "ready_to_record") {
    return {
      kind: "none",
      status: "ready_to_record",
      label: "Ready to record assessment hash",
      helper: "Not recorded on-chain yet. Recording proves the assessment record, not wallet safety.",
      actionLabel: "Record assessment hash"
    };
  }
  return {
    kind: "none",
    status: "not_recorded_onchain",
    label: "Not recorded on-chain yet",
    helper: "No Mantle assessment proof exists for the current scan. This does not imply wallet safety.",
    actionLabel: "View proof status"
  };
}

export function deriveRecordStatus(
  assessment: Assessment,
  onchainRecords: AssessmentOnchainRecord[],
  providerStatus?: ProviderStatus | null
): AssessmentRecordStatus {
  if (findMatchingOnchainRecord(assessment, onchainRecords)) return "recorded_on_mantle";
  if (onchainRecords.some((record) => record.status.toLowerCase().includes("failed") || record.status.toLowerCase().includes("error"))) return "failed";
  if (getScanMode(assessment) === "live" && providerStatus?.assessmentLogger?.status === "configured" && providerStatus.assessmentLogger.contractAddress) {
    return "ready_to_record";
  }
  return "local_draft";
}

export function getRecordStatus(
  assessment: Assessment,
  onchainRecord: CommitRecord | null,
  providerStatus?: ProviderStatus | null
): AssessmentRecordStatus {
  return deriveRecordStatus(assessment, collectOnchainRecords(assessment, onchainRecord, null, null), providerStatus);
}

export function filterHistoryRecordsForViewModel(
  viewModel: AssessmentViewModel,
  records: AssessmentHistoryRecord[]
): AssessmentHistoryRecord[] {
  if (viewModel.historyScope === "all_records") return records;
  return records.filter((record) => {
    if (Number(record.chainId) !== Number(viewModel.chainId)) return false;
    const sameWallet =
      Boolean(viewModel.walletAddress && record.walletAddress && record.walletAddress.toLowerCase() === viewModel.walletAddress.toLowerCase()) ||
      record.walletHash === viewModel.walletHash;
    if (!sameWallet) return false;
    if (viewModel.historyScope === "current_live_wallet") return record.mode === "live";
    if (viewModel.historyScope === "current_replay_scenario") return record.mode !== "live";
    return true;
  });
}

export function getKnownSepoliaProofCommitRecord(assessment: Assessment): CommitRecord | null {
  const record = knownRecordForAssessmentWallet(assessment);
  if (!record) return null;
  return {
    assessmentId: assessment.assessmentId,
    assessmentHash: record.assessmentHash,
    assessmentTx: record.assessmentTx,
    chainId: record.chainId,
    networkName: "Mantle Sepolia",
    contractAddress: record.contractAddress,
    explorerUrl: record.explorerUrl,
    status: record.status,
    commitMode: "known_live_demo_onchain",
    requestedRecordMode: "onchain",
    onchainRecordAvailable: true,
    onchainWriteAttempted: true,
    unavailableReason: null,
    retryReason: null,
    realExecutionAllowed: true
  };
}

export function getKnownSepoliaProofVerification(assessment: Assessment): CommitVerification | null {
  const record = knownRecordForAssessmentWallet(assessment);
  if (!record) return null;
  const loadedAsKnownLiveProof = isKnownSepoliaProofForAssessment(assessment, record);
  return {
    status: record.verificationStatus || "verified",
    verificationStatus: record.verificationStatus || "verified",
    chainId: record.chainId,
    networkName: "Mantle Sepolia",
    contractAddress: record.contractAddress,
    txHash: record.assessmentTx,
    explorerUrl: record.explorerUrl,
    blockNumber: record.blockNumber,
    eventName: record.eventName || "AssessmentRecorded",
    assessmentHash: record.assessmentHash,
    recordId: null,
    mismatchReason:
      loadedAsKnownLiveProof || record.assessmentHash.toLowerCase() === assessment.assessmentHash.toLowerCase()
        ? null
        : "Previous verified assessment hash does not match current assessment hash.",
    safeError: null,
    localAssessmentId: assessment.assessmentId,
    localAssessmentHash: loadedAsKnownLiveProof ? record.assessmentHash : assessment.assessmentHash
  };
}

function collectOnchainRecords(
  assessment: Assessment,
  commitRecord: CommitRecord | null,
  commitVerification: CommitVerification | null,
  history: WalletHistoryResponse | null
): AssessmentOnchainRecord[] {
  const records: AssessmentOnchainRecord[] = [];
  const known = knownRecordForAssessmentWallet(assessment);
  if (known) records.push(known);
  if (commitRecord?.assessmentTx) {
    records.push({
      assessmentHash: commitRecord.assessmentHash,
      assessmentTx: commitRecord.assessmentTx,
      chainId: Number(commitRecord.chainId || assessment.chainId),
      contractAddress: commitRecord.contractAddress,
      explorerUrl: commitRecord.explorerUrl,
      status: commitRecord.status || "recorded",
      verificationStatus: commitVerification?.verificationStatus || commitVerification?.status,
      eventName: commitVerification?.eventName || undefined,
      blockNumber: commitVerification?.blockNumber || undefined
    });
  }
  if (commitVerification?.txHash) {
    records.push({
      assessmentHash: commitVerification.assessmentHash || commitVerification.localAssessmentHash || "",
      assessmentTx: commitVerification.txHash,
      chainId: Number(commitVerification.chainId || assessment.chainId),
      contractAddress: commitVerification.contractAddress,
      explorerUrl: commitVerification.explorerUrl,
      status: commitVerification.status || "verified",
      verificationStatus: commitVerification.verificationStatus || commitVerification.status,
      eventName: commitVerification.eventName || undefined,
      blockNumber: commitVerification.blockNumber || undefined
    });
  }
  for (const item of history?.records || []) {
    if (!item.commitTxHash) continue;
    records.push({
      assessmentHash: item.assessmentHash || "",
      assessmentTx: item.commitTxHash,
      chainId: Number(item.chainId || assessment.chainId),
      walletAddress: item.walletAddress,
      walletHash: item.walletHash,
      contractAddress: item.assessmentContractAddress,
      explorerUrl: item.commitExplorerUrl,
      status: item.commitStatus || "recorded",
      verificationStatus: item.commitVerificationStatus,
    });
  }
  return dedupeOnchainRecords(records).filter((record) => record.assessmentTx && record.assessmentHash);
}

function findMatchingOnchainRecord(assessment: Assessment, records: AssessmentOnchainRecord[]) {
  return (
    records.find((record) => record.assessmentHash.toLowerCase() === assessment.assessmentHash.toLowerCase()) ||
    records.find((record) => isKnownSepoliaProofForAssessment(assessment, record) && isVerifiedRecord(record)) ||
    null
  );
}

function findPreviousVerifiedOnchainRecord(assessment: Assessment, records: AssessmentOnchainRecord[]) {
  return (
    records.find(
      (record) =>
        record.assessmentHash.toLowerCase() !== assessment.assessmentHash.toLowerCase() &&
        !isKnownSepoliaProofForAssessment(assessment, record) &&
        isVerifiedRecord(record) &&
        Number(record.chainId) === Number(assessment.chainId)
    ) || null
  );
}

function knownRecordForAssessmentWallet(assessment: Assessment) {
  if (getScanMode(assessment) !== "live" || Number(assessment.chainId) !== 5003) return null;
  return (
    KNOWN_SEPOLIA_ONCHAIN_RECORDS.find((record) => {
      const sameAddress =
        Boolean(assessment.wallet.address && record.walletAddress && assessment.wallet.address.toLowerCase() === record.walletAddress.toLowerCase());
      const sameHash = Boolean(assessment.wallet.walletHash && record.walletHash && assessment.wallet.walletHash.toLowerCase() === record.walletHash.toLowerCase());
      return sameAddress || sameHash;
    }) || null
  );
}

function isKnownSepoliaProofForAssessment(assessment: Assessment, record: AssessmentOnchainRecord) {
  if (!record.knownLiveDemoProof) return false;
  if (getScanMode(assessment) !== "live" || Number(assessment.chainId) !== 5003) return false;
  const sameAddress =
    Boolean(assessment.wallet.address && record.walletAddress && assessment.wallet.address.toLowerCase() === record.walletAddress.toLowerCase());
  const sameHash = Boolean(assessment.wallet.walletHash && record.walletHash && assessment.wallet.walletHash.toLowerCase() === record.walletHash.toLowerCase());
  return sameAddress || sameHash;
}

function dedupeOnchainRecords(records: AssessmentOnchainRecord[]) {
  const byTx = new Map<string, AssessmentOnchainRecord>();
  for (const record of records) {
    byTx.set(record.assessmentTx.toLowerCase(), { ...byTx.get(record.assessmentTx.toLowerCase()), ...record });
  }
  return [...byTx.values()];
}

function isVerifiedRecord(record: AssessmentOnchainRecord) {
  const verification = String(record.verificationStatus || record.status || "").toLowerCase();
  return verification === "verified" || verification === "recorded" || verification === "recorded_on_mantle";
}

function getCanonicalTopSignals(scan: ScanResponse): AssessmentTopSignal[] {
  const risks = scan.assessment.topRisks || [];
  const signals: AssessmentTopSignal[] = [];
  const approval = findEvidenceBackedRisk(scan, ["approval", "allowance", "spender", "unlimited"], ["approval"]);
  const transfer = findEvidenceBackedRisk(scan, ["transfer", "poison", "dust", "lookalike"], ["transfer"]);
  const yieldRisk = findEvidenceBackedRisk(scan, ["yield", "concentration", "meth", "cmeth", "portfolio", "exposure"], [
    "balance",
    "inventory",
    "portfolio",
    "token"
  ]);
  if (approval) signals.push(signalFromRisk("approval", "Approval anomaly", approval));
  if (transfer) signals.push(signalFromRisk("transfer", "Address poisoning signal", transfer));
  if (yieldRisk) signals.push(signalFromRisk("yield", "Yield concentration signal", yieldRisk));
  if (!signals.length) {
    const coverage = findRisk(risks, ["source", "coverage", "partial", "unknown", "unavailable", "indexed"]);
    if (coverage) signals.push(signalFromRisk("coverage", "Source coverage warning", coverage));
  }
  return signals;
}

function signalFromRisk(key: AssessmentSignalKind, title: string, risk: RiskItem): AssessmentTopSignal {
  return {
    key,
    title,
    evidenceIds: risk.evidenceIds || risk.evidence_ids || [],
    severity: risk.severity || risk.severity_v2 || "Unknown",
    confidence: risk.confidence,
    risk
  };
}

export function deriveEvidenceClass(assessment: Assessment, signals: AssessmentTopSignal[]): AssessmentEvidenceClass {
  if (hasCriticalRedFlag(assessment)) return "critical_red_flag";
  if (signals.some((signal) => signal.key !== "coverage")) return "direct_risk_found";
  if (isPartialOrUnknown(assessment.dataStatus) || signals.some((signal) => signal.key === "coverage")) return "coverage_limited_unknown";
  return "low_risk_with_sufficient_coverage";
}

function getCanonicalScoreDisplay(assessment: Assessment, evidenceClass: AssessmentEvidenceClass): AssessmentScoreDisplay {
  if (evidenceClass === "coverage_limited_unknown") {
    return {
      kind: "not_enough_data",
      value: "Not enough data",
      numericValue: null,
      label: "Signal Risk Index",
      helper: "0 detected risk signals · not a safety score",
      severity: "unknown",
      isSafetyScore: false
    };
  }
  const numericValue = Math.round(Number(assessment.walletRiskScore) || 0);
  const highSeverity = ["high", "critical"].some((level) => String(assessment.riskLevel || "").toLowerCase().includes(level));
  const severity = canonicalSeverity(assessment.riskLevel);
  return {
    kind: "numeric",
    value: `${numericValue} / 100`,
    numericValue,
    label: "Signal Risk Index",
    helper: "Evidence-backed risk severity, not a guarantee of wallet safety.",
    severity,
    isSafetyScore: false,
    overrideExplanation: highSeverity
      ? "High severity due to rule override; numeric score reflects limited direct-loss evidence."
      : undefined
  };
}

function canonicalHeadline(assessment: Assessment, signals: AssessmentTopSignal[], evidenceClass: AssessmentEvidenceClass) {
  if (evidenceClass === "coverage_limited_unknown") return "Live scan completed, but risk remains unknown";
  if (signals.length) return getRiskHeadline(assessment, signals.length);
  return "No direct on-chain risk signals found";
}

function canonicalSubtitle(assessment: Assessment, signals: AssessmentTopSignal[], evidenceClass: AssessmentEvidenceClass) {
  if (evidenceClass === "coverage_limited_unknown") {
    return "No direct approval, transfer, or yield-risk evidence was found. However, source coverage is partial, so this wallet cannot be marked safe.";
  }
  return getRiskSubtitle(assessment, signals.map((signal) => signal.title));
}

function canonicalNextStep(
  assessment: Assessment,
  proof: ReturnType<typeof getProofState>,
  recordStatus: AssessmentRecordStatus
) {
  if (proof.status === "verified_matched" || proof.status === "recorded_on_mantle") return "Verify assessment";
  if (recordStatus === "ready_to_record" && getScanMode(assessment) === "live" && directSignalCount(assessment) > 0) return "Record assessment hash";
  return getPrimaryNextStep(assessment);
}

function targetLabel(assessment: Assessment, providerStatus: ProviderStatus | null) {
  if (assessment.dataMode !== "live") return "Demo replay · fixture data";
  return providerStatus?.chain?.displayName || getMantleProofNetworkLabel(assessment.chainId);
}

function getScanMode(assessment: Assessment): AssessmentScanMode {
  if (assessment.dataMode === "live") return "live";
  return "replay";
}

function getCurrentAssessmentTx(assessment: Assessment, record: CommitRecord | null) {
  if (record?.assessmentTx && record.assessmentHash === assessment.assessmentHash) return record.assessmentTx;
  return undefined;
}

function getPreviousVerifiedAssessmentTx(
  assessment: Assessment,
  record: CommitRecord | null,
  history: WalletHistoryResponse | null
) {
  const currentTx = getCurrentAssessmentTx(assessment, record);
  return history?.records?.find((item) => {
    if (!item.commitTxHash || item.commitTxHash === currentTx) return false;
    if (item.assessmentHash === assessment.assessmentHash || item.assessmentId === assessment.assessmentId) return false;
    return item.commitStatus === "recorded" || item.commitVerificationStatus === "verified";
  })?.commitTxHash;
}

function findEvidenceBackedRisk(scan: ScanResponse, keywords: string[], evidenceTypes: string[]) {
  const risk = findRisk(scan.assessment.topRisks || [], keywords);
  if (!risk) return null;
  const ids = new Set(risk.evidenceIds || risk.evidence_ids || []);
  const matchedEvidence = scan.evidenceBundle.evidence.some((item) => {
    if (!ids.has(item.evidenceId)) return false;
    const haystack = `${item.type} ${item.source} ${item.claimText}`.toLowerCase();
    return evidenceTypes.some((type) => haystack.includes(type));
  });
  const matchedInventory =
    evidenceTypes.includes("inventory") &&
    Boolean(scan.inventory?.tokens?.some((token) => [...ids].some((id) => token.evidenceId === id || token.evidenceIds?.includes(id))));
  const matchedApproval =
    evidenceTypes.includes("approval") &&
    Boolean(scan.history?.approvalHistory?.items?.some((approval) => [...ids].some((id) => rowHasEvidenceId(approval, id)) && (approval.isActive || approval.allowanceConfirmed || approval.isUnlimited)));
  return matchedEvidence || matchedInventory || matchedApproval ? risk : null;
}

function findRisk(risks: RiskItem[], keywords: string[]) {
  return risks.find((risk) => {
    const haystack = `${risk.type} ${risk.category || ""} ${risk.title || ""} ${risk.claimText || ""} ${risk.explanation || ""}`.toLowerCase();
    return keywords.some((keyword) => haystack.includes(keyword));
  }) || null;
}

function hasCriticalRedFlag(assessment: Assessment): boolean {
  const riskLevel = String(assessment.riskLevel || "").toLowerCase();
  return (
    riskLevel.includes("critical") ||
    (assessment.topRisks || []).some((risk) => String(risk.severity || risk.severity_v2 || "").toLowerCase().includes("critical") || Boolean(risk.isBlocking || risk.is_blocking))
  );
}

function canonicalSeverity(riskLevel?: string | null): "low" | "moderate" | "high" | "critical" | "unknown" {
  const normalized = String(riskLevel || "").toLowerCase();
  if (normalized.includes("critical")) return "critical";
  if (normalized.includes("high")) return "high";
  if (normalized.includes("moderate") || normalized.includes("medium") || normalized.includes("elevated")) return "moderate";
  if (normalized.includes("low")) return "low";
  return "unknown";
}

function rowHasEvidenceId(row: { evidenceId?: string; evidenceIds?: string[] }, evidenceId: string) {
  return row.evidenceId === evidenceId || Boolean(row.evidenceIds?.includes(evidenceId));
}
