import ansible_runner
import jinja2
import os
import tempfile
import shutil
from pathlib import Path
import logging
import threading # Import threading for locks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 상대 경로로 정확한 프로젝트 루트 설정 (backend/app/services -> 3단계 상위)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent  # /root/ansible/ 또는 설치된 위치
ANSIBLE_DIR = PROJECT_ROOT / "ansible"  # ansible 디렉토리

# 경로 로깅 추가
logger.info(f"PROJECT_ROOT set to: {PROJECT_ROOT}")
logger.info(f"ANSIBLE_DIR set to: {ANSIBLE_DIR}")

# 경로 설정
INVENTORY_TEMPLATE_PATH = ANSIBLE_DIR / "inventory" / "hosts.ini.j2"
logger.info(f"Looking for inventory template at: {INVENTORY_TEMPLATE_PATH}")

# Use a lock for status updates to handle potential concurrency if scaling later
status_lock = threading.Lock()

# 로그 최대 줄 수 제한
MAX_LOG_LINES = 1000

def _generate_inventory(inventory_data: dict) -> str:
    """Generates Ansible inventory content from data."""
    # 템플릿 로더에 올바른.searchpath 전달
    template_loader = jinja2.FileSystemLoader(searchpath=str(ANSIBLE_DIR / "inventory"))
    template_env = jinja2.Environment(loader=template_loader, trim_blocks=True, lstrip_blocks=True)
    
    # 파일 이름만 전달 (경로 제외)
    template_name = INVENTORY_TEMPLATE_PATH.name
    logger.info(f"Loading template: {template_name} from searchpath: {ANSIBLE_DIR / 'inventory'}")
    
    template = template_env.get_template(template_name)

    # SSH 비밀번호 관련 옵션 처리
    use_ssh_password = inventory_data.get("use_ssh_password", False)
    default_ssh_password = None
    bastion_ssh_password = None
    
    if use_ssh_password and "ssh_password" in inventory_data:
        # 비밀번호가 SecretStr 객체인 경우 처리
        if hasattr(inventory_data["ssh_password"], "get_secret_value"):
            default_ssh_password = inventory_data["ssh_password"].get_secret_value()
        else:
            default_ssh_password = inventory_data["ssh_password"]
    
    # Bastion 노드 비밀번호 처리
    if use_ssh_password and "bastion_ssh_password" in inventory_data:
        if hasattr(inventory_data["bastion_ssh_password"], "get_secret_value"):
            bastion_ssh_password = inventory_data["bastion_ssh_password"].get_secret_value()
        else:
            bastion_ssh_password = inventory_data["bastion_ssh_password"]
    elif use_ssh_password and default_ssh_password:
        bastion_ssh_password = default_ssh_password

    # Prepare context, extracting port information
    context = {
        "bastion_ip": str(inventory_data.get("bastion_ip")),
        "bastion_port": inventory_data.get("bastion_port"), # Get bastion port
        "bastion_ssh_password": bastion_ssh_password,
        "master_nodes": inventory_data.get("master_nodes_info", []),
        "worker_nodes": inventory_data.get("worker_nodes_info", []),
        "etcd_nodes": inventory_data.get("master_nodes_info", []),
        "ansible_user": inventory_data.get("ansible_user", "ubuntu"),
        "use_ssh_password": use_ssh_password,
        "default_ssh_password": default_ssh_password,
    }
    
    # Ensure IPs and Ports within the nodes lists are correctly formatted
    for node_list_key in ["master_nodes", "worker_nodes", "etcd_nodes"]:
        if node_list_key in context:
            for node in context[node_list_key]:
                if isinstance(node, dict):
                    if 'ip' in node:
                        node['ip'] = str(node['ip'])
                    # Ensure port is int if present, otherwise jinja ignores it
                    if 'port' in node and node['port'] is not None:
                        try:
                            node['port'] = int(node['port'])
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid port value '{node['port']}' for node {node.get('name')}, ignoring.")
                            node.pop('port') # Remove invalid port
                    elif 'port' in node: # If port is None, remove it so Jinja condition works
                         node.pop('port')
                         
                    # SSH 비밀번호 처리
                    if 'ssh_password' in node and hasattr(node['ssh_password'], 'get_secret_value'):
                        node['ssh_password'] = node['ssh_password'].get_secret_value()
                        
                # Handle Pydantic models if somehow passed (less likely)
                elif hasattr(node, 'ip'): 
                    node.ip = str(node.ip)
                    if not hasattr(node, 'port') or node.port is None:
                         # Ensure no port attribute if None
                         if hasattr(node, 'port'): delattr(node, 'port')
                    # SSH 비밀번호 처리
                    if hasattr(node, 'ssh_password') and node.ssh_password is not None:
                        if hasattr(node.ssh_password, 'get_secret_value'):
                            node.ssh_password = node.ssh_password.get_secret_value()

    return template.render(context)

