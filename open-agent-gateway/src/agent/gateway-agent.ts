/**
 * GatewayAgent — Cloudflare Agents SDK session agent (w06).
 *
 * Replaces the w01 stub. Durable synced state + SQLite tools/memory.
 * Route: /agents/gateway-agent/:sessionId
 * Provider secrets stay in Env — never in this.state.
 */

import {
  Agent,
  callable,
  type Connection,
  type ConnectionContext,
} from "agents";

import type { Env } from "../env";
import { completeViaProvider } from "./provider";
import {
  createBuiltinTools,
  defaultProviders,
  toOpenAITools,
  type ToolHost,
} from "./tools";
import type {
  ChatMessage,
  GatewayState,
  ProviderInfo,
  ToolDefinition,
  WsEnvelope,
} from "./types";
import {
  DEFAULT_MODEL,
  DEFAULT_PROVIDER_ID,
  MAX_SYNCED_MESSAGES,
  MAX_TOOL_ROUNDS,
} from "./types";

export type GatewayAgentState = GatewayState;

function nowIso(): string {
  return new Date().toISOString();
}

function newId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function envelope<T>(
  type: string,
  ok: boolean,
  payload?: T,
  error?: string,
): string {
  const body: WsEnvelope<T> = { type, ok };
  if (payload !== undefined) body.payload = payload;
  if (error) body.error = error;
  return JSON.stringify(body);
}

function providerKey(env: Env): string | undefined {
  return (
    env.UPSTREAM_API_KEY ||
    env.APMIX_API_KEY ||
    (env as Env & { PROVIDER_API_KEY?: string }).PROVIDER_API_KEY
  );
}

function providerBase(env: Env): string {
  return (
    env.UPSTREAM_BASE_URL ||
    env.APMIX_BASE_URL ||
    "https://api.apmix.ai/v1"
  );
}

export class GatewayAgent extends Agent<Env, GatewayState> {
  initialState: GatewayState = {
    version: 1,
    messages: [],
    sessionMeta: {
      sessionId: "pending",
      createdAt: nowIso(),
      updatedAt: nowIso(),
      model: DEFAULT_MODEL,
      providerId: DEFAULT_PROVIDER_ID,
      messageCount: 0,
    },
    preferences: {
      temperature: 0.4,
      maxTokens: 1024,
      systemPrompt:
        "You are the Open Agent Gateway session assistant. Use tools for memory, history, preferences, and scheduling. Never request or reveal API keys.",
      locale: "en",
    },
    lastToolRun: null,
  };

  private tools = new Map<string, ToolDefinition>();

  async onStart(): Promise<void> {
    this.sql`
      CREATE TABLE IF NOT EXISTS memories (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `;
    this.sql`
      CREATE TABLE IF NOT EXISTS tool_runs (
        id TEXT PRIMARY KEY,
        tool_name TEXT NOT NULL,
        arguments_json TEXT,
        result_json TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    `;
    this.sql`
      CREATE TABLE IF NOT EXISTS message_archive (
        id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        content TEXT,
        created_at TEXT NOT NULL
      )
    `;

    if (this.state.sessionMeta.sessionId === "pending") {
      this.setState({
        ...this.state,
        sessionMeta: {
          ...this.state.sessionMeta,
          sessionId: this.name || newId("sess"),
          model: this.env.GATEWAY_DEFAULT_MODEL || DEFAULT_MODEL,
          updatedAt: nowIso(),
        },
      });
    }

    this.registerBuiltinTools();
  }

  private registerBuiltinTools(): void {
    this.tools.clear();
    const host = this.createToolHost();
    for (const def of createBuiltinTools(host)) {
      this.tools.set(def.name, def);
    }
  }

