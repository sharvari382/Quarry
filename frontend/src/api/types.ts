export interface User {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

export interface ColumnInfo {
  name: string;
  original_name: string;
  type: "integer" | "number" | "text" | "datetime" | "boolean";
  nulls: number;
  distinct: number;
  min?: number | string;
  max?: number | string;
  mean?: number;
  examples?: string[];
}

export interface QualityIssue {
  severity: "info" | "warning";
  column: string | null;
  issue: string;
}

export interface Dataset {
  id: string;
  original_filename: string;
  table_name: string;
  row_count: number;
  column_count: number;
  size_bytes: number;
  columns: ColumnInfo[];
  quality: { score: number; issues: QualityIssue[]; duplicate_rows: number; skipped_rows: number };
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  dataset_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface Step {
  id: string;
  tool: string;
  label: string;
  input: Record<string, unknown>;
  ok?: boolean;
  elapsed_ms?: number;
  error?: string;
}

export interface TableArtifact {
  type: "table";
  id: string;
  title: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface ChartArtifact {
  type: "chart";
  id: string;
  chart_type: "bar" | "horizontal_bar" | "line" | "area" | "pie" | "scatter" | "stacked_bar";
  title: string;
  x: string;
  y: string[];
  y_label?: string | null;
  data: Record<string, unknown>[];
  sql: string;
  band?: [string, string];
  note?: string;
}

export interface Flagged {
  row: number;
  value: number;
  score: number;
  direction: "above" | "below";
  reason: string;
  group: string | null;
  labels: Record<string, string | null>;
}

export interface AnomalyArtifact {
  type: "anomalies";
  id: string;
  value_column: string;
  method: string;
  n_values: number;
  n_flagged: number;
  summary: string;
  flagged: Flagged[];
  sql: string;
}

export interface ProfileArtifact {
  type: "profile";
  id: string;
  table: string;
  rows: number;
  columns: { column: string; dtype: string; nulls: number; distinct: number; [k: string]: unknown }[];
}

export type Artifact = TableArtifact | ChartArtifact | AnomalyArtifact | ProfileArtifact;

export interface AnswerPayload {
  answer: string;
  reasoning: string[];
  sql: string | null;
  pandas_code: string | null;
  follow_ups: string[];
  cached?: boolean;
}

export interface MessageArtifacts {
  steps?: Step[];
  items?: Artifact[];
  sql?: string[];
  reasoning?: string[];
  pandas_code?: string | null;
  final_sql?: string;
  follow_ups?: string[];
  failed?: boolean;
  cached?: boolean;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  artifacts: MessageArtifacts;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export type StreamEvent =
  | ({ type: "step" } & Step)
  | ({ type: "step_end" } & Step)
  | { type: "artifact"; artifact: Artifact }
  | ({ type: "answer" } & AnswerPayload)
  | { type: "error"; message: string }
  | { type: "done"; message_id: string };