def update_status(cluster_id, status, status_db, message=None, error_info=None, runner_artifact_dir=None, log_line=None):
    """Helper function to update cluster status safely."""
    with status_lock:
        if cluster_id in status_db:
            status_db[cluster_id]["status"] = status
            if message:
                status_db[cluster_id]["message"] = message
            if error_info:
                status_db[cluster_id]["last_error"] = error_info
            if runner_artifact_dir:
                 status_db[cluster_id]["runner_artifact_dir"] = runner_artifact_dir
            
            # 로그 처리 추가
            if log_line:
                # 로그 배열이 없다면 초기화
                if "logs" not in status_db[cluster_id]:
                    status_db[cluster_id]["logs"] = []
                
                # 로그 추가
                status_db[cluster_id]["logs"].append(log_line)
                
                # 로그 최대 라인 수 제한
                if len(status_db[cluster_id]["logs"]) > MAX_LOG_LINES:
                    status_db[cluster_id]["logs"] = status_db[cluster_id]["logs"][-MAX_LOG_LINES:]

            # Avoid logging sensitive data potentially in error_info
            log_message = f"Cluster {cluster_id} status updated to: {status}"
            if message: log_message += f" - {message}"
            logger.info(log_message)
        else:
            logger.error(f"Cluster ID {cluster_id} not found in status DB for update.")

def ansible_event_handler(event, cluster_id, status_db):
    """Callback function for ansible-runner events."""
    event_type = event['event']
    event_data = event.get('event_data', {})
    
    # 모든 이벤트에서 로그 줄 추출 및 저장
    if 'stdout' in event and event['stdout'] and event['stdout'].strip():
        log_line = event['stdout'].strip()
        update_status(cluster_id, status_db[cluster_id]["status"], status_db, log_line=log_line)
    
    # 이벤트 타입별 처리 (기존 코드)
    if event_type == 'runner_on_failed':
        task_name = event_data.get('task')
        host = event_data.get('host')
        result = event_data.get('res', {})
        error_msg = f"Task '{task_name}' failed on host '{host}'. Result: {result.get('msg', 'No message')}"
        logger.error(error_msg)
        update_status(cluster_id, status_db[cluster_id]["status"], status_db, error_info=error_msg)

    elif event_type == 'playbook_on_task_start':
        task_name = event_data.get('name')
        logger.info(f"Cluster {cluster_id}: Starting task: {task_name}")
        update_status(cluster_id, status_db[cluster_id]["status"], status_db, message=f"Running task: {task_name}")

    elif event_type == 'verbose': # Reduce noise from verbose events if needed
        pass
    else:
        # 로그 이벤트 디버깅을 위해 주석 해제
        # logger.debug(f"Cluster {cluster_id}: Ansible event: {event_type}")
        pass

