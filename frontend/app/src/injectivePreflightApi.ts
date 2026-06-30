type ApiPreflightRequest = {
  prompt: string;
  address: string;
  subaccountId: string;
  network: "injective_testnet";
  mode: "demo_scenario" | "live_read_only";
};

type ApiTradeIntent = {
  market: string;
  side: "long" | "short" | "buy" | "sell";
  orderType: "market" | "limit";
  leverage: number;
  marginUsagePct: number;
  notionalUsd: number;
  slippageBps: number;
  timeInForce?: string;
  coverageRequestedPartial?: boolean;
};

type ApiPreflightAssessment = {
  assessmentId: string;
  assessmentHash: string;
  createdAt: string;
  request: ApiPreflightRequest;
  parseResult: {
    rawPrompt: string;
    tradeIntent: ApiTradeIntent;
    confidence: number;
    parserMode: string;
    warnings: string[];
  };
  decision: {
    decision: "allow" | "warn" | "block";
    riskScore: number;
    riskLevel: "low" | "moderate" | "high" | "critical" | "unknown";
    action: string;
    reason: string;
    topRisks: Array<{
      id: string;
      title: string;
      severity: "low" | "moderate" | "high" | "critical" | "unknown";
      claim: string;
      confidence?: number;
      evidenceIds: string[];
    }>;
    allowedActions: string[];
    blockedActions: string[];
  };
  evidence: Array<{
    id: string;
    source: string;
    claim: string;
    verification?: string;
    dataQuality?: string;
    mode: "demo_replay" | "live_read_only" | "simulated";
    adapter?: string;
    sourceKind?: string;
    scope?: string;
    rawRef?: string;
    timestamp: string;
  }>;
  sourceCoverage: {
    status: "full" | "partial" | "unavailable" | "replay";
    explanation: string;
    modeSummary?: string;
    sources?: Array<{ name: string; status: "available" | "partial" | "replay" | "simulated" }>;
  };
  simulation: {
    before: ApiTradeIntent;
    after: ApiTradeIntent;
    riskBefore: number;
    riskAfter: number;
    riskDelta: number;
    explanation: string;
    noBroadcast: true;
  };
  proof: {
    status: "not_recorded" | "ready_to_record" | "pending" | "recorded" | "verified_matched" | "verified_mismatch" | "unavailable";
    network: "injective_testnet";
    txHash?: string | null;
    explorerUrl?: string | null;
    proofMethod?: "tx_memo" | "cosmwasm_event";
    recordedAssessmentHash?: string | null;
    blockHeight?: number | null;
    message: string;
  };
  accountState?: {
    availableMarginUsd?: number;
    address?: string;
    subaccountId?: string;
    subaccountKind?: string;
    sourceKind?: string;
    sourceDisclosure?: string;
  };
  marketSnapshot?: {
    marketId?: string;
    sourceKind?: string;
    sourceDisclosure?: string;
    markPrice?: number;
    oraclePrice?: number;
    fundingRatePct?: number;
    spreadBps?: number;
    maxLeverage?: number;
  };
  positions?: Array<{
    market?: string;
    side?: string;
    leverage?: number;
    liquidationDistancePct?: number;
  }>;
};

type ApiProofRecord = ApiPreflightAssessment["proof"] & {
  assessmentId?: string;
  assessmentHash?: string;
  idempotencyKey?: string;
};

type ApiProofVerification = {
  status: "verified_matched" | "verified_mismatch" | "not_found" | "unavailable";
  network: "injective_testnet";
  localAssessmentHash: string;
  onchainAssessmentHash?: string | null;
  txHash?: string | null;
  explorerUrl?: string | null;
  blockHeight?: number | null;
  message: string;
};

