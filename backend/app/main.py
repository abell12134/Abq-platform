from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agents,
    analyze,
    compose,
    factors,
    graph,
    health,
    knowledge,
    llm,
    memory,
    paths,
    portfolios,
    prompts,
    quotes,
    tools,
)
from app.graph.maintenance import maybe_run_startup_maintenance
from app.graph.store import graph_store
from app.config import settings
from app.factors.store import factor_store
from app.memory.store import memory_store
from app.persistence.library_store import library_store
from app.persistence.paths import path_store
from app.persistence.portfolio_store import portfolio_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await path_store.ensure()
    library_store.ensure()
    factor_store.ensure()
    portfolio_store.ensure()
    memory_store.ensure()
    if settings.graph_enabled:
        graph_store.ensure()
        await maybe_run_startup_maintenance()
    yield


app = FastAPI(title="ABQ Lab API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(paths.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(prompts.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(factors.router, prefix="/api")
app.include_router(portfolios.router, prefix="/api")
app.include_router(compose.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
app.include_router(quotes.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(memory.router, prefix="/api")


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