def ansible_status_handler(status_data, runner_config, cluster_id, status_db):
    """Callback function for ansible-runner status changes (end of playbook)."""
    final_status = status_data['status']
    artifact_dir = runner_config.private_data_dir
    playbook_name = Path(runner_config.playbook).name
    cluster_info = status_db.get(cluster_id, {})

    success_status = "unknown"
    success_message = "Playbook execution successful."
    if playbook_name == "create_cluster.yml":
        success_status = "running"
        success_message = "Cluster creation successful."
    elif playbook_name == "destroy_cluster.yml":
        success_status = "deleted"
        success_message = "Cluster deletion successful."
        # Potentially remove cluster from status_db here after successful deletion?
        # Be careful with concurrency if multiple requests happen.
        # with status_lock:
        #     if cluster_id in status_db and status_db[cluster_id]["status"] == "deleting":
        #        del status_db[cluster_id]
        #        logger.info(f"Removed successfully deleted cluster {cluster_id} from status DB.")
    elif playbook_name == "add_worker_node.yml":
        success_status = "running" # Back to running after adding worker
        success_message = "Worker node added successfully."
        # Update worker list in status DB upon success
        if final_status == 'successful' and cluster_info:
            new_worker_name = runner_config.extravars.get("new_worker_name") # Need to pass this to runner? Or parse from inventory?
            # This part is tricky without knowing exactly which worker was added from extravars
            # Requires passing the added worker info to this handler or re-parsing inventory.
            # Placeholder: Log that update is needed.
            logger.info(f"Cluster {cluster_id}: Worker node added. Status DB update needed manually or via improved logic.")

    elif playbook_name == "remove_worker_node.yml":
        success_status = "running" # Back to running after removing worker
        success_message = "Worker node removed successfully."
        # Update worker list in status DB upon success
        if final_status == 'successful' and cluster_info:
            removed_worker_name = runner_config.extravars.get("node_to_remove_name")
            if removed_worker_name:
                with status_lock:
                    current_workers = cluster_info.get("worker_nodes_info", [])
                    updated_workers = [w for w in current_workers if w.get("name") != removed_worker_name]
                    cluster_info["worker_nodes_info"] = updated_workers
                    logger.info(f"Updated worker list for cluster {cluster_id} after removing {removed_worker_name}.")
            else:
                logger.warning(f"Could not determine removed worker name for cluster {cluster_id} to update status DB.")

    if final_status == 'successful':
        update_status(cluster_id, success_status, status_db, success_message, runner_artifact_dir=artifact_dir)
    elif final_status == 'failed':
        fail_status = "failed"
        if playbook_name == "add_worker_node.yml": fail_status = "add_worker_failed"
        elif playbook_name == "remove_worker_node.yml": fail_status = "remove_worker_failed"
        elif playbook_name == "destroy_cluster.yml": fail_status = "delete_failed"

        last_error = status_db.get(cluster_id, {}).get("last_error", "Playbook execution failed. Check logs.")
        update_status(cluster_id, fail_status, status_db, "Playbook execution failed.", error_info=last_error, runner_artifact_dir=artifact_dir)
    elif final_status == 'running':
        logger.info(f"Ansible playbook for cluster {cluster_id} is still running...") # Should not happen as final status
    else:
        logger.warning(f"Cluster {cluster_id}: Unhandled final status: {final_status}")
        update_status(cluster_id, "unknown", status_db, f"Playbook finished with status: {final_status}", runner_artifact_dir=artifact_dir)

    # Log artifact directory for potential manual cleanup
    logger.info(f"Ansible runner artifacts for cluster {cluster_id} are in: {artifact_dir}. Manual cleanup may be required.")

def _run_ansible(playbook_name: str, inventory_content: str, extra_vars: dict, cluster_id: str, status_db: dict):
    """Internal function to configure and run ansible-runner."""
    private_data_dir = None
    try:
        private_data_dir = tempfile.mkdtemp(prefix=f"ansible_runner_{cluster_id}_")
        inventory_file_path = os.path.join(private_data_dir, "hosts.ini")
        with open(inventory_file_path, 'w') as f:
            f.write(inventory_content)

        # 플레이북 경로 수정 및 존재 확인 로깅 추가
        full_playbook_path = str(ANSIBLE_DIR / "playbooks" / playbook_name)
        logger.info(f"Looking for playbook at: {full_playbook_path}")
        
        if not os.path.exists(full_playbook_path):
            # 파일이 없으면 다른 위치도 시도
            alternative_path = str(PROJECT_ROOT / "playbooks" / playbook_name)
            logger.info(f"Playbook not found, trying alternative path: {alternative_path}")
            
            if os.path.exists(alternative_path):
                full_playbook_path = alternative_path
                logger.info(f"Using alternative playbook path: {full_playbook_path}")
            else:
                raise FileNotFoundError(f"Playbook not found at {full_playbook_path} or {alternative_path}")
        
        logger.info(f"Cluster {cluster_id}: Running playbook {full_playbook_path} with inventory {inventory_file_path}")
        log_extra_vars = {k: ('***' if 'password' in k else v) for k, v in extra_vars.items()}
        logger.debug(f"Cluster {cluster_id}: Extra Vars: {log_extra_vars}")

        # 실행 옵션 향상: verbosity 추가하여 더 상세한 로그 생성 (-vv와 동일)
        runner_thread, runner = ansible_runner.run_async(
            private_data_dir=private_data_dir,
            playbook=full_playbook_path,
            inventory=inventory_file_path,
            extravars=extra_vars,
            event_handler=lambda e: ansible_event_handler(e, cluster_id, status_db),
            status_handler=lambda s, rc: ansible_status_handler(s, rc, cluster_id, status_db),
            quiet=False,
            verbosity=2,  # -vv 수준의 상세 로그 생성
        )
        # Pass the temp dir path to the status handler via the runner_config
        # (ansible_status_handler already receives runner_config)

    except Exception as e:
        logger.exception(f"Error preparing Ansible run for {cluster_id}")
        # Ensure status is updated even if run_async fails to start
        update_status(cluster_id, "failed", status_db, f"Error preparing Ansible: {str(e)}", runner_artifact_dir=private_data_dir)
        # Log artifact dir even on preparation failure for potential partial artifacts
        if private_data_dir:
            logger.info(f"Ansible runner artifacts (potentially incomplete) for cluster {cluster_id} are in: {private_data_dir}. Manual cleanup may be required.")