  private createToolHost(): ToolHost {
    const agent = this;
    return {
      sessionId: agent.state.sessionMeta.sessionId,
      getPreference: (key) => agent.state.preferences[key],
      setPreference: (key, value) => {
        agent.setState({
          ...agent.state,
          preferences: { ...agent.state.preferences, [key]: value },
          sessionMeta: { ...agent.state.sessionMeta, updatedAt: nowIso() },
        });
      },
      memorySet: (key, value) => {
        agent.sql`
          INSERT INTO memories (key, value, updated_at)
          VALUES (${key}, ${value}, ${nowIso()})
          ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        `;
      },
      memoryGet: (key) => {
        const rows = agent.sql<{ value: string }>`
          SELECT value FROM memories WHERE key = ${key} LIMIT 1
        `;
        return rows.length ? rows[0].value : null;
      },
      searchHistory: (query, limit) => {
        const q = query.toLowerCase();
        const fromState = agent.state.messages
          .filter((m) => (m.content || "").toLowerCase().includes(q))
          .slice(-limit)
          .map((m) => ({ role: m.role, content: m.content || "" }));

        if (fromState.length > 0) return fromState;

        const like = `%${query}%`;
        const rows = agent.sql<{ role: string; content: string }>`
          SELECT role, content FROM message_archive
          WHERE content LIKE ${like}
          ORDER BY created_at DESC
          LIMIT ${limit}
        `;
        return rows.map((r) => ({ role: r.role, content: r.content || "" }));
      },
      clearHistory: () => {
        agent.sql`DELETE FROM tool_runs`;
        agent.sql`DELETE FROM message_archive`;
        agent.setState({
          ...agent.state,
          messages: [],
          lastToolRun: null,
          sessionMeta: {
            ...agent.state.sessionMeta,
            messageCount: 0,
            updatedAt: nowIso(),
          },
        });
        agent.broadcast(envelope("history_cleared", true, { at: nowIso() }));
      },
      listProviders: () => agent.resolveProviders(),
      schedulePing: async (delaySeconds, message) => {
        const { id } = await agent.schedule(delaySeconds, "onScheduledPing", {
          message,
        });
        return String(id);
      },
      nowIso,
    };
  }

  private resolveProviders(): ProviderInfo[] {
    const catalog = (this.env as Env & { PROVIDER_CATALOG?: string })
      .PROVIDER_CATALOG;
    if (catalog) {
      try {
        const parsed = JSON.parse(catalog) as ProviderInfo[];
        if (Array.isArray(parsed) && parsed.length) return parsed;
      } catch {
        /* fall through */
      }
    }
    return defaultProviders(providerBase(this.env));
  }

  validateStateChange(
    nextState: GatewayState,
    _source: Connection | "server",
  ): void {
    if (!nextState || typeof nextState !== "object") {
      throw new Error("Invalid state");
    }
    if (!Array.isArray(nextState.messages)) {
      throw new Error("messages must be an array");
    }
    if (nextState.messages.length > MAX_SYNCED_MESSAGES) {
      throw new Error(
        `messages exceeds max ${MAX_SYNCED_MESSAGES}; use clear_history or archive`,
      );
    }
    for (const m of nextState.messages) {
      if (m.content && m.content.length > 32_000) {
        throw new Error("message content too large");
      }
    }
  }

  onStateUpdate(state: GatewayState, source: Connection | "server"): void {
    if (
      source !== "server" &&
      state.sessionMeta.messageCount !== state.messages.length
    ) {
      this.setState({
        ...state,
        sessionMeta: {
          ...state.sessionMeta,
          messageCount: state.messages.length,
          updatedAt: nowIso(),
        },
      });
    }
  }

  async onConnect(
    connection: Connection,
    _ctx: ConnectionContext,
  ): Promise<void> {
    connection.send(
      envelope("welcome", true, {
        service: "open-agent-gateway",
        sessionId: this.state.sessionMeta.sessionId,
        history: this.state.messages,
        preferences: this.state.preferences,
        tools: [...this.tools.keys()],
      }),
    );
  }

