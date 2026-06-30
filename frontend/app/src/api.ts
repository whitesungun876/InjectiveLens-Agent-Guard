import type {
  AgentIdentity,
  AlertItem,
  CommitCalldataResponse,
  CommitVerification,
  CommitResponse,
  EnhancementsResponse,
  ProviderStatus,
  ScanRequest,
  ScanResponse,
  SimulationResponse,
  WalletHistoryResponse
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE ||
  (window.location.port === "5173" ? "http://127.0.0.1:8765" : "");

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "Request failed");
  }
  return data as T;
}

export function getHealth(): Promise<{ status: string; mode: string; day: string }> {
  return jsonRequest("/api/health");
}

export function getProviderStatus(): Promise<ProviderStatus> {
  return jsonRequest("/api/provider/status");
}

export async function getAgentIdentity(): Promise<AgentIdentity> {
  const [registration, card] = await Promise.all([
    jsonRequest<AgentIdentity["registration"]>("/agent-registration.json"),
    jsonRequest<AgentIdentity["card"]>("/.well-known/agent-card.json")
  ]);
  return { registration, card };
}

export function scanWallet(payload: ScanRequest): Promise<ScanResponse> {
  return jsonRequest("/api/wallet/scan", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function simulateApproval(assessment: ScanResponse["assessment"]): Promise<SimulationResponse> {
  return jsonRequest("/api/simulation/approval", {
    method: "POST",
    body: JSON.stringify({
      assessment,
      actionId: "act_simulate_revoke_approval"
    })
  });
}

export function simulatePortfolio(assessment: ScanResponse["assessment"]): Promise<SimulationResponse> {
  return jsonRequest("/api/simulation/portfolio", {
    method: "POST",
    body: JSON.stringify({
      assessment,
      actionId: "act_simulate_portfolio_adjustment"
    })
  });
}

export function commitAssessment(
  assessment: ScanResponse["assessment"],
  simulation?: SimulationResponse["simulation"] | null,
  recordMode: "local_only" | "onchain" = "local_only"
): Promise<CommitResponse> {
  return jsonRequest("/api/assessment/commit", {
    method: "POST",
    body: JSON.stringify({
      assessment,
      simulation,
      recordMode,
      confirmationReceived: true,
      idempotencyKey: `idem_${recordMode}_${assessment.assessmentId}_${assessment.assessmentHash}`
    })
  });
}

export function prepareAssessmentCommitCalldata(
  assessment: ScanResponse["assessment"]
): Promise<CommitCalldataResponse> {
  return jsonRequest("/api/assessment/commit/calldata", {
    method: "POST",
    body: JSON.stringify({ assessment })
  });
}

export function verifyAssessmentCommit(
  txHash: string,
  assessmentId?: string,
  assessmentHash?: string
): Promise<CommitVerification> {
  const query = new URLSearchParams({ tx_hash: txHash });
  if (assessmentId) query.set("assessment_id", assessmentId);
  if (assessmentHash) query.set("assessment_hash", assessmentHash);
  return jsonRequest(`/api/assessment/commit/verify?${query.toString()}`);
}

export function runEnhancements(data: ScanResponse): Promise<EnhancementsResponse> {
  return jsonRequest("/api/enhancements", {
    method: "POST",
    body: JSON.stringify({
      assessment: data.assessment,
      evidence: data.evidenceBundle.evidence,
      coverage: data.coverage,
      toolOutputs: data.toolOutputs,
      inventory: data.inventory,
      history: data.history
    })
  });
}

export function getWalletHistory(params: {
  walletHash?: string;
  address?: string;
  chainId?: number;
  mode?: string;
  limit?: number;
}): Promise<WalletHistoryResponse> {
  const query = new URLSearchParams();
  if (params.walletHash) query.set("walletHash", params.walletHash);
  if (params.address) query.set("address", params.address);
  if (params.chainId) query.set("chain_id", String(params.chainId));
  if (params.mode) query.set("mode", params.mode);
  query.set("limit", String(params.limit || 20));
  return jsonRequest(`/api/wallet/history?${query.toString()}`);
}

export function getAlerts(params: {
  walletHash?: string;
  address?: string;
  chainId?: number;
  mode?: string;
  status?: "open" | "resolved" | "all";
} = {}): Promise<{ alerts: AlertItem[] }> {
  const status = params.status || "open";
  const query = new URLSearchParams({ status });
  if (params.walletHash) query.set("walletHash", params.walletHash);
  if (params.address) query.set("address", params.address);
  if (params.chainId) query.set("chain_id", String(params.chainId));
  if (params.mode) query.set("mode", params.mode);
  return jsonRequest(`/api/alerts?${query.toString()}`);
}

export function resolveAlert(alertId: string): Promise<{ alert: AlertItem }> {
  return jsonRequest(`/api/alerts/${encodeURIComponent(alertId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({
      alertId,
      resolutionNote: "Resolved in MantleLens app"
    })
  });
}
