import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Response, Body
from typing import List
from ..models.cluster import ClusterCreateRequest, ClusterCreateResponse, ClusterInfo, NodeInfo
from ..services import ansible_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/clusters",
    tags=["clusters"],
)

# In-memory storage for cluster status (replace with DB/file later)
cluster_status_db = {}

def adapt_status_to_cluster_info(status_info: dict) -> ClusterInfo:
    """Helper to convert stored status dict to ClusterInfo model."""
    # Ensure IPs are converted back if needed, though status endpoint does this
    return ClusterInfo(
        id=status_info.get("id", "unknown"),
        name=status_info.get("name", "unknown"),
        status=status_info.get("status", "unknown"),
        vip=str(status_info.get("vip", "0.0.0.0")), # Ensure string conversion
        master_ips=[str(node.get('ip', 'unknown')) for node in status_info.get("master_nodes_info", [])],
        worker_ips=[str(node.get('ip', 'unknown')) for node in status_info.get("worker_nodes_info", [])],
        # Add message or error info if desired in the response
        # message=status_info.get("message"),
        # last_error=status_info.get("last_error")
    )

@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=ClusterCreateResponse)
async def create_cluster(cluster_request: ClusterCreateRequest, background_tasks: BackgroundTasks):
    """
    Receives cluster configuration and triggers Ansible playbook execution
    in the background to create a new Kubernetes cluster.
    """
    cluster_id = str(uuid.uuid4())
    cluster_name = cluster_request.cluster_name

    # Convert Pydantic models to dict for inventory context
    # The validator in the model should have applied default_ssh_port already
    inventory_input_data = {
        "bastion_ip": str(cluster_request.bastion_ip),
        "bastion_port": cluster_request.bastion_port, # Include bastion port
        "master_nodes_info": [node.dict() for node in cluster_request.master_nodes],
        "worker_nodes_info": [node.dict() for node in cluster_request.worker_nodes],
        "ansible_user": cluster_request.ansible_user,
        "vip": cluster_request.vip_address,
        "cluster_name": cluster_name,
        "pcs_hacluster_password_secret": cluster_request.pcs_hacluster_password.get_secret_value(),
        "vip_interface_from_req": cluster_request.vip_interface,
        # Store default port if provided, might be useful for context
        "default_ssh_port_from_req": cluster_request.default_ssh_port 
    }
    # Ensure IPs are strings (service will handle port conversion/validation)
    for node_list_key in ["master_nodes_info", "worker_nodes_info"]:
        for node in inventory_input_data[node_list_key]:
            node['ip'] = str(node['ip'])
            # Port will be handled by the service/inventory generation logic

    # Prepare extra_vars (pass only what Ansible needs directly)
    extra_vars = {
        "cluster_name": cluster_name,
        "vip_address": str(cluster_request.vip_address),
        "pcs_hacluster_password": cluster_request.pcs_hacluster_password.get_secret_value(),
    }
    if cluster_request.vip_interface:
        extra_vars["vip_interface"] = cluster_request.vip_interface
    # Note: Ports are handled via inventory, not typically needed in extra_vars for these roles

    # Store initial status (including data needed for inventory gen later)
    cluster_status_db[cluster_id] = {
        "id": cluster_id,
        "name": cluster_name,
        "status": "pending",
        "message": "Cluster creation request received.",
        **inventory_input_data # Unpack the prepared dict including ports
    }

    logger.info(f"Scheduling Ansible playbook run for cluster: {cluster_id}, Name: {cluster_name}")

    background_tasks.add_task(
        ansible_service.run_creation_playbook,
        inventory_data=cluster_status_db[cluster_id],
        extra_vars=extra_vars,
        cluster_id=cluster_id,
        status_db=cluster_status_db
    )

    return ClusterCreateResponse(
        message="Cluster creation process has been initiated.",
        cluster_id=cluster_id,
        status=cluster_status_db[cluster_id]["status"]
    )

@router.get("/", response_model=List[ClusterInfo])
async def list_clusters():
    """List all managed clusters and their current status."""
    return [adapt_status_to_cluster_info(info) for info in cluster_status_db.values()]

@router.get("/{cluster_id}/status", response_model=ClusterInfo)
async def get_cluster_status(cluster_id: str):
    """Retrieve the current status of a cluster creation or deletion process."""
    if cluster_id not in cluster_status_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{cluster_id}' not found")

    status_info = cluster_status_db[cluster_id]
    return adapt_status_to_cluster_info(status_info)

