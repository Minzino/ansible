import inquirer
import requests
import os
import sys
import time
import ipaddress # For IP validation
import re # For basic hostname validation
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Load environment variables (e.g., API URL)
load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

console = Console()

# --- Validation Functions ---
def is_valid_ip(ip_str: str) -> bool:
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False

def validate_ip(answers, current):
    if not is_valid_ip(current):
        raise inquirer.errors.ValidationError('', reason=f"'{current}' is not a valid IP address.")
    return True

def validate_not_empty(answers, current):
    if not current or not current.strip():
        raise inquirer.errors.ValidationError('', reason="Input cannot be empty.")
    return True

def validate_hostname(answers, current):
    validate_not_empty(answers, current)
    # Basic check: alphanumeric, hyphens, not starting/ending with hyphen
    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$", current):
         raise inquirer.errors.ValidationError('', reason=f"'{current}' is not a valid hostname (alphanumeric, hyphens allowed)." )
    return True

def validate_comma_separated_ips(count: int):
    def validator(answers, current):
        validate_not_empty(answers, current)
        ips = [ip.strip() for ip in current.split(',') if ip.strip()]
        if len(ips) != count:
            raise inquirer.errors.ValidationError('', reason=f"Exactly {count} comma-separated IPs are required.")
        for ip in ips:
            if not is_valid_ip(ip):
                raise inquirer.errors.ValidationError('', reason=f"'{ip}' is not a valid IP address.")
        return True
    return validator

def validate_port(answers, current):
    if not current:
        return True # Optional port
    try:
        port_num = int(current)
        if 1 <= port_num <= 65535:
            return True
        else:
            raise inquirer.errors.ValidationError('', reason="Port must be between 1 and 65535.")
    except ValueError:
        raise inquirer.errors.ValidationError('', reason="Invalid port number.")

# --- API Helper Functions ---

def handle_api_error(response: requests.Response):
    """Generic handler for API errors."""
    try:
        error_data = response.json()
        detail = error_data.get("detail", "No details provided.")
        if isinstance(detail, list) and detail:
             # Handle Pydantic validation errors
             err_msgs = [f"  - {err.get('loc',[''])[-1]}: {err.get('msg','')}" for err in detail]
             console.print(f"[bold red]Error {response.status_code}: Validation Failed[/bold red]")
             console.print("\n".join(err_msgs))
        else:
             console.print(f"[bold red]Error {response.status_code}: {detail}[/bold red]")
    except requests.exceptions.JSONDecodeError:
        console.print(f"[bold red]Error {response.status_code}: {response.text}[/bold red]")

def list_clusters_api():
    """Calls the GET /clusters endpoint."""
    try:
        response = requests.get(f"{API_BASE_URL}/clusters")
        if response.status_code == 200:
            return response.json()
        else:
            handle_api_error(response)
            return None
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return None

def get_cluster_status_api(cluster_id: str):
    """Calls the GET /clusters/{cluster_id}/status endpoint."""
    try:
        response = requests.get(f"{API_BASE_URL}/clusters/{cluster_id}/status")
        if response.status_code == 200:
            return response.json()
        else:
            handle_api_error(response)
            return None
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return None

def create_cluster_api(payload: dict):
    """Calls the POST /clusters endpoint."""
    try:
        response = requests.post(f"{API_BASE_URL}/clusters", json=payload)
        if response.status_code == 202: # Accepted
            return response.json()
        else:
            handle_api_error(response)
            return None
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return None

def delete_cluster_api(cluster_id: str):
    """Calls the DELETE /clusters/{cluster_id} endpoint."""
    try:
        response = requests.delete(f"{API_BASE_URL}/clusters/{cluster_id}")
        if response.status_code == 202: # Accepted
            console.print(f"[green]Cluster '{cluster_id}' deletion initiated.[/green]")
            console.print(response.text)
            return True
        else:
            handle_api_error(response)
            return False
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return False

def add_worker_api(cluster_id: str, payload: dict):
    """Calls the POST /clusters/{cluster_id}/workers endpoint."""
    try:
        response = requests.post(f"{API_BASE_URL}/clusters/{cluster_id}/workers", json=payload)
        if response.status_code == 202:
            console.print(f"[green]Add worker node process initiated for cluster '{cluster_id}'.[/green]")
            console.print(response.text)
            return True
        else:
            handle_api_error(response)
            return False
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return False

