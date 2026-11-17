import os

from fastapi import FastAPI

service_name = os.getenv("SERVICE_NAME", "cleaning-agent")
app = FastAPI(title=f"DCIC-Flix26 {service_name}")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": service_name}