@router.delete("/{cluster_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_cluster(cluster_id: str, background_tasks: BackgroundTasks):
    """
    Triggers Ansible playbook execution to delete a cluster.
    """
    if cluster_id not in cluster_status_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{cluster_id}' not found")
    cluster_info = cluster_status_db[cluster_id]
    current_status = cluster_info.get("status")
    if current_status in ["deleting", "preparing_deletion", "deleted"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Cluster '{cluster_id}' is already in status '{current_status}'")

    logger.info(f"Scheduling Ansible playbook run for cluster deletion: {cluster_id}")
    
    # Prepare extra_vars needed for deletion playbook (currently only VIP for potential checks)
    extra_vars = {
         "vip_address": str(cluster_info.get("vip"))
    }
    # Removed password handling here as it's not used by the current destroy playbook
    # and storing it is insecure. If needed later, use Vault or re-prompt.

    ansible_service.update_status(cluster_id, "pending_deletion", cluster_status_db, message="Cluster deletion request received.")
    background_tasks.add_task(
        ansible_service.run_deletion_playbook,
        cluster_info=cluster_info,
        extra_vars=extra_vars,
        cluster_id=cluster_id,
        status_db=cluster_status_db
    )
    return Response(status_code=status.HTTP_202_ACCEPTED, content=f"Cluster {cluster_id} deletion process initiated.")

# --- Worker Node Management Endpoints ---

@router.post("/{cluster_id}/workers", status_code=status.HTTP_202_ACCEPTED)
async def add_worker_node(
    cluster_id: str, 
    worker_request: NodeInfo = Body(...), # Use NodeInfo model for request body
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Adds a new worker node to an existing cluster."""
    if cluster_id not in cluster_status_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{cluster_id}' not found")
    
    cluster_info = cluster_status_db[cluster_id]
    current_status = cluster_info.get("status")

    # Check if cluster is in a state ready to accept workers
    if current_status != "running":
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                            detail=f"Cluster '{cluster_id}' is not in 'running' state (current: {current_status}). Cannot add worker.")

    # Check if worker IP or name already exists
    new_worker_dict = worker_request.dict()
    new_worker_dict['ip'] = str(new_worker_dict['ip']) # Ensure string IP
    for existing_worker in cluster_info.get("worker_nodes_info", []):
        if existing_worker.get("ip") == new_worker_dict['ip'] or existing_worker.get("name") == new_worker_dict['name']:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Worker with name '{new_worker_dict['name']}' or IP '{new_worker_dict['ip']}' already exists in cluster '{cluster_id}'")

    logger.info(f"Scheduling Add Worker Node playbook for cluster {cluster_id}, New Worker: {worker_request.name} ({worker_request.ip})")

    # Update status before starting background task
    ansible_service.update_status(cluster_id, "adding_worker", cluster_status_db, message=f"Request received to add worker {worker_request.name}.")

    # Extra vars might not be strictly needed if join command handles all
    extra_vars = {}

    background_tasks.add_task(
        ansible_service.run_add_worker_playbook,
        cluster_info=cluster_info,
        new_worker_info=new_worker_dict,
        cluster_id=cluster_id,
        status_db=cluster_status_db
    )

    # TODO: The service needs to update cluster_info["worker_nodes_info"] upon success.

    return Response(status_code=status.HTTP_202_ACCEPTED, 
                    content=f"Worker node {worker_request.name} addition process initiated for cluster {cluster_id}.")

@router.delete("/{cluster_id}/workers/{worker_identifier}", status_code=status.HTTP_202_ACCEPTED)
async def remove_worker_node(
    cluster_id: str, 
    worker_identifier: str, # Can be name or IP
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Removes a worker node from an existing cluster."""
    if cluster_id not in cluster_status_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{cluster_id}' not found")

    cluster_info = cluster_status_db[cluster_id]
    current_status = cluster_info.get("status")

    if current_status != "running":
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                            detail=f"Cluster '{cluster_id}' is not in 'running' state (current: {current_status}). Cannot remove worker.")

    # Find the worker node to remove by name or IP
    worker_to_remove = None
    for worker in cluster_info.get("worker_nodes_info", []):
        if worker.get("name") == worker_identifier or worker.get("ip") == worker_identifier:
            worker_to_remove = worker
            break
    
    if not worker_to_remove:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, 
                            detail=f"Worker '{worker_identifier}' not found in cluster '{cluster_id}'")

    worker_name = worker_to_remove.get("name")
    logger.info(f"Scheduling Remove Worker Node playbook for cluster {cluster_id}, Worker: {worker_name}")

    # Update status before starting background task
    ansible_service.update_status(cluster_id, "removing_worker", cluster_status_db, message=f"Request received to remove worker {worker_name}.")

    # Extra vars might not be needed if playbook gets name from inventory/passed var
    extra_vars = {} 

    background_tasks.add_task(
        ansible_service.run_remove_worker_playbook,
        cluster_info=cluster_info,
        worker_to_remove=worker_to_remove,
        cluster_id=cluster_id,
        status_db=cluster_status_db
    )

    # TODO: The service needs to update cluster_info["worker_nodes_info"] upon success.

    return Response(status_code=status.HTTP_202_ACCEPTED, 
                    content=f"Worker node {worker_name} removal process initiated for cluster {cluster_id}.")

# TODO: Add endpoint for adding worker nodes (triggering add_worker_node.yml) 

@router.get("/{cluster_id}/logs", response_model=List[str])
async def get_cluster_logs(cluster_id: str):
    """
    클러스터 Ansible 실행 로그를 반환합니다.
    """
    if cluster_id not in cluster_status_db:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    
    # 로그가 없으면 빈 리스트 반환
    if "logs" not in cluster_status_db[cluster_id]:
        return []
    
    return cluster_status_db[cluster_id]["logs"]