def remove_worker_api(cluster_id: str, worker_identifier: str):
    """Calls the DELETE /clusters/{cluster_id}/workers/{worker_identifier} endpoint."""
    try:
        # URL encode the identifier? Usually not needed for simple names/IPs
        response = requests.delete(f"{API_BASE_URL}/clusters/{cluster_id}/workers/{worker_identifier}")
        if response.status_code == 202:
            console.print(f"[green]Remove worker node process initiated for '{worker_identifier}' in cluster '{cluster_id}'.[/green]")
            console.print(response.text)
            return True
        else:
            handle_api_error(response)
            return False
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return False

def get_cluster_logs_api(cluster_id: str):
    """Calls the GET /clusters/{cluster_id}/logs endpoint."""
    try:
        response = requests.get(f"{API_BASE_URL}/clusters/{cluster_id}/logs")
        if response.status_code == 200:
            return response.json()
        else:
            handle_api_error(response)
            return None
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Connection Error:[/bold red] {e}")
        return None

# --- CLI Action Functions ---

def display_clusters():
    console.print("\nFetching cluster list...", style="cyan")
    clusters = list_clusters_api()
    if clusters is None:
        return # Error handled in API function

    if not clusters:
        console.print("No clusters found.", style="yellow")
        return

    table = Table(title="Managed Kubernetes Clusters")
    table.add_column("Cluster ID", style="dim", width=36)
    table.add_column("Name", style="magenta")
    table.add_column("Status", justify="right", style="green")
    table.add_column("VIP", style="cyan")
    table.add_column("Masters", style="blue")
    table.add_column("Workers", style="blue")

    for cluster in clusters:
        status = cluster['status']
        status_color = "green"
        if "fail" in status:
            status_color = "red"
        elif "ing" in status or "pending" in status:
             status_color = "yellow"
        elif status == "deleted":
            status_color = "dim"

        table.add_row(
            cluster['id'],
            cluster['name'],
            f"[{status_color}]{status}[/{status_color}]",
            str(cluster['vip']),
            ", ".join(map(str, cluster['master_ips'])),
            ", ".join(map(str, cluster['worker_ips']))
        )
    console.print(table)

