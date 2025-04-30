# K8s Ansible Manager

Ansible과 FastAPI, CLI 클라이언트를 사용하여 Kubernetes 클러스터 생성 및 관리를 자동화하는 프로젝트입니다.

## 프로젝트 구조

```
k8s-ansible-manager/
├── ansible/         # Ansible 역할(roles), 플레이북(playbooks), 설정(group_vars) 등
├── backend/         # FastAPI 백엔드 API 서버 (Python)
├── client/          # CLI 클라이언트 (Python)
├── .gitignore       # Git 추적 제외 파일 목록
├── README.md        # 프로젝트 설명 및 안내 (현재 파일)
└── setup.sh         # 초기 환경 설정 스크립트
```

## 기능

*   Ansible 플레이북을 이용한 K8s 클러스터 자동 구축 (Ubuntu 20.04/22.04 기반)
    *   Bastion, Master(HA), Worker 구성 (기본 1+3+3 구성 가정)
    *   외부 ETCD 클러스터 구성 (기본적으로 마스터 노드와 동일하게 설정됨)
    *   Cilium CNI 사용
    *   PCS를 이용한 VIP 구성 (Control Plane HA)
    *   kubeadm 사용
*   FastAPI 백엔드를 통한 REST API 제공
    *   클러스터 생성, 삭제, 상태 조회, 목록 조회
    *   워커 노드 추가, 제거
    *   Ansible 플레이북 실행 관리 (비동기)
*   사용자 친화적인 CLI 클라이언트 제공 (메뉴 기반)

## 요구 사항

*   **제어 노드 (이 프로젝트를 실행하는 머신):**
    *   Python 3.8 이상 및 pip
    *   Git
    *   **Ansible (중요):** `ansible-core` 또는 `ansible` 패키지가 설치되어 있어야 합니다. (`ansible-runner`가 내부적으로 사용)
    *   SSH 클라이언트 (대상 노드 접속용)
*   **대상 노드 (클러스터 VM - Bastion, Master, Worker, ETCD):**
    *   Ubuntu 20.04 또는 22.04 LTS
    *   SSH 서버 실행 및 제어 노드로부터의 **비밀번호 없는 SSH 키 기반 접속** 설정 (매우 중요)
        *   Ansible 사용자 (기본값: `ubuntu`)의 `~/.ssh/authorized_keys`에 제어 노드의 공개키 추가 필요.
    *   `sudo` 권한을 가진 사용자 (`ansible_user`가 sudoer여야 함)
    *   인터넷 연결 (패키지 다운로드용)
    *   고정 IP 주소 권장

## 설치 및 설정

**방법 1: 자동 설정 스크립트 사용 (권장 - Linux/macOS)**

프로젝트 루트 디렉토리에서 다음 명령어를 실행하여 필요한 의존성 확인 및 설치를 시도합니다.

```bash
# 스크립트 실행 권한 부여
chmod +x setup.sh

# 스크립트 실행
./setup.sh
```
이 스크립트는 다음을 수행합니다:
*   Python 3.8+ 및 pip 확인 (미설치 시 안내)
*   Ansible 설치 확인 및 사용자 선택에 따른 설치 (pip 또는 apt 사용)
*   Python 가상 환경 생성 여부 확인 및 생성 (사용자 선택)
*   백엔드 및 클라이언트 Python 의존성 설치 (`requirements.txt` 사용)
*   완료 후 다음 단계 안내

스크립트 실행 후, 스크립트 마지막의 'Next Steps' 안내에 따라 가상 환경 활성화, SSH 키 설정 등을 진행하세요.

**방법 2: 수동 설정**

자동 설정 스크립트를 사용하지 않거나 지원되지 않는 환경인 경우, 아래 단계를 수동으로 진행하세요.

1.  **저장소 클론:**
    ```bash
    git clone <repository_url> # 이 저장소의 URL로 변경
    cd k8s-ansible-manager
    ```

