"""Cloudflare Worker entry — FastAPI (fetch) + daily cleanup cron (scheduled)."""

from __future__ import annotations

from workers import WorkerEntrypoint

from app.factory import create_app
from services.cleanup import purge_old_rows

app = create_app()


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import asgi

        # Pass the JS request object + env bindings into ASGI (scope["env"]).
        return await asgi.fetch(app, request.js_object, self.env)

    async def scheduled(self, controller, env, ctx):
        # Prefer self.env — positional env/ctx may be None on Python Workers.
        await purge_old_rows(self.env)