def run_creation_playbook(inventory_data: dict, extra_vars: dict, cluster_id: str, status_db: dict):
    """Runs the cluster creation playbook."""
    logger.info(f"Initiating cluster creation for {cluster_id}")
    update_status(cluster_id, "preparing", status_db, "Generating inventory and preparing Ansible.")
    try:
        inventory_content = _generate_inventory(inventory_data)
        logger.debug(f"Generated Inventory for {cluster_id} creation:\n{inventory_content}")
        update_status(cluster_id, "creating", status_db, "Inventory generated. Starting Ansible playbook.")
        _run_ansible("create_cluster.yml", inventory_content, extra_vars, cluster_id, status_db)
    except Exception as e:
        logger.exception(f"Failed to generate inventory or start playbook for {cluster_id}")
        update_status(cluster_id, "failed", status_db, f"Setup Error: {str(e)}")

def run_deletion_playbook(cluster_info: dict, extra_vars: dict, cluster_id: str, status_db: dict):
    """Runs the cluster deletion playbook."""
    logger.info(f"Initiating cluster deletion for {cluster_id}")
    update_status(cluster_id, "preparing_deletion", status_db, "Generating inventory for deletion.")
    try:
        # We need inventory data from the stored cluster_info
        inventory_content = _generate_inventory(cluster_info)
        logger.debug(f"Generated Inventory for {cluster_id} deletion:\n{inventory_content}")
        update_status(cluster_id, "deleting", status_db, "Inventory generated. Starting deletion playbook.")
        _run_ansible("destroy_cluster.yml", inventory_content, extra_vars, cluster_id, status_db)
    except Exception as e:
        logger.exception(f"Failed to generate inventory or start deletion playbook for {cluster_id}")
        update_status(cluster_id, "delete_failed", status_db, f"Deletion Setup Error: {str(e)}")

def _get_worker_join_command(cluster_info: dict) -> str:
    """
    Placeholder: Gets a fresh worker join command.
    !!! CRITICAL: This requires running 'kubeadm token create' on a master node.
    This placeholder returns a dummy value. A real implementation needs:
    1. Secure mechanism to execute commands on the master (e.g., dedicated Ansible run, k8s API client).
    2. Proper inventory and authentication for the command execution.
    Failure to implement this securely will prevent adding worker nodes.
    """
    logger.critical("CRITICAL: _get_worker_join_command is a placeholder and will not work. Needs implementation.")
    # Simulate fetching command (replace with actual implementation)
    # master_ip = cluster_info.get("master_nodes_info", [{}])[0].get("ip", "DUMMY_MASTER_IP")
    # cmd_result = run_command_on_host(master_ip, "kubeadm token create --print-join-command")
    # return cmd_result
    return f"kubeadm join {cluster_info.get('vip', 'API_ENDPOINT')}:6443 --token DUMMY_TOKEN --discovery-token-ca-cert-hash sha256:DUMMY_HASH"

