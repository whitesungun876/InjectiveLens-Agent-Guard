export type DataMode = "demo" | "live";

export type ScanRequest = {
  dataMode: DataMode;
  scanMode?: DataMode;
  fixtureId: string;
  benchmarkCaseId?: string;
  benchmarkCaseLabel?: string;
  walletAddress?: string;
  targetId?: string;
  chainId?: number | null;
  historyOptions?: {
    pageSize: number;
    maxPages: number;
    fromBlock: number;
    toBlock: "latest";
    sort: "desc";
  };
  includeExplanation: boolean;
};

export type ChainTarget = {
  id: string;
  name: string;
  chainId: number | null;
  environment: "testnet" | "mainnet" | "custom" | string;
  explorerBaseUrl?: string | null;
  nativeSymbol?: string;
  enabled: boolean;
  comingSoon?: boolean;
  supportsReadOnlyScan: boolean;
  supportsAssessmentCommit: boolean;
  knownTokenAllowlistKey?: string | null;
  label: string;
  description?: string;
};

export type ProviderStatus = {
  schemaVersion: string;
  chain: {
    chainId: number;
    networkName: string;
    displayName: string;
  };
  defaultTargetId?: string;
  chainTargets?: ChainTarget[];
  rpc: {
    configured: boolean;
    provider: string;
  };
  assessmentLogger: {
    status: "configured" | "unavailable" | "mocked" | "error" | string;
    contractAddress?: string | null;
    explorerBaseUrl?: string | null;
    privateKeyConfigured?: boolean;
    mode?: string;
  };
  sources: Record<string, { status: string; limitation?: string }>;
  secrets: {
    privateKeysExposed: boolean;
    rawRpcUrlExposed: boolean;
    rawApiKeysExposed: boolean;
  };
};

export type Assessment = {
  assessmentId: string;
  assessmentHash: string;
  timestamp?: string;
  walletRiskScore: number;
  riskLevel: string;
  dataConfidence: number;
  dataStatus: string;
  dataMode: string;
  fixtureId?: string;
  benchmarkCase?: {
    id?: string;
    label?: string;
  };
  chainId: number;
  wallet: {
    address?: string;
    walletHash: string;
  };
  topRisks: RiskItem[];
  suggestedActions: SuggestedAction[];
  metricResults?: MetricResult[];
  scoreBreakdown?: ScoreBreakdown;
  riskEngine?: {
    schemaVersion: string;
    status: string;
    dataConfidence: number;
    allRisks: RiskItem[];
    supplementalScores?: Record<string, number>;
    scoreBreakdown: ScoreBreakdown;
  };
};

export type MetricResult = {
  metricId: string;
  label: string;
  score: number;
  weight: number;
  weightedContribution: number;
  severity: string;
  evidenceIds: string[];
  calculationMode: string;
  limitations?: string[];
};

export type RiskItem = {
  riskId: string;
  risk_id?: string;
  type: string;
  category?: string;
  title?: string;
  severity: string;
  severity_v2?: string;
  claimText: string;
  explanation?: string;
  scoreImpact: number;
  score_impact?: number;
  scoreContribution?: number;
  score_contribution?: number;
  confidence?: number;
  evidenceIds: string[];
  evidence_ids?: string[];
  sourceStatus?: string;
  source_status?: string;
  recommendedSafeActions?: string[];
  recommended_safe_actions?: string[];
  isBlocking?: boolean;
  is_blocking?: boolean;
  unknowns?: string[];
  limitations?: string[];
};

export type ScoreBreakdown = {
  schemaVersion: string;
  method: string;
  totalScore: number;
  riskLevel: string;
  riskLevelV2?: string;
  dataConfidence: number;
  weightedMetricSum: number;
  metricContributions: Array<{
    metricId: string;
    score: number;
    weight: number;
    weightedContribution: number;
  }>;
  riskContributions?: Array<{
    riskId: string;
    category: string;
    severity: string;
    scoreImpact: number;
    scoreContribution: number;
    confidence: number;
    evidenceIds: string[];
  }>;
  redFlagOverrides?: Array<Record<string, string>>;
  topRiskIds?: string[];
};