def prompt_for_cluster_creation():
    console.print("\nEnter details for the new Kubernetes cluster:", style="bold blue")
    questions = [
        inquirer.Text('cluster_name', message="Cluster Name", default="my-k8s-cluster",
                      validate=validate_not_empty),
        inquirer.Text('bastion_ip', message="Bastion Node IP",
                      validate=validate_ip),
        inquirer.Text('bastion_port', message="Bastion SSH Port (optional, defaults to 22)",
                      validate=validate_port, default=None),
        inquirer.Text('master_ips', message="Master Node IPs (comma-separated, exactly 3)",
                      validate=validate_comma_separated_ips(3)),
        inquirer.Text('worker_ips', message="Worker Node IPs (comma-separated, exactly 3)",
                      validate=validate_comma_separated_ips(3)),
        inquirer.Text('default_ssh_port', message="Default SSH Port for Master/Worker nodes (optional, defaults to 22)",
                      validate=validate_port, default=None),
        inquirer.Text('vip_address', message="Virtual IP (VIP) for API Server",
                      validate=validate_ip),
        inquirer.Password('pcs_hacluster_password', message="Password for PCS 'hacluster' user",
                         validate=validate_not_empty),
        inquirer.Text('ansible_user', message="Default SSH User for Ansible", default="ubuntu",
                      validate=validate_not_empty),
        inquirer.Text('vip_interface', message="Network Interface for VIP (optional, e.g., eth0)", default=None),
        inquirer.List('auth_method', 
                      message="SSH Authentication Method",
                      choices=[
                          ('Password Authentication', 'password'),
                          ('Key Authentication (requires pre-configured SSH keys)', 'key')
                      ],
                      default='key'),
        inquirer.Confirm('customize_node_names', 
                      message="Would you like to customize node names? (default: master-1, worker-1, etc.)",
                      default=False),
    ]
    
    answers = inquirer.prompt(questions)
    if not answers: return  # User cancelled
    
    if answers['auth_method'] == 'password':
        password_questions = [
            inquirer.Password('ssh_password', 
                              message="SSH Password for all nodes (can be overridden per node later)",
                              validate=validate_not_empty),
        ]
        password_answers = inquirer.prompt(password_questions)
        if not password_answers: return  # User cancelled
        
        answers['ssh_password'] = password_answers['ssh_password']
    
    try:
        master_ips = [ip.strip() for ip in answers['master_ips'].split(',')]
        worker_ips = [ip.strip() for ip in answers['worker_ips'].split(',')]
        default_port_int = int(answers['default_ssh_port']) if answers['default_ssh_port'] else None
        bastion_port_int = int(answers['bastion_port']) if answers['bastion_port'] else None
        
        # 노드 이름 커스터마이징 옵션이 활성화된 경우 각 노드 이름 입력 요청
        if answers['customize_node_names']:
            console.print("\n[bold blue]Enter custom names for master nodes:[/bold blue]")
            master_names = []
            for i, ip in enumerate(master_ips):
                # 기본 이름 제안: 클러스터명-master-숫자
                default_name = f"{answers['cluster_name']}-master-{i+1}".replace(' ', '-').lower()
                name_question = [
                    inquirer.Text(f'master_name_{i}', 
                                 message=f"Name for Master node with IP {ip}",
                                 default=default_name,
                                 validate=validate_hostname)
                ]
                name_answer = inquirer.prompt(name_question)
                if not name_answer: return  # User cancelled
                master_names.append(name_answer[f'master_name_{i}'])
                
            console.print("\n[bold blue]Enter custom names for worker nodes:[/bold blue]")
            worker_names = []
            for i, ip in enumerate(worker_ips):
                # 기본 이름 제안: 클러스터명-worker-숫자
                default_name = f"{answers['cluster_name']}-worker-{i+1}".replace(' ', '-').lower()
                name_question = [
                    inquirer.Text(f'worker_name_{i}', 
                                 message=f"Name for Worker node with IP {ip}",
                                 default=default_name,
                                 validate=validate_hostname)
                ]
                name_answer = inquirer.prompt(name_question)
                if not name_answer: return  # User cancelled
                worker_names.append(name_answer[f'worker_name_{i}'])
        else:
            # 기존 방식대로 이름 자동 생성
            master_names = [f"master-{i+1}" for i in range(len(master_ips))]
            worker_names = [f"worker-{i+1}" for i in range(len(worker_ips))]

        # Create NodeInfo structure
        master_nodes = []
        for i, ip in enumerate(master_ips):
            master_nodes.append({
                "name": master_names[i], 
                "ip": ip,
                "port": default_port_int
            })
        worker_nodes = []
        for i, ip in enumerate(worker_ips):
             worker_nodes.append({
                 "name": worker_names[i], 
                 "ip": ip,
                 "port": default_port_int
             })

        payload = {
            "cluster_name": answers['cluster_name'],
            "bastion_ip": answers['bastion_ip'],
            "bastion_port": bastion_port_int, # Pass bastion port
            "master_nodes": master_nodes,
            "worker_nodes": worker_nodes,
            "default_ssh_port": default_port_int, # Pass default port for validation logic
            "vip_address": answers['vip_address'],
            "pcs_hacluster_password": answers['pcs_hacluster_password'],
            "ansible_user": answers['ansible_user'],
            "vip_interface": answers['vip_interface'] or None,
        }
        
        if answers['auth_method'] == 'password':
            payload["ssh_password"] = answers['ssh_password']
            payload["use_ssh_password"] = True

        console.print("\nSending cluster creation request...", style="cyan")
        result = create_cluster_api(payload)
        if result:
            console.print(Panel(f"[bold green]Success![/bold green]\nCluster creation initiated.\nCluster ID: [cyan]{result['cluster_id']}[/cyan]\nUse 'Check Status' to monitor progress.", title="Request Sent", border_style="green"))

    except inquirer.errors.ValidationError as e:
        console.print("[bold red]Input validation failed.[/bold red]")
    except (KeyboardInterrupt, EOFError):
        console.print("\nOperation cancelled.", style="yellow")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")