  async onMessage(
    connection: Connection,
    message: string | ArrayBuffer,
  ): Promise<void> {
    try {
      const text =
        typeof message === "string"
          ? message
          : new TextDecoder().decode(message);
      const data = JSON.parse(text) as {
        type?: string;
        content?: string;
        name?: string;
        arguments?: Record<string, unknown>;
      };

      switch (data.type) {
        case "ping":
          connection.send(envelope("pong", true, { at: nowIso() }));
          return;
        case "get_state":
          connection.send(
            envelope("state", true, {
              state: this.state,
              tools: [...this.tools.keys()],
            }),
          );
          return;
        case "chat": {
          if (!data.content?.trim()) {
            connection.send(
              envelope("error", false, undefined, "content required"),
            );
            return;
          }
          const reply = await this.handleChatWithTools(data.content.trim());
          connection.send(
            envelope("response", true, {
              content: reply.content,
              toolRuns: reply.toolNames,
              model: reply.model,
            }),
          );
          return;
        }
        case "tool": {
          if (!data.name) {
            connection.send(
              envelope("error", false, undefined, "tool name required"),
            );
            return;
          }
          const result = await this.executeTool(
            data.name,
            data.arguments || {},
          );
          connection.send(
            envelope("tool_result", true, {
              name: data.name,
              result,
            }),
          );
          return;
        }
        default:
          connection.send(
            envelope(
              "error",
              false,
              undefined,
              `unknown type: ${data.type ?? "undefined"}`,
            ),
          );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      connection.send(envelope("error", false, undefined, msg));
    }
  }

  async onRequest(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (request.method === "GET" && path.endsWith("/state")) {
      return Response.json({
        ok: true,
        state: this.state,
        tools: [...this.tools.keys()],
      });
    }

    if (request.method === "GET" && path.endsWith("/tools")) {
      return Response.json({ ok: true, tools: this.listToolDefs() });
    }

    if (request.method === "POST" && path.endsWith("/chat")) {
      try {
        const body = (await request.json()) as { content?: string };
        if (!body.content?.trim()) {
          return Response.json(
            { ok: false, error: "content required" },
            { status: 400 },
          );
        }
        const reply = await this.handleChatWithTools(body.content.trim());
        return Response.json({ ok: true, ...reply });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return Response.json({ ok: false, error: msg }, { status: 500 });
      }
    }

    return Response.json({
      ok: true,
      agent: "GatewayAgent",
      sessionId: this.state.sessionMeta.sessionId,
      endpoints: ["GET /state", "GET /tools", "POST /chat"],
    });
  }

  async onScheduledPing(payload: { message: string }): Promise<void> {
    this.broadcast(
      envelope("scheduled_ping", true, {
        message: payload.message,
        at: nowIso(),
      }),
    );
  }

  @callable()
  async chat(content: string): Promise<{
    content: string | null;
    toolNames: string[];
    model: string;
  }> {
    if (!content?.trim()) throw new Error("content required");
    return this.handleChatWithTools(content.trim());
  }

  @callable()
  getHistory(): ChatMessage[] {
    return this.state.messages;
  }

  @callable()
  clearHistory(): { ok: true } {
    this.createToolHost().clearHistory();
    return { ok: true };
  }

  @callable()
  listTools(): Array<{ name: string; description: string }> {
    return this.listToolDefs();
  }

  @callable()
  async runTool(
    name: string,
    args: Record<string, unknown> = {},
  ): Promise<string> {
    return this.executeTool(name, args);
  }

  @callable()
  getStateSnapshot(): GatewayState {
    return this.state;
  }

  @callable()
  setPreference(
    key: string,
    value: string,
  ): { preferences: GatewayState["preferences"] } {
    this.createToolHost().setPreference(key, value);
    return { preferences: this.state.preferences };
  }

  @callable()
  async listSchedules(): Promise<unknown[]> {
    return this.getSchedules();
  }

  private listToolDefs(): Array<{ name: string; description: string }> {
    return [...this.tools.values()].map((t) => ({
      name: t.name,
      description: t.description,
    }));
  }

  async executeTool(
    name: string,
    params: Record<string, unknown>,
  ): Promise<string> {
    this.registerBuiltinTools();
    const tool = this.tools.get(name);
    if (!tool) throw new Error(`Unknown tool: ${name}`);

    const runId = newId("run");
    const started = nowIso();
    this.sql`
      INSERT INTO tool_runs (id, tool_name, arguments_json, result_json, status, created_at)
      VALUES (
        ${runId},
        ${name},
        ${JSON.stringify(params)},
        ${null},
        ${"running"},
        ${started}
      )
    `;

    try {
      const result = await tool.handler(params, {
        agentName: "GatewayAgent",
        sessionId: this.state.sessionMeta.sessionId,
      });
      const text = typeof result === "string" ? result : JSON.stringify(result);
      this.sql`
        UPDATE tool_runs
        SET result_json = ${text}, status = ${"completed"}
        WHERE id = ${runId}
      `;
      this.setState({
        ...this.state,
        lastToolRun: {
          id: runId,
          name,
          status: "completed",
          at: nowIso(),
        },
        sessionMeta: { ...this.state.sessionMeta, updatedAt: nowIso() },
      });
      return text;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.sql`
        UPDATE tool_runs
        SET result_json = ${msg}, status = ${"failed"}
        WHERE id = ${runId}
      `;
      this.setState({
        ...this.state,
        lastToolRun: {
          id: runId,
          name,
          status: "failed",
          at: nowIso(),
        },
      });
      throw err;
    }
  }

  private appendMessage(message: ChatMessage): void {
    const id = message.id || newId("msg");
    const createdAt = message.createdAt || nowIso();
    const next: ChatMessage = { ...message, id, createdAt };

    this.sql`
      INSERT INTO message_archive (id, role, content, created_at)
      VALUES (${id}, ${next.role}, ${next.content ?? ""}, ${createdAt})
    `;

    let messages = [...this.state.messages, next];
    if (messages.length > MAX_SYNCED_MESSAGES) {
      messages = messages.slice(-MAX_SYNCED_MESSAGES);
    }

    this.setState({
      ...this.state,
      messages,
      sessionMeta: {
        ...this.state.sessionMeta,
        messageCount: messages.length,
        updatedAt: nowIso(),
      },
    });
  }

  private async handleChatWithTools(userMessage: string): Promise<{
    content: string | null;
    toolNames: string[];
    model: string;
  }> {
    this.registerBuiltinTools();
    this.appendMessage({ role: "user", content: userMessage });

    const systemPrompt =
      (this.state.preferences.systemPrompt as string | undefined) ||
      (this.initialState.preferences.systemPrompt as string) ||
      "";

    const openaiTools = toOpenAITools([...this.tools.values()]);
    const toolNamesUsed: string[] = [];
    let model: string = this.env.GATEWAY_DEFAULT_MODEL || DEFAULT_MODEL;
    let finalContent: string | null = null;

    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      const messages: ChatMessage[] = [
        { role: "system", content: systemPrompt },
        ...this.state.messages,
      ];

      const completion = await completeViaProvider(
        {
          APMIX_BASE_URL: providerBase(this.env),
          PROVIDER_API_KEY: providerKey(this.env),
          DEFAULT_MODEL: this.env.GATEWAY_DEFAULT_MODEL || DEFAULT_MODEL,
        },
        messages,
        openaiTools,
        {
          model: this.state.sessionMeta.model || model,
          temperature: Number(this.state.preferences.temperature ?? 0.4),
          maxTokens: Number(this.state.preferences.maxTokens ?? 1024),
        },
      );

      model = completion.model;

      if (completion.tool_calls?.length) {
        this.appendMessage({
          role: "assistant",
          content: completion.content,
          tool_calls: completion.tool_calls,
        });

        for (const call of completion.tool_calls) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(call.function.arguments || "{}") as Record<
              string,
              unknown
            >;
          } catch {
            args = {};
          }
          toolNamesUsed.push(call.function.name);
          let result: string;
          try {
            result = await this.executeTool(call.function.name, args);
          } catch (err) {
            result = JSON.stringify({
              ok: false,
              error: err instanceof Error ? err.message : String(err),
            });
          }
          this.appendMessage({
            role: "tool",
            content: result,
            tool_call_id: call.id,
            name: call.function.name,
          });
        }
        continue;
      }

      finalContent = completion.content;
      this.appendMessage({ role: "assistant", content: finalContent });
      break;
    }

    if (finalContent === null && toolNamesUsed.length) {
      finalContent = `Completed tools: ${toolNamesUsed.join(", ")}`;
      this.appendMessage({ role: "assistant", content: finalContent });
    }

    return { content: finalContent, toolNames: toolNamesUsed, model };
  }
}

/** Alias kept for fanout / docs that used GatewaySessionAgent. */
export { GatewayAgent as GatewaySessionAgent };
