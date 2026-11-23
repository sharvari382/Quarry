/**
 * Thin fetch wrapper.
 * - Cookies carry the session (HttpOnly), so no token ever touches JS or localStorage.
 * - State-changing requests echo the CSRF cookie in a header (double-submit).
 * - A 401 triggers one silent refresh, then the original request is retried.
 */
import type { Conversation, ConversationDetail, Dataset, StreamEvent, User } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)quarry_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

let refreshing: Promise<boolean> | null = null;
let onSessionLost: () => void = () => {};
export function setSessionLostHandler(fn: () => void) {
  onSessionLost = fn;
}

async function refreshSession(): Promise<boolean> {
  // Collapse concurrent 401s into a single refresh call.
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
    headers: { "x-csrf-token": csrfToken() },
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      setTimeout(() => (refreshing = null), 0);
    });
  return refreshing;
}

async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET") headers.set("x-csrf-token", csrfToken());
  if (init.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });

  const isAuthCall = path.startsWith("/api/auth/login") || path.startsWith("/api/auth/register");
  if (res.status === 401 && retry && !isAuthCall && path !== "/api/auth/refresh") {
    if (await refreshSession()) return raw(path, init, false);
    onSessionLost();
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 429) {
      const after = res.headers.get("retry-after");
      if (after && !detail.includes("Try again")) detail += ` Try again in ${after}s.`;
    }
    throw new ApiError(res.status, detail);
  }
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  me: () => json<User>("/api/auth/me"),
  login: (email: string, password: string) =>
    json<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (email: string, full_name: string, password: string) =>
    json<User>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, full_name, password }) }),
  logout: () => json<void>("/api/auth/logout", { method: "POST" }),
  logoutAll: () => json<void>("/api/auth/logout-all", { method: "POST" }),

  datasets: () => json<Dataset[]>("/api/datasets"),
  upload: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return json<{ datasets: Dataset[]; errors: string[] }>("/api/datasets", { method: "POST", body: form });
  },
  preview: (id: string) =>
    json<{ columns: string[]; rows: unknown[][]; row_count: number }>(`/api/datasets/${id}/preview?limit=25`),
  deleteDataset: (id: string) => json<void>(`/api/datasets/${id}`, { method: "DELETE" }),

  conversations: () => json<Conversation[]>("/api/conversations"),
  conversation: (id: string) => json<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (dataset_ids: string[]) =>
    json<Conversation>("/api/conversations", { method: "POST", body: JSON.stringify({ dataset_ids }) }),
  updateConversation: (id: string, patch: { title?: string; dataset_ids?: string[] }) =>
    json<Conversation>(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteConversation: (id: string) => json<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  async exportReport(id: string, title: string) {
    const res = await raw(`/api/conversations/${id}/export.md`);
    downloadBlob(await res.blob(), `${slug(title)}.md`);
  },

  async exportCsv(sql: string, dataset_ids: string[], name: string) {
    const res = await raw("/api/datasets/query.csv", { method: "POST", body: JSON.stringify({ sql, dataset_ids }) });
    downloadBlob(await res.blob(), `${slug(name)}.csv`);
  },

  /** POST a question and yield Server-Sent Events as they arrive. */
  async *ask(conversationId: string, question: string, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    const res = await raw(`/api/conversations/${conversationId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
      signal,
    });
    const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const data = block
          .split("\n")
          .filter((l) => l.startsWith("data: "))
          .map((l) => l.slice(6))
          .join("\n");
        if (data) yield JSON.parse(data) as StreamEvent;
      }
    }
  },
};

export function parseSseBlocks(text: string): StreamEvent[] {
  return text
    .split("\n\n")
    .map((b) => b.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n"))
    .filter(Boolean)
    .map((d) => JSON.parse(d));
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "quarry";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