def select_cluster_for_action(action_name: str, required_status: str = None):
    """Lists clusters and prompts user to select one. Can filter by status."""
    clusters = list_clusters_api()
    if not clusters:
        console.print("No clusters available for this action.", style="yellow")
        return None
    
    filtered_clusters = clusters
    if required_status:
        filtered_clusters = [c for c in clusters if c.get('status') == required_status]
        if not filtered_clusters:
            console.print(f"No clusters found with status '{required_status}' for this action.", style="yellow")
            return None

    cluster_choices = [
        (f"{c['name']} ({c['id']} - {c['status']})", c['id']) for c in filtered_clusters
    ]
    questions = [
        inquirer.List('cluster_id',
                      message=f"Select a cluster to {action_name}",
                      choices=cluster_choices,
                      carousel=True)
    ]
    try:
        answers = inquirer.prompt(questions)
        return answers['cluster_id'] if answers else None
    except (KeyboardInterrupt, EOFError):
        console.print("\nOperation cancelled.", style="yellow")
        return None

def check_cluster_status():
    cluster_id = select_cluster_for_action("check status on")
    if not cluster_id: return

    console.print(f"\nFetching status for cluster {cluster_id}...", style="cyan")
    
    # 로그 표시 옵션 메뉴
    log_view_options = [
        inquirer.List('log_view',
                      message="로그 표시 방식을 선택하세요",
                      choices=[
                          ('실시간 로그 표시 (축약)', 'live'),
                          ('전체 상세 로그 표시 (ansible-playbook -vvv 수준)', 'detailed'),
                          ('로그 표시하지 않음', 'none')
                      ],
                      default='live'),
    ]
    
    log_view_answers = inquirer.prompt(log_view_options)
    if not log_view_answers: return
    
    log_view_mode = log_view_answers['log_view']
    show_logs = log_view_mode != 'none'
    show_detailed = log_view_mode == 'detailed'
    
    # 마지막으로 본 로그 인덱스
    last_log_index = -1
    
    # 폴링 간격 (초) - 더 빠른 업데이트
    polling_interval = 2
    
    # 로그 실시간 화면 출력 제어
    max_live_logs = 10 if not show_detailed else 100
    
    # Progress Bar 생성 (로그 모드가 아닌 경우에만)
    if not show_detailed:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) 
        progress_ctx = progress.__enter__()
        task_id = progress_ctx.add_task(f"Polling {cluster_id}", total=None)
    else:
        progress_ctx = None
        console.print("\n[bold cyan]전체 상세 로그 모드입니다. Ansible 실행 로그가 실시간으로 표시됩니다.[/bold cyan]\n")
        console.print("=" * 80)
    
    try:
        while True:
            try:
                status_data = get_cluster_status_api(cluster_id)
                if not status_data:
                    if progress_ctx:
                        progress_ctx.stop()
                    break # Error handled in API func

                status = status_data.get('status', 'unknown')
                message = status_data.get('message', '')
                last_error = status_data.get('last_error')
                
                status_color = "green"
                if "fail" in status:
                    status_color = "red"
                elif "ing" in status or "pending" in status:
                     status_color = "yellow"
                elif status == "deleted":
                    status_color = "dim"

                status_line = f"Status: [bold {status_color}]{status}[/bold {status_color}] - {message or '...'}"
                
                # 상세 모드에서는 상태 변경 시 출력
                if show_detailed:
                    console.print(f"\n[cyan]{status_line}[/cyan]\n")
                elif progress_ctx:
                    progress_ctx.update(task_id, description=status_line)
                
                # 로그 표시 옵션이 활성화된 경우 로그 가져오기
                if show_logs:
                    logs = get_cluster_logs_api(cluster_id)
                    if logs and len(logs) > last_log_index + 1:
                        # 새 로그 라인만 표시
                        new_logs = logs[last_log_index + 1:]
                        
                        # 상세 모드가 아닌 경우 진행 표시줄 일시 중지
                        if not show_detailed and progress_ctx:
                            progress_ctx.stop()
                        
                        # 로그가 너무 많으면 축약 (상세 모드 아닌 경우)
                        display_logs = new_logs
                        if not show_detailed and len(new_logs) > max_live_logs:
                            console.print(f"[dim](새 로그 {len(new_logs)}줄 중 최근 {max_live_logs}줄만 표시)[/dim]")
                            display_logs = new_logs[-max_live_logs:]
                        
                        for log_line in display_logs:
                            # ANSI 색상 코드 처리 (선택 사항)
                            if "TASK" in log_line:
                                console.print(f"[bold cyan]{log_line}[/bold cyan]")
                            elif "PLAY" in log_line:
                                console.print(f"[bold green]{log_line}[/bold green]")
                            elif "fatal:" in log_line or "ERROR" in log_line or "Failed" in log_line or "FAILED" in log_line:
                                console.print(f"[bold red]{log_line}[/bold red]")
                            elif "ok:" in log_line:
                                console.print(f"[green]{log_line}[/green]")
                            elif "changed:" in log_line:
                                console.print(f"[yellow]{log_line}[/yellow]")
                            elif "skipping:" in log_line:
                                console.print(f"[dim]{log_line}[/dim]")
                            elif "ITEM FAILED:" in log_line:
                                console.print(f"[bold red]{log_line}[/bold red]")
                            elif "CMD OUTPUT" in log_line:
                                console.print(f"[blue]{log_line}[/blue]")
                            elif "VERBOSE:" in log_line:
                                console.print(f"[dim cyan]{log_line}[/dim cyan]")
                            elif "DEBUG:" in log_line:
                                console.print(f"[dim]{log_line}[/dim]")
                            else:
                                console.print(log_line)
                        
                        # 마지막 로그 인덱스 업데이트
                        last_log_index = len(logs) - 1
                        
                        # 상세 모드가 아닌 경우 진행 표시줄 재시작
                        if not show_detailed and progress_ctx:
                            task_id = progress_ctx.add_task(f"Polling {cluster_id}", total=None)
                            progress_ctx.update(task_id, description=status_line)

                # Define terminal states for polling
                terminal_states = ["running", "failed", "deleted", "unknown", 
                                   "delete_failed", "add_worker_failed", "remove_worker_failed"]
                if status in terminal_states:
                    if not show_detailed and progress_ctx:
                        progress_ctx.stop()
                    
                    # 종료 상태 도달 시 최종 상태 표시
                    console.print("\n" + "=" * 80)
                    console.print(Panel.fit(
                        f"[bold]ID:[/bold] {status_data['id']}\n" +
                        f"[bold]Name:[/bold] {status_data['name']}\n" +
                        f"[bold]Status:[/bold] {status}\n" +
                        f"[bold]VIP:[/bold] {status_data['vip']}\n" +
                        f"[bold]Masters:[/bold] { ', '.join(map(str, status_data['master_ips'])) }\n" +
                        f"[bold]Workers:[/bold] { ', '.join(map(str, status_data['worker_ips'])) }\n" +
                        (f"[bold]Message:[/bold] {message}\n" if message else "") +
                        (f"[bold red]Last Error:[/bold red] {last_error}\n" if last_error else ""),
                        title=f"Cluster Status: {cluster_id}",
                        border_style="red" if "fail" in status else status_color # Use calculated color
                    ))
                    
                    # 작업이 완료되면 전체 로그 보기 옵션 제공
                    if show_logs and not show_detailed:
                        view_full_logs = inquirer.confirm("전체 Ansible 로그를 보시겠습니까?", default=True)
                        if view_full_logs and (logs := get_cluster_logs_api(cluster_id)):
                            console.print("\n[bold]Full Ansible Execution Logs:[/bold]", style="cyan")
                            for log_line in logs:
                                # ANSI 색상 코드 처리 (위와 동일)
                                if "TASK" in log_line:
                                    console.print(f"[bold cyan]{log_line}[/bold cyan]")
                                elif "PLAY" in log_line:
                                    console.print(f"[bold green]{log_line}[/bold green]")
                                elif "fatal:" in log_line or "ERROR" in log_line or "Failed" in log_line or "FAILED" in log_line:
                                    console.print(f"[bold red]{log_line}[/bold red]")
                                elif "ok:" in log_line:
                                    console.print(f"[green]{log_line}[/green]")
                                elif "changed:" in log_line:
                                    console.print(f"[yellow]{log_line}[/yellow]")
                                elif "skipping:" in log_line:
                                    console.print(f"[dim]{log_line}[/dim]")
                                elif "ITEM FAILED:" in log_line:
                                    console.print(f"[bold red]{log_line}[/bold red]")
                                elif "CMD OUTPUT" in log_line:
                                    console.print(f"[blue]{log_line}[/blue]")
                                elif "VERBOSE:" in log_line:
                                    console.print(f"[dim cyan]{log_line}[/dim cyan]")
                                elif "DEBUG:" in log_line:
                                    console.print(f"[dim]{log_line}[/dim]")
                                else:
                                    console.print(log_line)
                    
                    break
                
                # 폴링 간격만큼 대기
                time.sleep(polling_interval)
                
            except KeyboardInterrupt:
                if not show_detailed and progress_ctx:
                    progress_ctx.stop()
                console.print("\nStatus polling stopped.", style="yellow")
                break
                
    except Exception as e:
        console.print(f"[bold red]로그 모니터링 중 오류가 발생했습니다: {e}[/bold red]")
    finally:
        # 항상 progress context를 정리
        if not show_detailed and progress_ctx:
            progress_ctx.__exit__(None, None, None)

