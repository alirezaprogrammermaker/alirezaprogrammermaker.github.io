export function handleHealth(): Response {
  return Response.json({
    ok: true,
    service: "open-agent-gateway",
    version: "0.1.0",
  });
}
