import os
import time
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from ..services.ansible_service import (
    run_create_cluster, run_destroy_cluster, 
    run_add_worker_node, run_remove_worker_node
)
from ..models.cluster import ClusterLogs, LogEntry

logger = logging.getLogger(__name__)

def get_cluster_logs(cluster_id: str, status_db: Dict) -> Optional[ClusterLogs]:
    """지정된.id의 클러스터 로그를 조회합니다."""
    if cluster_id not in status_db:
        return None
    
    cluster_info = status_db[cluster_id]
    logs = cluster_info.get("logs", [])
    
    # 로그 항목 생성
    log_entries = []
    for log in logs:
        timestamp = log.get("timestamp", datetime.now().isoformat())
        message = log.get("message", "")
        
        log_entries.append(LogEntry(
            timestamp=timestamp,
            message=message
        ))
    
    return ClusterLogs(
        cluster_id=cluster_id,
        cluster_name=cluster_info.get("name", ""),
        log_entries=log_entries
    ) 