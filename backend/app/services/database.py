from ..routers.cluster import cluster_status_db  # Import the shared dictionary
from typing import Dict, Any

# 이전 메모리 내 저장소 정의 제거
# status_db: Dict[str, Dict[str, Any]] = {}

def get_status_db() -> Dict[str, Dict[str, Any]]:
    """공유 클러스터 상태 사전을 반환합니다."""
    # routers.cluster 모듈의 공유 사전을 직접 반환
    return cluster_status_db 