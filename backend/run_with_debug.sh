#!/bin/bash
# 디버그 모드에서 백엔드 서버 실행

# 가상 환경 확인 및 활성화
if [ -d "venv" ]; then
    echo "가상 환경을 활성화합니다..."
    source venv/bin/activate
else
    echo "가상 환경이 존재하지 않습니다. 생성 중..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
fi

# Ansible 컬렉션 설치 - posix 모듈 설치
echo "Ansible POSIX 컬렉션 설치 여부 확인 중..."
if ! ansible-galaxy collection list | grep -q "ansible.posix"; then
    echo "ansible.posix 컬렉션을 설치합니다..."
    ansible-galaxy collection install ansible.posix
else
    echo "ansible.posix 컬렉션이 이미 설치되어 있습니다."
fi

# 실행 디렉토리 및 로그 파일 설정
LOG_DIR="./logs"
LOG_FILE="${LOG_DIR}/backend_$(date +%Y%m%d_%H%M%S).log"

# 로그 디렉토리 생성
mkdir -p ${LOG_DIR}

echo "백엔드 서버를 디버그 모드로 시작합니다..."
echo "로그 파일: ${LOG_FILE}"

# 상세 로깅 레벨로 서버 시작 (로그 파일과 콘솔에 동시 출력)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug 2>&1 | tee ${LOG_FILE}

# 실행 방법:
# chmod +x run_with_debug.sh
# ./run_with_debug.sh 