from fastapi import FastAPI
from .routers import cluster

app = FastAPI(
    title="K8s Ansible Manager API",
    description="API to manage Kubernetes cluster creation via Ansible",
    version="0.1.0",
)

app.include_router(cluster.router)

@app.get("/")
async def root():
    return {"message": "Welcome to K8s Ansible Manager API"} 