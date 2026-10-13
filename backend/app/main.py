from fastapi import FastAPI

from app.api import accounts, attachments, auth, brief, messages, replies, rules, status
from app.config import settings

# A documentação da API é um mapa pronto do sistema para quem o estuda.
# Fica fechada por padrão; DOCS_ENABLED=true liga durante a depuração.
app = FastAPI(
    title="BR BOSS",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(messages.router)
app.include_router(rules.router)
app.include_router(replies.router)
app.include_router(attachments.router)
app.include_router(brief.router)
app.include_router(status.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
