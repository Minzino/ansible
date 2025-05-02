from pydantic import BaseModel, Field, IPvAnyAddress, SecretStr, validator
from typing import List, Optional, Dict, Any
from datetime import datetime

class NodeInfo(BaseModel):
    name: str = Field(..., description="Node hostname used in inventory")
    ip: IPvAnyAddress = Field(..., description="Node IP address")
    user: Optional[str] = Field(None, description="SSH user for this specific node (overrides default)")
    port: Optional[int] = Field(None, gt=0, lt=65536, description="SSH port for this specific node (overrides default)")
    ssh_password: Optional[SecretStr] = Field(None, description="SSH password for this specific node (overrides default)")

class ClusterCreateRequest(BaseModel):
    cluster_name: str = Field(default="kubernetes", description="Name for the Kubernetes cluster")
    bastion_ip: IPvAnyAddress = Field(..., description="Bastion node IP address")
    bastion_port: Optional[int] = Field(None, gt=0, lt=65536, description="SSH port for the bastion node (defaults to 22)") # Bastion port
    master_nodes: List[NodeInfo] = Field(..., min_length=3, max_length=3, description="List of 3 master node details")
    worker_nodes: List[NodeInfo] = Field(..., min_length=3, max_length=3, description="List of 3 worker node details")
    # Assuming etcd runs on master nodes for this basic setup
    # If etcd nodes are separate, add: etcd_nodes: List[NodeInfo] = Field(..., min_length=3, max_length=3)
    vip_address: IPvAnyAddress = Field(..., description="Virtual IP address for Kubernetes API server")
    vip_interface: Optional[str] = None
    ansible_user: Optional[str] = Field("ubuntu", description="Default SSH user for Ansible connections")
    default_ssh_port: Optional[int] = 22
    ssh_private_key_path: Optional[str] = "/root/.ssh/id_rsa" # SSH 개인키 경로 추가
    # SSH 인증 옵션 추가
    ssh_password: Optional[SecretStr] = Field(None, description="Default SSH password for Ansible connections")
    use_ssh_password: bool = Field(False, description="Whether to use password authentication instead of key-based authentication")
    # Use SecretStr for sensitive data
    pcs_hacluster_password: SecretStr = Field(..., description="Password for the 'hacluster' user for PCS")
    # Add other necessary variables like SSH key path if needed
    # ssh_private_key_path: Optional[str] = None

    @validator('master_nodes', 'worker_nodes')
    def set_default_ssh_port(cls, nodes, values):
        default_port = values.get('default_ssh_port')
        if default_port:
            for node in nodes:
                if node.port is None:
                    node.port = default_port
        return nodes

    # If individual passwords are not set, apply default ssh_password
    @validator('master_nodes', 'worker_nodes', pre=True, each_item=True)
    def apply_default_password(cls, v, values):
        if isinstance(v, dict) and v.get('ssh_password') is None and values.get('use_ssh_password', False):
            default_password = values.get('ssh_password')
            if default_password:
                v['ssh_password'] = default_password
        return v

class ClusterInfo(BaseModel):
    id: str # Or UUID
    name: str
    status: str # e.g., "creating", "running", "failed", "deleting"
    vip: IPvAnyAddress
    master_ips: List[IPvAnyAddress]
    worker_ips: List[IPvAnyAddress]
    message: Optional[str] = None
    last_error: Optional[str] = None

class ClusterCreateResponse(BaseModel):
    message: str
    cluster_id: str # ID to track the creation process
    status: str = "creating"

class LogEntry(BaseModel):
    """로그 항목 모델"""
    timestamp: str
    message: str

class ClusterLogs(BaseModel):
    """클러스터 로그 모델"""
    cluster_id: str
    cluster_name: str
    log_entries: List[LogEntry] = [] 