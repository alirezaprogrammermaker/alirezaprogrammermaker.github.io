/**
 * Agents SDK slice exports (w06).
 */

export {
  GatewayAgent,
  GatewaySessionAgent,
  type GatewayAgentState,
} from "./gateway-agent";

export {
  completeViaProvider,
  type ProviderEnv,
  type CompletionResult,
} from "./provider";

export {
  createBuiltinTools,
  toOpenAITools,
  defaultProviders,
  type ToolHost,
} from "./tools";

export type {
  ChatMessage,
  ChatRole,
  GatewayState,
  SessionMeta,
  SessionPreferences,
  ToolCall,
  ToolDefinition,
  OpenAIFunctionTool,
  ProviderInfo,
  WsEnvelope,
  LastToolRunSummary,
} from "./types";

export {
  MAX_SYNCED_MESSAGES,
  MAX_TOOL_ROUNDS,
  DEFAULT_MODEL,
  DEFAULT_PROVIDER_ID,
} from "./types";

export { tryRouteAgent, agentFetchHandler } from "./route";
