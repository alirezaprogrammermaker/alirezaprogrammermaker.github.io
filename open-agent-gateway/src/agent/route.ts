/**
 * Worker integration helpers for Agents SDK routing.
 */

import { routeAgentRequest } from "agents";
import type { Env } from "../env";

export async function tryRouteAgent(
  request: Request,
  env: Env,
): Promise<Response | null> {
  const routed = await routeAgentRequest(request, env);
  return routed ?? null;
}

export async function agentFetchHandler(
  request: Request,
  env: Env,
  next: (request: Request, env: Env) => Promise<Response>,
): Promise<Response> {
  const agentResponse = await tryRouteAgent(request, env);
  if (agentResponse) return agentResponse;
  return next(request, env);
}
