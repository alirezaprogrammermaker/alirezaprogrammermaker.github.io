/**
 * // SLOT w06 — Agents SDK agent class, tools, durable state
 */

import { Agent, type Connection } from "agents";
import type { Env } from "../env";

export interface GatewayAgentState {
  messages: Array<{ role: string; content: string }>;
  updatedAt: string | null;
}

/**
 * Stateful chat agent (WebSocket /agents/gateway-agent/:name).
 * // SLOT w06: wire tools, provider complete(), scheduling, SQL history
 */
export class GatewayAgent extends Agent<Env, GatewayAgentState> {
  initialState: GatewayAgentState = {
    messages: [],
    updatedAt: null,
  };

  async onConnect(connection: Connection) {
    connection.send(
      JSON.stringify({
        type: "welcome",
        service: "open-agent-gateway",
        // SLOT w06: include fuller history / identity
        history: this.state.messages,
      }),
    );
  }

  async onMessage(connection: Connection, message: string | ArrayBuffer) {
    if (typeof message !== "string") {
      connection.send(JSON.stringify({ type: "error", message: "Expected text" }));
      return;
    }

    let data: { type?: string; content?: string };
    try {
      data = JSON.parse(message) as { type?: string; content?: string };
    } catch {
      connection.send(JSON.stringify({ type: "error", message: "Invalid JSON" }));
      return;
    }

    if (data.type === "chat" && data.content) {
      // SLOT w06: call resolveDefaultProvider(this.env).complete(...)
      const messages = [
        ...this.state.messages,
        { role: "user", content: data.content },
        {
          role: "assistant",
          content:
            "SLOT w06: agent chat not wired to providers yet. Use POST /v1/chat/completions.",
        },
      ];
      this.setState({
        messages,
        updatedAt: new Date().toISOString(),
      });
      connection.send(
        JSON.stringify({
          type: "response",
          content: messages[messages.length - 1].content,
        }),
      );
      return;
    }

    connection.send(
      JSON.stringify({
        type: "error",
        message: "Unknown message type. Send {type:'chat', content:'...'}",
      }),
    );
  }
}