def delete_cluster_action():
    cluster_id = select_cluster_for_action("delete")
    if not cluster_id: return

    confirm = inquirer.confirm(f"Are you sure you want to initiate deletion for cluster {cluster_id}?", default=False)
    if confirm:
        delete_cluster_api(cluster_id)
    else:
        console.print("Deletion cancelled.", style="yellow")

def prompt_for_add_worker():
    cluster_id = select_cluster_for_action("add worker to", required_status="running")
    if not cluster_id: return

    console.print(f"\nEnter details for the new worker node to add to cluster {cluster_id}:", style="bold blue")
    questions = [
        inquirer.Text('worker_name', message="New Worker Node Name (for inventory)",
                      validate=validate_hostname),
        inquirer.Text('worker_ip', message="New Worker Node IP",
                      validate=validate_ip),
        inquirer.Text('worker_user', message="SSH User for new worker (optional, leave blank for default)", default=None),
        inquirer.Text('worker_port', message="SSH Port for new worker (optional, defaults to cluster default)", 
                      validate=validate_port, default=None),
        inquirer.List('auth_method', 
                      message="SSH Authentication Method",
                      choices=[
                          ('Password Authentication', 'password'),
                          ('Key Authentication (requires pre-configured SSH keys)', 'key')
                      ],
                      default='key'),
    ]
    
    answers = inquirer.prompt(questions)
    if not answers: return
    
    if answers['auth_method'] == 'password':
        password_questions = [
            inquirer.Password('ssh_password', 
                              message="SSH Password for new worker node",
                              validate=validate_not_empty),
        ]
        password_answers = inquirer.prompt(password_questions)
        if not password_answers: return
        
        answers['ssh_password'] = password_answers['ssh_password']
    
    try:
        payload = {
            "name": answers['worker_name'].strip(),
            "ip": answers['worker_ip'].strip(),
            "user": answers['worker_user'] or None,
            "port": int(answers['worker_port']) if answers['worker_port'] else None,
        }
        
        if answers['auth_method'] == 'password':
            payload["ssh_password"] = answers['ssh_password']
            payload["use_ssh_password"] = True
            
        add_worker_api(cluster_id, payload)

    except inquirer.errors.ValidationError as e:
        console.print("[bold red]Input validation failed.[/bold red]")
    except (KeyboardInterrupt, EOFError):
        console.print("\nOperation cancelled.", style="yellow")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")