def run_add_worker_playbook(cluster_info: dict, new_worker_info: dict, cluster_id: str, status_db: dict):
    """Runs the add worker node playbook."""
    logger.info(f"Initiating add worker node for cluster {cluster_id}")
    update_status(cluster_id, "adding_worker", status_db, f"Preparing to add worker {new_worker_info.get('name')}.")
    try:
        # 1. Get worker join command
        try:
            worker_join_cmd = _get_worker_join_command(cluster_info)
            # Check if it's still the dummy value
            if "DUMMY_TOKEN" in worker_join_cmd:
                raise NotImplementedError("_get_worker_join_command placeholder is used.")
        except Exception as e:
            logger.error(f"Failed to retrieve worker join command for {cluster_id}: {e}")
            update_status(cluster_id, "add_worker_failed", status_db, f"Error: Could not get join command. {e}")
            return

        # 2. Prepare inventory containing only the new worker node
        new_worker_inventory_data = {
            # Use a temporary group name or just 'all'?
            # Let's assume the playbook targets 'all' from the temp inventory.
            "worker_nodes_info": [new_worker_info], # Pass as worker_nodes_info for _generate_inventory?
            "ansible_user": cluster_info.get("ansible_user", "ubuntu"),
            # Ensure IPs are strings
        }
        new_worker_info['ip'] = str(new_worker_info['ip'])

        template_loader = jinja2.FileSystemLoader(searchpath=str(ANSIBLE_DIR / "inventory"))
        template_env = jinja2.Environment(loader=template_loader, trim_blocks=True, lstrip_blocks=True)
        template = template_env.get_template(INVENTORY_TEMPLATE_PATH.name)
        # Render with only the new worker (using a trick with group names or modifying template slightly might be cleaner)
        # Quick hack: Temporarily override nodes in context for rendering
        add_context = {
             "bastion_ip": None, "master_nodes": [], "worker_nodes": [new_worker_info], "etcd_nodes": [],
             "ansible_user": new_worker_inventory_data["ansible_user"]
        }
        inventory_content = template.render(add_context)

        logger.debug(f"Generated Inventory for adding worker to {cluster_id}:\n{inventory_content}")

        # 3. Prepare extra_vars
        add_extra_vars = {
            "worker_join_command": worker_join_cmd,
            "k8s_version": cluster_info.get("k8s_version", "1.29.7"),
        }

        update_status(cluster_id, "adding_worker", status_db, f"Starting add worker playbook for {new_worker_info.get('name')}.")
        _run_ansible("add_worker_node.yml", inventory_content, add_extra_vars, cluster_id, status_db)

    except Exception as e:
        logger.exception(f"Failed to prepare add worker playbook for {cluster_id}")
        update_status(cluster_id, "add_worker_failed", status_db, f"Add Worker Setup Error: {str(e)}")

def run_remove_worker_playbook(cluster_info: dict, worker_to_remove: dict, cluster_id: str, status_db: dict):
    """Runs the remove worker node playbook."""
    worker_name = worker_to_remove.get("name")
    logger.info(f"Initiating remove worker node '{worker_name}' for cluster {cluster_id}")
    update_status(cluster_id, "removing_worker", status_db, f"Preparing to remove worker {worker_name}.")
    try:
        # 1. Generate inventory including masters and the node to remove
        # _generate_inventory expects master_nodes_info, worker_nodes_info
        # Ensure the node being removed is included in worker_nodes_info for the reset task targeting
        remove_inventory_data = cluster_info.copy()
        # Ensure the specific node to remove is present if the status DB was modified
        if not any(n.get("name") == worker_name for n in remove_inventory_data.get("worker_nodes_info",[])):
             remove_inventory_data.setdefault("worker_nodes_info", []).append(worker_to_remove)

        inventory_content = _generate_inventory(remove_inventory_data)
        logger.debug(f"Generated Inventory for removing worker from {cluster_id}:\n{inventory_content}")

        # 2. Prepare extra_vars
        remove_extra_vars = {
            "node_to_remove_name": worker_name
        }

        update_status(cluster_id, "removing_worker", status_db, f"Starting remove worker playbook for {worker_name}.")
        _run_ansible("remove_worker_node.yml", inventory_content, remove_extra_vars, cluster_id, status_db)

    except Exception as e:
        logger.exception(f"Failed to prepare remove worker playbook for {cluster_id}")
        update_status(cluster_id, "remove_worker_failed", status_db, f"Remove Worker Setup Error: {str(e)}")

# Example of how to potentially handle cleanup later
# You might need a mechanism to know when runner_thread finishes
# def cleanup_runner_artifacts(private_data_dir):
#    if private_data_dir and os.path.exists(private_data_dir):
#        shutil.rmtree(private_data_dir)
#        logger.info(f"Cleaned up runner artifacts: {private_data_dir}") 