2.  **Python 가상 환경 생성 및 활성화 (권장):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    # Windows: venv\Scripts\activate
    ```

3.  **Ansible 설치 (미설치 시):**
    *   **Using pip (가상 환경 내 권장):**
        ```bash
        pip install ansible-core>=2.14 # 특정 버전 이상 권장
        # 또는 최신 버전: pip install ansible
        ```
    *   **Using apt (Ubuntu/Debian):**
        ```bash
        sudo apt update && sudo apt install ansible -y
        ```
    설치 확인: `ansible --version`

4.  **백엔드 의존성 설치:**
    ```bash
    pip install -r backend/requirements.txt
    ```

5.  **클라이언트 의존성 설치:**
    ```bash
    pip install -r client/requirements.txt
    ```

6.  **클라이언트 환경 설정 (필요시):**
    `client/.env` 파일이 API 서버의 기본 주소 (`http://127.0.0.1:8000`)를 사용합니다. 백엔드 서버가 다른 곳에서 실행된다면 이 파일을 수정하거나 환경 변수 `API_BASE_URL`을 설정하세요.

7.  **대상 노드 SSH 접속 설정 (필수):**
    제어 노드에서 생성한 SSH 키 쌍의 **공개 키** (`~/.ssh/id_rsa.pub` 또는 다른 이름의 파일 내용)를 **모든 대상 노드** (Bastion, Masters, Workers, ETCD)의 **Ansible 사용자** (기본값: `ubuntu`, CLI에서 변경 가능) 홈 디렉토리 아래 `.ssh/authorized_keys` 파일에 추가해야 합니다. 그래야 Ansible이 비밀번호 입력 없이 접속할 수 있습니다.
    *   예시 (제어 노드에서 대상 노드 `target_ip`로 키 복사):
        ```bash
        ssh-copy-id ubuntu@target_ip 
        ```

## 실행 방법

1.  **(필수) 가상 환경 활성화:**
    ```bash
    source venv/bin/activate 
    ```

2.  **백엔드 API 서버 실행:**
    ```bash
    cd backend
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```
    *   `--reload` 옵션은 개발 중 코드 변경 시 자동 재시작을 위함입니다. 실제 배포 시에는 제거하고 Gunicorn 등을 사용하는 것이 좋습니다.

3.  **CLI 클라이언트 실행:**
    (백엔드 서버가 실행 중인 상태에서) 새 터미널을 열고 프로젝트 루트 디렉토리에서 다음 명령어를 실행합니다.
    ```bash
    # (다른 터미널이라면 가상 환경 다시 활성화 필요)
    # source venv/bin/activate
    python client/cli.py
    ```
    CLI 메뉴의 안내에 따라 클러스터를 생성, 관리합니다. 클러스터 생성 시 노드 이름은 CLI에서 자동으로 `master-1`, `worker-1` 등으로 지정합니다.

## 중요 참고사항 및 주의점

*   **⚠️ 비밀번호 보안 (PCS):** `load_balancer` 역할의 `pcs_hacluster_password`는 **절대로** 코드나 `defaults/main.yml` 파일에 평문으로 저장해서는 안 됩니다. **Ansible Vault 사용이 매우 강력히 권장됩니다.**
    1.  Vault 파일 생성: `ansible-vault create ansible/roles/load_balancer/vars/vault.yml` (비밀번호 설정)
    2.  Vault 파일에 변수 추가: `vault_pcs_password: YourSecurePassword`
    3.  `defaults/main.yml` 수정: `# pcs_hacluster_password: "..."` 주석 처리
    4.  `load_balancer/vars/main.yml` 생성 및 내용 추가: `pcs_hacluster_password: "{{ vault_pcs_password }}"`
    5.  백엔드 API: Vault 비밀번호를 안전하게 관리하고 `ansible-runner` 실행 시 `--vault-password-file` 또는 환경 변수를 통해 전달해야 합니다. (현재 코드 미반영)
    *   또는 CLI 실행 시 `--extra-vars` 를 통해 직접 전달하는 방법도 있으나, Vault 방식이 더 안전합니다.