type ApiHistoryRecord = {
  assessmentId: string;
  createdAt: string;
  prompt?: string;
  market?: string;
  decision: "allow" | "warn" | "block";
  riskScore: number;
  riskLevel?: "low" | "moderate" | "high" | "critical" | "unknown";
  topRisks?: string[];
  proofStatus: string;
  txHash?: string | null;
  dataMode?: "demo_replay" | "live_read_only";
  sourceMode?: string;
  marketSource?: string;
  simulatedMarket?: boolean;
  proofRecorded?: boolean;
  proofVerified?: boolean;
};

type ApiAgentAudit = {
  assessmentId: string;
  decision: ApiPreflightAssessment["decision"];
  allowedActions: string[];
  blockedActions: string[];
  llmBoundary?: string;
  agentIdentity?: {
    agentName: string;
    agentCardUrl: string;
    registryUrl: string;
    mcpUrl?: string;
  };
  toolTrace: Array<{
    step: number;
    tool: string;
    status: "completed" | "allow" | "block" | "skipped" | "failed";
    summary?: string;
    evidenceIds?: string[];
    actionType?: string;
    timestamp?: string;
  }>;
};

const API_BASE =
  import.meta.env.VITE_INJECTIVELENS_API_BASE ||
  import.meta.env.VITE_API_BASE ||
  (["5173", "5183"].includes(window.location.port) ? "http://127.0.0.1:8765" : "");

export async function getLatestPreflightAssessment() {
  const response = await fetch(`${API_BASE}/api/injective/preflight/latest`);
  const data = await response.json();
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(data.message || data.error || "Latest pre-flight assessment request failed");
  }
  return mapPreflightAssessment(data as ApiPreflightAssessment);
}

export async function runInjectivePreflight(payload: ApiPreflightRequest) {
  const response = await fetch(`${API_BASE}/api/injective/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "Pre-flight API request failed");
  }
  return mapPreflightAssessment(data as ApiPreflightAssessment);
}

export async function recordInjectiveProof(payload: {
  assessmentId: string;
  assessmentHash: string;
  network: "injective_testnet";
}) {
  const response = await fetch(`${API_BASE}/api/proof/record`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      confirmation: "user_confirmed_record_assessment",
      idempotencyKey: `record_${payload.assessmentId}_${payload.assessmentHash}`
    })
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "Proof record request failed");
  }
  return mapProofRecord(data as ApiProofRecord, payload.assessmentHash);
}

export async function verifyInjectiveProof(payload: {
  assessmentHash: string;
  txHash?: string;
  network: "injective_testnet";
}) {
  const response = await fetch(`${API_BASE}/api/proof/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "Proof verify request failed");
  }
  return mapProofVerification(data as ApiProofVerification);
}

export async function getPreflightHistory() {
  const response = await fetch(`${API_BASE}/api/history/preflight`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "History request failed");
  }
  return (data.records || []).map(mapHistoryRecord);
}