def prompt_for_remove_worker():
    cluster_id = select_cluster_for_action("remove worker from", required_status="running")
    if not cluster_id: return

    console.print("\nFetching worker nodes...", style="cyan")
    cluster_details = get_cluster_status_api(cluster_id)
    if not cluster_details:
        console.print("[bold red]Could not fetch cluster details.[/bold red]")
        return

    worker_ips = cluster_details.get("worker_ips", [])
    worker_info_list = cluster_details.get("worker_nodes_info", [])

    worker_choices = []
    identifiers = []
    if worker_info_list and len(worker_info_list) == len(worker_ips):
        console.print("[dim]Using locally cached worker names.[/dim]")
        for worker in worker_info_list:
            name = worker.get('name', 'Unknown')
            ip = worker.get('ip', 'Unknown')
            display = f"{name} ({ip})"
            identifier = name
            worker_choices.append((display, identifier))
            identifiers.append(identifier)
    elif worker_ips:
        console.print("[yellow]Warning: Could not reliably determine worker names. Showing IPs only.[/yellow]")
        for ip in worker_ips:
            worker_choices.append((ip, ip))
            identifiers.append(ip)
    else:
        console.print("No worker nodes found for this cluster.", style="yellow")
        return

    questions = [
        inquirer.List('worker_idx',
                      message="Select a worker node to remove",
                      choices=[choice[0] for choice in worker_choices],
                      carousel=True)
    ]
    try:
        answers = inquirer.prompt(questions)
        if not answers: return

        selected_display_text = answers['worker_idx']
        selected_identifier = None
        for i, choice in enumerate(worker_choices):
            if choice[0] == selected_display_text:
                selected_identifier = identifiers[i]
                break

        if not selected_identifier:
            console.print("[bold red]Error: Could not map selection to worker identifier.[/bold red]")
            return

        confirm = inquirer.confirm(f"Are you sure you want to initiate removal for worker '{selected_identifier}' from cluster {cluster_id}?", default=False)
        if confirm:
            remove_worker_api(cluster_id, selected_identifier)
        else:
            console.print("Removal cancelled.", style="yellow")

    except inquirer.errors.ValidationError as e:
        console.print("[bold red]Input validation failed.[/bold red]")
    except (KeyboardInterrupt, EOFError):
        console.print("\nOperation cancelled.", style="yellow")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")