export type SuggestedAction = {
  actionId: string;
  actionType: string;
  label: string;
  executionMode: string;
  evidenceIds: string[];
};

export type DecisionAuditSeverity = "info" | "warning" | "high" | "critical";

export type DecisionAuditReason = {
  label: string;
  description: string;
  evidenceIds?: string[];
  ruleIds?: string[];
  severity?: DecisionAuditSeverity;
};

export type DecisionAuditRule = {
  id: string;
  label: string;
  description: string;
  triggered: boolean;
};

export type DecisionAuditAction = {
  label: string;
  reason: string;
};

export type DecisionAudit = {
  decisionType: string;
  actionType: string;
  decisionLabel: string;
  actionLabel: string;
  why: DecisionAuditReason[];
  hardRules: DecisionAuditRule[];
  blockedActions: DecisionAuditAction[];
  allowedActions: DecisionAuditAction[];
  llmBoundary: string;
  evidenceFirst: boolean;
};

export type EvidenceItem = {
  evidenceId: string;
  type: string;
  claimText: string;
  source: string;
  endpoint?: string;
  rawData?: Record<string, unknown>;
  txHash?: string | null;
  allowanceConfirmed?: boolean;
  timestamp?: string;
  blockNumber?: number | string;
  limitation?: string;
};

export type EvidenceBundle = {
  evidenceBundleHash: string;
  evidenceCount: number;
  evidence: EvidenceItem[];
};

export type Inventory = {
  inventoryStatus: string;
  totalValueUsd: number;
  tokenCount: number;
  tokens: TokenItem[];
};

export type TokenItem = {
  symbol: string;
  tokenAddress: string;
  balance: number;
  balanceRaw: string;
  valueUsd?: number;
  securityStatus?: string;
  balanceSource?: string;
  candidateSource?: string;
  evidenceId?: string;
  evidenceIds?: string[];
};

export type HistoryBucket<T> = {
  status: string;
  items: T[];
  pageInfo?: Record<string, unknown>;
};

export type ApprovalItem = {
  token?: string;
  tokenAddress: string;
  spender?: string;
  isActive?: boolean;
  isUnlimited?: boolean;
  blockNumber?: number;
  txHash?: string | null;
  timestamp?: string;
  observedAt?: string;
  allowanceConfirmed?: boolean;
  evidenceId?: string;
  evidenceIds?: string[];
};

export type TransferItem = {
  token?: string;
  tokenAddress: string;
  direction?: string;
  transferType?: string;
  amount?: string;
  pattern?: string;
  riskLevel?: string;
  blockNumber?: number;
  txHash?: string | null;
  timestamp?: string;
  observedAt?: string;
  counterparty?: string;
  evidenceId?: string;
  evidenceIds?: string[];
};

export type History = {
  approvalHistory?: HistoryBucket<ApprovalItem>;
  transferHistory?: HistoryBucket<TransferItem>;
};

export type TrendPoint = {
  assessmentId: string;
  timestamp: string;
  walletRiskScore: number;
  riskLevel: string;
  dataConfidence: number;
  dataStatus: string;
  assessmentHash: string;
  evidenceBundleHash: string;
  topRiskIds: string[];
};

export type Trend = {
  schemaVersion?: string;
  walletAddress?: string | null;
  walletHash: string;
  chainId?: number | null;
  networkName?: string | null;
  mode?: string | null;
  trendStatus?: string;
  status: string;
  pointCount: number;
  recordCount?: number;
  scoreSeries?: Array<{ assessmentId: string; timestamp: string; value: number }>;
  riskLevelSeries?: Array<{ assessmentId: string; timestamp: string; value: string }>;
  confidenceSeries?: Array<{ assessmentId: string; timestamp: string; value: number }>;
  statusSeries?: Array<{ assessmentId: string; timestamp: string; value: string }>;
  sourceCoverageSeries?: Array<{ assessmentId: string; timestamp: string; summary: Record<string, unknown> }>;
  latestScoreDelta?: number | null;
  latestRiskLevelChange?: { previous: string; current: string; direction: string } | null;
  sourceCoverageChanges?: Array<{ source: string; previous: string; current: string; direction: string }>;
  topRiskCategoryChanges?: { added: string[]; removed: string[] };
  trendSummary?: string;
  comparabilityNotes?: string[];
  points: TrendPoint[];
  delta: null | {
    scoreDelta: number;
    dataConfidenceDelta?: number;
    riskLevelChanged: boolean;
    previousRiskLevel: string;
    currentRiskLevel: string;
    newTopRiskIds: string[];
    improvementConfirmed?: boolean;
  };
};