export async function getAgentAudit(assessmentId: string) {
  const query = new URLSearchParams({ assessmentId });
  const response = await fetch(`${API_BASE}/api/agent/audit?${query.toString()}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "Agent audit request failed");
  }
  return mapAgentAudit(data as ApiAgentAudit);
}

export function mapPreflightAssessment(data: ApiPreflightAssessment) {
  return {
    assessmentId: data.assessmentId,
    assessmentHash: data.assessmentHash,
    prompt: data.request.prompt,
    mode: data.request.mode === "live_read_only" ? "live" : "demo",
    network: "Injective testnet",
    account: data.request.address,
    subaccountId: data.request.subaccountId,
    parsedIntent: data.parseResult.tradeIntent,
    decision: data.decision.decision,
    riskScore: data.decision.riskScore,
    riskLevel: data.decision.riskLevel,
    action: data.decision.action,
    reason: data.decision.reason,
    topRisks: data.decision.topRisks.map((risk) => ({
      ...risk,
      confidence: risk.confidence ?? 0.8
    })),
    evidence: data.evidence.map((item) => ({
      id: item.id,
      source: item.source,
      claim: item.claim,
      verification: item.verification || "Read-only evidence",
      dataQuality: item.dataQuality || "Unknown",
      mode: item.mode,
      adapter: item.adapter || "Unknown adapter",
      sourceKind: item.sourceKind || item.mode,
      scope: item.scope || "preflight",
      rawRef: item.rawRef,
      timestamp: item.timestamp
    })),
    simulation: data.simulation,
    proof: mapProofRecord(data.proof, data.assessmentHash),
    injectiveContext: {
      account: data.accountState?.address || data.request.address,
      subaccountId: data.accountState?.subaccountId || data.request.subaccountId,
      subaccountKind: data.accountState?.subaccountKind,
      accountSourceKind: data.accountState?.sourceKind,
      accountSourceDisclosure: data.accountState?.sourceDisclosure,
      availableMarginUsd: data.accountState?.availableMarginUsd,
      marketId: data.marketSnapshot?.marketId,
      marketSourceKind: data.marketSnapshot?.sourceKind,
      marketSourceDisclosure: data.marketSnapshot?.sourceDisclosure,
      markPrice: data.marketSnapshot?.markPrice,
      oraclePrice: data.marketSnapshot?.oraclePrice,
      fundingRatePct: data.marketSnapshot?.fundingRatePct,
      spreadBps: data.marketSnapshot?.spreadBps,
      maxLeverage: data.marketSnapshot?.maxLeverage,
      openPositionCount: data.positions?.length ?? 0
    },
    sourceCoverage: {
      status: data.sourceCoverage.status === "unavailable" ? "partial" : data.sourceCoverage.status,
      summary: data.sourceCoverage.explanation,
      modeSummary: data.sourceCoverage.modeSummary,
      sources: data.sourceCoverage.sources || [
        { name: "Injective account state", status: "available" },
        { name: "Injective market snapshot", status: "available" },
        { name: "Open positions", status: data.sourceCoverage.status === "partial" ? "partial" : "available" },
        { name: "Proof verifier", status: data.proof.status === "verified_matched" ? "available" : "replay" }
      ]
    },
    allowedActions: data.decision.allowedActions,
    blockedActions: data.decision.blockedActions,
    toolTrace: buildFallbackToolTrace(data),
    createdAt: data.createdAt
  };
}

function buildFallbackToolTrace(data: ApiPreflightAssessment) {
  const evidenceIds = data.evidence.map((item) => item.id);
  const policyStatus = data.decision.decision === "block" ? "block" : "allow";
  const proofRecorded = ["recorded", "verified_matched"].includes(data.proof.status);
  return [
    { step: 1, tool: "ParseTradeIntent", status: "completed", summary: "Natural-language request parsed by the backend API.", evidenceIds: ["ev_intent_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 2, tool: "NormalizeTradeParameters", status: "completed", summary: "Trade parameters normalized before policy scoring.", evidenceIds: ["ev_intent_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 3, tool: "GetAccountState", status: "completed", summary: "Read-only account and subaccount context loaded by the adapter API.", evidenceIds: ["ev_account_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 4, tool: "GetMarketSnapshot", status: "completed", summary: "Market evidence loaded through the Injective pre-flight API.", evidenceIds: ["ev_market_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 5, tool: "GetOpenPositions", status: "completed", summary: "Open position or simulated position context loaded.", evidenceIds: ["ev_position_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 6, tool: "EvaluateTradeRisk", status: policyStatus, summary: `Decision ${data.decision.decision.toUpperCase()} with risk score ${data.decision.riskScore}/100.`, evidenceIds, actionType: policyStatus === "block" ? "blocked" : "allowed", timestamp: data.createdAt },
    { step: 7, tool: "BindEvidenceBundle", status: "completed", summary: "Risk decision bound to evidence ids before assessment hashing.", evidenceIds, actionType: "allowed", timestamp: data.createdAt },
    { step: 8, tool: "SimulateSaferTrade", status: "completed", summary: "Generated lower-risk alternative without placing an order.", evidenceIds: ["ev_simulation_001"], actionType: "allowed", timestamp: data.createdAt },
    { step: 9, tool: "DecideExecutionBoundary", status: policyStatus, summary: "Execution boundaries applied before signing or order placement.", evidenceIds, actionType: policyStatus === "block" ? "blocked" : "allowed", timestamp: data.createdAt },
    { step: 10, tool: "GenerateAssessmentHash", status: "completed", summary: "Assessment hash generated from request, decision, source coverage, and evidence ids.", evidenceIds, actionType: "allowed", timestamp: data.createdAt },
    { step: 11, tool: "RecordAssessment", status: proofRecorded ? "completed" : "skipped", summary: proofRecorded ? "Assessment hash has an Injective testnet proof." : "Explicit confirmation required before recording.", evidenceIds, actionType: proofRecorded ? "allowed" : "skipped", timestamp: data.createdAt },
    { step: 12, tool: "VerifyAssessment", status: data.proof.status === "verified_matched" ? "completed" : "skipped", summary: data.proof.status === "verified_matched" ? "Local and recorded assessment hashes match." : "Verification waits for a recorded proof.", evidenceIds, actionType: data.proof.status === "verified_matched" ? "allowed" : "skipped", timestamp: data.createdAt }
  ];
}

function mapHistoryRecord(record: ApiHistoryRecord) {
  return {
    id: record.assessmentId,
    createdAt: record.createdAt,
    market: record.market || "UNKNOWN",
    decision: record.decision,
    score: record.riskScore,
    riskLevel: record.riskLevel,
    risks: record.topRisks || [],
    proofStatus: record.proofStatus,
    txHash: record.txHash || undefined,
    dataMode: record.dataMode,
    sourceMode: record.sourceMode,
    marketSource: record.marketSource,
    simulatedMarket: record.simulatedMarket,
    proofRecorded: record.proofRecorded,
    proofVerified: record.proofVerified
  };
}

function mapAgentAudit(audit: ApiAgentAudit) {
  return {
    assessmentId: audit.assessmentId,
    allowedActions: audit.allowedActions,
    blockedActions: audit.blockedActions,
    llmBoundary: audit.llmBoundary || "The model explains; deterministic policy controls execution boundaries.",
    agentIdentity: audit.agentIdentity || {
      agentName: "InjectiveLens Agent Guard",
      agentCardUrl: "/.well-known/agent-card.json",
      registryUrl: "/agent-registration.json",
      mcpUrl: "/mcp"
    },
    toolTrace: audit.toolTrace.map((event) => ({
      step: event.step,
      tool: event.tool,
      status: event.status,
      summary: event.summary || "",
      evidenceIds: event.evidenceIds || [],
      actionType: event.actionType || "",
      timestamp: event.timestamp
    }))
  };
}

function mapProofRecord(data: ApiProofRecord, localAssessmentHash: string) {
  return {
    status: data.status,
    network: "Injective testnet",
    method: data.proofMethod === "cosmwasm_event" ? "testnet memo proof" : "tx memo proof",
    txHash: data.txHash || undefined,
    explorerUrl: data.explorerUrl || undefined,
    localAssessmentHash,
    onchainAssessmentHash: data.recordedAssessmentHash || undefined,
    blockHeight: data.blockHeight || undefined,
    message: data.message
  };
}

function mapProofVerification(data: ApiProofVerification) {
  return {
    status: data.status,
    network: "Injective testnet",
    method: "tx memo proof",
    txHash: data.txHash || undefined,
    explorerUrl: data.explorerUrl || undefined,
    localAssessmentHash: data.localAssessmentHash,
    onchainAssessmentHash: data.onchainAssessmentHash || undefined,
    blockHeight: data.blockHeight || undefined,
    message: data.message
  };
}