# 전용 로그 뷰어 함수 추가
def view_detailed_logs():
    """전용 로그 뷰어 함수 - 클러스터 로그를 다양한 방식으로 조회"""
    cluster_id = select_cluster_for_action("view logs")
    if not cluster_id: return
    
    console.print(f"\n[bold]클러스터 {cluster_id}의 로그를 조회합니다.[/bold]", style="cyan")
    
    # 로그 뷰어 옵션
    log_options = [
        inquirer.List('log_option',
                      message="로그 조회 방식을 선택하세요",
                      choices=[
                          ('전체 로그 보기', 'full'),
                          ('실시간 로그 모니터링 (새 로그만 표시)', 'tail'),
                          ('에러 로그만 보기', 'errors'),
                          ('특정 키워드로 필터링', 'filter'),
                          ('돌아가기', 'back')
                      ],
                      carousel=True),
    ]
    
    log_choice = inquirer.prompt(log_options)
    if not log_choice or log_choice['log_option'] == 'back': 
        return
    
    option = log_choice['log_option']
    logs = get_cluster_logs_api(cluster_id)
    if not logs:
        console.print("이 클러스터에 로그가 없습니다.", style="yellow")
        return
    
    if option == 'full':
        # 전체 로그 보기
        console.print(f"[bold cyan]=== 클러스터 {cluster_id} 전체 로그 ({len(logs)} 줄) ===[/bold cyan]\n")
        display_logs(logs)
        
    elif option == 'tail':
        # 실시간 모니터링 (tail -f 처럼)
        console.print(f"[bold cyan]=== 클러스터 {cluster_id} 실시간 로그 모니터링 ===[/bold cyan]")
        console.print("최신 로그만 표시합니다. Ctrl+C로 중단할 수 있습니다.", style="dim")
        
        last_log_index = len(logs) - 1
        try:
            while True:
                time.sleep(2)  # 2초마다 업데이트
                new_logs = get_cluster_logs_api(cluster_id)
                if new_logs and len(new_logs) > last_log_index + 1:
                    display_logs(new_logs[last_log_index + 1:])
                    last_log_index = len(new_logs) - 1
        except KeyboardInterrupt:
            console.print("\n로그 모니터링을 중지했습니다.", style="yellow")
            
    elif option == 'errors':
        # 에러 로그만 표시
        error_logs = [
            log for log in logs 
            if any(err in log for err in ['fatal:', 'ERROR', 'Failed', 'FAILED', 'error', 'ITEM FAILED'])
        ]
        if not error_logs:
            console.print("에러 로그가 없습니다.", style="green")
            return
            
        console.print(f"[bold red]=== 클러스터 {cluster_id} 에러 로그 ({len(error_logs)} 줄) ===[/bold red]\n")
        display_logs(error_logs)
        
    elif option == 'filter':
        # 키워드로 필터링
        keyword = inquirer.text(message="검색할 키워드를 입력하세요")
        if not keyword:
            return
            
        filtered_logs = [log for log in logs if keyword.lower() in log.lower()]
        if not filtered_logs:
            console.print(f"키워드 '{keyword}'를 포함하는 로그가 없습니다.", style="yellow")
            return
            
        console.print(f"[bold cyan]=== 키워드 '{keyword}'로 필터링된 로그 ({len(filtered_logs)} 줄) ===[/bold cyan]\n")
        display_logs(filtered_logs)