export type AlertItem = {
  alertId: string;
  alert_id?: string;
  walletHash: string;
  walletAddress?: string | null;
  chainId?: number;
  networkName?: string;
  mode?: string;
  alertType: string;
  type?: string;
  severity: string;
  status: string;
  title: string;
  message: string;
  description?: string;
  evidenceIds: string[];
  evidence_ids?: string[];
  sourceAssessmentHash: string;
  relatedAssessmentHashes?: string[];
  relatedAssessmentId?: string;
  relatedTxHash?: string | null;
  sourceStatus?: string;
  recommendedSafeActions?: string[];
  dedupeKey?: string;
  dedup_key?: string;
  occurrenceCount: number;
  createdAt: string;
  resolvedAt?: string | null;
  resolutionNote?: string | null;
};

export type TraceEvent = {
  eventType: string;
  toolName?: string;
  toState?: string;
  policyDecision?: string;
  message?: string;
};

export type ScanResponse = {
  assessment: Assessment;
  evidenceBundle: EvidenceBundle;
  explanation?: {
    explanation?: string;
    mode?: string;
    claimGuardPassed?: boolean;
  };
  coverage: {
    dataStatus: string;
    dataCompleteness: Record<string, string>;
    sourceAvailability: Record<string, { status: string; limitation?: string }>;
    pageCoverage?: Record<string, Record<string, unknown>>;
    missingDataIsSafe?: boolean;
  };
  integrity?: {
    schemaVersion: string;
    evidenceBinding: {
      status: string;
      evidenceCount: number;
      topRiskCount: number;
      suggestedActionCount: number;
      orphanClaimCount: number;
      orphanClaims: string[];
    };
    sourceIntegrity: {
      status: string;
      missingDataIsSafe: boolean;
      partialSources: string[];
      unavailableSources: string[];
      sourceFailures: Array<{ source: string; status: string; limitation?: string }>;
      incompleteData: string[];
    };
    topRiskEvidenceBound: boolean;
    commitEligibility: {
      localRecordAllowed: boolean;
      onchainRecordAllowed: boolean;
      reason: string;
    };
  };
  inventory?: Inventory | null;
  history?: History | null;
  toolOutputs?: Record<string, { output?: Record<string, unknown>; sourceStatus?: string; dataCoverage?: string }>;
  trend?: Trend | null;
  monitoringTrend?: Trend | null;
  assessmentHistoryRecord?: AssessmentHistoryRecord;
  alerts: AlertItem[];
  trace: {
    runId: string;
    traceId: string;
    events: TraceEvent[];
  };
};

export type SimulationResponse = {
  simulation: {
    simulationType: string;
    executionMode: string;
    before: { walletRiskScore: number };
    after: { walletRiskScore: number };
    scoreDelta: number;
    transactionCreated: boolean;
  };
};

export type WalletHistoryResponse = {
  schemaVersion?: string;
  walletAddress?: string | null;
  walletHash: string;
  chainId?: number | null;
  networkName?: string | null;
  mode?: string | null;
  modeSelection?: string;
  recordCount?: number;
  records?: AssessmentHistoryRecord[];
  trend: Trend;
  benchmarkRecords: CommitRecord[];
  alerts: AlertItem[];
};

