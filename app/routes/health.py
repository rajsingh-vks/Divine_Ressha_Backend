from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", summary="API health check")
async def api_health():
    return {"status": "ok"}


@router.get("/db", summary="MongoDB connectivity check")
async def database_health(request: Request):
    try:
        result = await request.app.state.mongo_db.command("ping")
        db_name = request.app.state.mongo_db.name
        stats = await request.app.state.mongo_db.command("dbStats")
        return {
            "status": "ok",
            "database": "connected",
            "db_name": db_name,
            "ping": result.get("ok"),
            "collections": stats.get("collections", 0),
            "objects": stats.get("objects", 0),
            "storage_size_bytes": stats.get("storageSize", 0),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "disconnected",
                "detail": str(exc),
            },
        )