def display_logs(logs):
    """로그를 색상 코드와 함께 표시하는 헬퍼 함수"""
    for log_line in logs:
        # ANSI 색상 코드 처리 (선택 사항)
        if "TASK" in log_line:
            console.print(f"[bold cyan]{log_line}[/bold cyan]")
        elif "PLAY" in log_line:
            console.print(f"[bold green]{log_line}[/bold green]")
        elif "fatal:" in log_line or "ERROR" in log_line or "Failed" in log_line or "FAILED" in log_line:
            console.print(f"[bold red]{log_line}[/bold red]")
        elif "ok:" in log_line:
            console.print(f"[green]{log_line}[/green]")
        elif "changed:" in log_line:
            console.print(f"[yellow]{log_line}[/yellow]")
        elif "skipping:" in log_line:
            console.print(f"[dim]{log_line}[/dim]")
        elif "ITEM FAILED:" in log_line:
            console.print(f"[bold red]{log_line}[/bold red]")
        elif "CMD OUTPUT" in log_line:
            console.print(f"[blue]{log_line}[/blue]")
        elif "VERBOSE:" in log_line:
            console.print(f"[dim cyan]{log_line}[/dim cyan]")
        elif "DEBUG:" in log_line:
            console.print(f"[dim]{log_line}[/dim]")
        else:
            console.print(log_line)
    
    # 로그 끝에 구분선 추가
    console.print("\n" + "=" * 80 + "\n")

# --- Main Loop ---

def main():
    console.print(Panel("[bold cyan]Kubernetes Ansible Manager CLI[/bold cyan]", title="Welcome", expand=False))

    while True:
        questions = [
            inquirer.List('action',
                          message="What would you like to do?",
                          choices=[
                              ('1. List Clusters', 'list'),
                              ('2. Create New Cluster', 'create'),
                              ('3. Add Worker Node', 'add_worker'),
                              ('4. Remove Worker Node', 'remove_worker'),
                              ('5. Delete Cluster', 'delete'),
                              ('6. Check Cluster Status', 'status'),
                              ('7. View Detailed Logs', 'logs'),  # 새 옵션 추가
                              ('8. Exit', 'exit'),
                          ],
                          carousel=True),
        ]
        try:
            answers = inquirer.prompt(questions)
            if not answers: # User pressed Ctrl+C
                 break
            action = answers['action']

            if action == 'list':
                display_clusters()
            elif action == 'create':
                prompt_for_cluster_creation()
            elif action == 'add_worker':
                prompt_for_add_worker()
            elif action == 'remove_worker':
                prompt_for_remove_worker()
            elif action == 'delete':
                delete_cluster_action()
            elif action == 'status':
                check_cluster_status()
            elif action == 'logs':  # 새 로그 뷰어 기능 실행
                view_detailed_logs()
            elif action == 'exit':
                break
            else:
                console.print("Invalid choice, please try again.", style="yellow")

        except (KeyboardInterrupt, EOFError):
            break # Exit cleanly on Ctrl+C or Ctrl+D

    console.print("\nExiting K8s Ansible Manager CLI. Goodbye!", style="bold cyan")

if __name__ == "__main__":
    main() 