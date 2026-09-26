# GatewayAgent (w06)

Stateful Cloudflare **Agents SDK** agent for `open-agent-gateway/`.

## Routes

| Kind | Path |
|------|------|
| WebSocket / RPC | `/agents/gateway-agent/:sessionId` |
| HTTP state | `GET .../state` |
| HTTP tools | `GET .../tools` |
| HTTP chat | `POST .../chat` `{ "content": "..." }` |

## Callable RPC

`chat`, `getHistory`, `clearHistory`, `listTools`, `runTool`, `getStateSnapshot`, `setPreference`, `listSchedules`

## Built-in tools

`echo`, `memory_set`, `memory_get`, `list_providers`, `schedule_ping`, `search_history`, `clear_history`, `set_preference`

## Durable state

- **Synced (`setState`)**: messages (max 100), preferences, sessionMeta, lastToolRun
- **SQLite**: `memories`, `tool_runs`, `message_archive`
- Provider keys: Env secrets only (`APMIX_API_KEY` / `UPSTREAM_API_KEY`)

## Wrangler

Uses existing `GatewayAgent` DO binding + `new_sqlite_classes` from w01 scaffold.

## Integration

`routeAgentRequest` runs first in `src/index.ts`; `/v1/chat/completions` remains the stateless HTTP gateway (w05).
