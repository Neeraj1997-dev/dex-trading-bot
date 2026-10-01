import type { ChatMessage, DashboardSnapshot, RiskLimits } from "../types";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8080/api/v1";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("dex_token");
  return token
    ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  });
  if (res.status === 401) {
    localStorage.removeItem("dex_token");
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async login(email: string, password: string) {
    const data = await request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    localStorage.setItem("dex_token", data.access_token);
    return data;
  },
  logout() {
    localStorage.removeItem("dex_token");
  },
  isAuthed() {
    return Boolean(localStorage.getItem("dex_token"));
  },
  dashboard: () => request<DashboardSnapshot>("/dashboard"),
  control: (action: string) =>
    request("/bot/control", { method: "POST", body: JSON.stringify({ action }) }),
  setMode: (mode: string) =>
    request("/bot/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
  updateRisk: (limits: RiskLimits) =>
    request("/bot/risk", { method: "PUT", body: JSON.stringify({ limits }) }),
  togglePair: (symbol: string, enabled: boolean) =>
    request("/bot/pairs", {
      method: "PUT",
      body: JSON.stringify({ symbol, enabled }),
    }),
  runCycle: () => request("/bot/cycle", { method: "POST" }),
  chatHistory: () => request<{ messages: ChatMessage[] }>("/chat"),
  chatSend: (message: string) =>
    request<{ messages: ChatMessage[] }>("/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  approveSignal: (id: string, approve: boolean) =>
    request(`/signals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    }),
  whatsappStatus: () =>
    request<{
      enabled: boolean;
      provider: string;
      to: string;
      configured: boolean;
    }>("/notifications/whatsapp"),
  whatsappTest: () =>
    request<{ success: boolean; to: string }>("/notifications/whatsapp/test", {
      method: "POST",
    }),
};