*   **🔥 Join Command 구현:** 워커 노드 추가 기능은 백엔드(`ansible_service.py`)의 `_get_worker_join_command` 함수가 **실제 구현되어야 동작합니다.** 현재는 플레이스홀더 상태이며, 이를 구현하지 않으면 **워커 노드 추가가 불가능**합니다. 마스터 노드에서 `kubeadm token create --print-join-command`를 안전하게 실행하고 결과를 반환하는 로직이 필요합니다.
*   **ETCD 노드:** 현재 Ansible 플레이북은 ETCD가 마스터 노드에서 함께 실행된다고 가정합니다 (`inventory/hosts.ini.j2` 및 `ansible_service.py` 참고). 만약 ETCD 노드를 별도로 구성했다면, 해당 Jinja2 템플릿과 서비스 코드의 `etcd_nodes` 관련 로직을 수정해야 합니다.
*   **네트워크 인터페이스:** `load_balancer` 역할의 `vip_interface` 기본값 (`eth0`)은 실제 마스터 노드의 주 네트워크 인터페이스 이름과 다를 수 있습니다. 클러스터 생성 시 CLI에서 옵션으로 입력하거나 `defaults/main.yml`을 직접 수정하세요.
*   **멱등성:** Ansible 역할들은 최대한 멱등성을 유지하도록 작성되었으나, `pcs cluster setup --force` 등 일부 명령어는 상태를 강제로 변경할 수 있으며, 외부 시스템 상태에 따라 예기치 않은 결과가 발생할 수 있습니다. 반복 실행 시 주의가 필요합니다.
*   **STONITH:** `load_balancer` 역할에서 STONITH(노드 장애 시 격리 기능)는 프로덕션 환경의 안정성을 위해 **필수적**이지만, 현재 설정에서는 **비활성화**되어 있습니다. 실제 운영 환경에서는 반드시 환경에 맞는 STONITH 설정을 추가해야 합니다.
*   **상태 저장:** 백엔드는 현재 클러스터 상태를 **메모리에만 저장**합니다. 서버가 재시작되면 모든 상태 정보가 유실됩니다. 영구적인 관리를 위해서는 데이터베이스 연동 또는 파일 기반 저장 로직 구현이 필요합니다.
*   **롤백:** 현재 명시적인 롤백 기능은 구현되어 있지 않습니다. 플레이북 실행 실패 시 중간 상태로 남을 수 있으며, `destroy_cluster.yml`을 이용한 전체 삭제 후 재시도가 필요할 수 있습니다.

## 간단한 문제 해결 (Troubleshooting)

*   **Ansible SSH 접속 오류:**
    *   SSH 키가 대상 노드의 `authorized_keys`에 올바르게 추가되었는지 확인하세요.
    *   Ansible 사용자 (`ubuntu` 또는 지정한 사용자) 이름이 올바른지 확인하세요.
    *   네트워크 연결 및 방화벽 설정을 확인하세요 (SSH 포트 22).
    *   `ansible -i <inventory_file> <host_group> -m ping --user <user>` 명령으로 직접 연결 테스트를 해보세요.
*   **플레이북 실행 실패:**
    *   FastAPI 백엔드 서버의 로그를 확인하세요. `ansible-runner`의 상세 출력이 로깅됩니다.
    *   Ansible 역할 내 태스크 실패 메시지를 확인하여 원인을 파악하세요.
    *   특정 `pcs` 명령 실패 시, 마스터 노드에 직접 접속하여 `pcs status` 등으로 클러스터 상태를 확인해보세요.
*   **VIP 접속 불가:**
    *   `load_balancer` 역할이 성공적으로 완료되었는지 확인하세요.
    *   마스터 노드에서 `ip addr` 명령으로 VIP가 원하는 인터페이스에 할당되었는지 확인하세요.
    *   PCS 상태 확인 (`pcs status`)을 통해 VIP 리소스가 정상 실행 중인지 확인하세요. 