export type AssessmentHistoryRecord = {
  historyRecordId: string;
  assessmentId: string;
  walletAddress?: string | null;
  walletHash: string;
  chainId: number;
  networkName: string;
  mode: string;
  fixtureId?: string | null;
  benchmarkCaseId?: string | null;
  benchmarkCaseLabel?: string | null;
  scanTimestamp: string;
  riskScore: number;
  riskLevel: string;
  confidence: number;
  status: string;
  sourceCoverageSummary?: {
    available?: number;
    partial?: number;
    unavailable?: number;
    unknown?: number;
    source_failed?: number;
    statuses?: Record<string, string>;
  };
  topRiskSummaries: Array<{
    riskId: string;
    title: string;
    category: string;
    severity: string;
    evidenceIds: string[];
  }>;
  riskCategories: string[];
  evidenceIds: string[];
  assessmentHash?: string;
  commitTxHash?: string | null;
  commitStatus?: string | null;
  commitMode?: string | null;
  commitExplorerUrl?: string | null;
  commitVerificationStatus?: string | null;
  assessmentContractAddress?: string | null;
  createdAt: string;
};

export type CommitRecord = {
  assessmentId: string;
  assessmentHash: string;
  assessmentTx: string | null;
  chainId?: number | null;
  networkName?: string | null;
  contractAddress?: string | null;
  explorerUrl?: string | null;
  status: string;
  commitMode?: string;
  requestedRecordMode?: string;
  onchainRecordAvailable?: boolean;
  onchainWriteAttempted?: boolean;
  unavailableReason?: string | null;
  retryReason?: string | null;
  realExecutionAllowed: boolean;
};

export type CommitResponse = {
  record: CommitRecord;
};

export type CommitCalldataResponse = {
  status: string;
  method: string;
  to: string;
  contractAddress: string;
  chainId: number;
  networkName: string;
  explorerBaseUrl: string;
  value: string;
  data: string;
  assessmentHash: string;
  walletHash: string;
  evidenceBundleHash: string;
  recommendationHash: string;
  walletRiskScoreBps: number;
  privateKeyRequired: boolean;
  walletConfirmationRequired: boolean;
  onchainWriteAttempted: boolean;
  safety?: {
    serverSigned: boolean;
    serverBroadcast: boolean;
    userWalletMustConfirm: boolean;
  };
};

export type CommitVerification = {
  status: "verified" | "pending" | "failed" | "mismatch" | "unknown" | string;
  verificationStatus?: string;
  chainId: number;
  networkName: string;
  contractAddress?: string | null;
  txHash: string;
  explorerUrl?: string | null;
  blockNumber?: number | null;
  eventName?: string | null;
  assessmentHash?: string | null;
  recordId?: string | null;
  mismatchReason?: string | null;
  safeError?: string | null;
  localAssessmentId?: string | null;
  localAssessmentHash?: string | null;
};

export type EnhancementModule = {
  module: string;
  status: string;
  fallbackUsed?: boolean;
  unavailableReason?: string;
  limitations?: string[];
  txRequest?: {
    chainId?: number;
    from?: string;
    to?: string;
    data?: string;
    value?: string;
    method?: string;
    args?: Record<string, unknown>;
  };
  items?: unknown[];
  positions?: unknown[];
  approvalSignals?: unknown[];
  tokenSignals?: unknown[];
  simulationResult?: Record<string, unknown>;
  shareText?: string;
  card?: Record<string, unknown>;
  recordHash?: string;
};

export type EnhancementsResponse = {
  status: string;
  moduleCount: number;
  modules: EnhancementModule[];
  safety: {
    noAutoRevoke: boolean;
    noServerSigning: boolean;
    noTradeOrSwap: boolean;
  };
};

export type AgentIdentity = {
  registration?: {
    agentId?: string;
    chainId?: number;
    networkName?: string;
    safety?: Record<string, unknown>;
    endpoints?: Record<string, string>;
  };
  card?: {
    name?: string;
    schemaVersion?: string;
    chain?: {
      chainId?: number;
      networkName?: string;
    };
    security?: Record<string, unknown>;
    skills?: unknown[];
  };
};
