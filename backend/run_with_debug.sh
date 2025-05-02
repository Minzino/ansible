#!/bin/bash
# 디버그 모드에서 백엔드 서버 실행

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd ) # Get backend directory
VENV_DIR="$SCRIPT_DIR/venv" # Path to venv inside backend

# 가상 환경 확인 및 활성화
if [ -d "$VENV_DIR" ]; then
    echo "가상 환경($VENV_DIR)을 활성화합니다..."
    source "$VENV_DIR/bin/activate"
else
    echo "가상 환경($VENV_DIR)이 존재하지 않습니다. 프로젝트 루트에서 ./setup.sh 를 실행하세요."
    exit 1
fi

# 실행 디렉토리 및 로그 파일 설정 (로그는 backend 디렉토리 내에 생성)
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="${LOG_DIR}/backend_$(date +%Y%m%d_%H%M%S).log"

# 로그 디렉토리 생성
mkdir -p ${LOG_DIR}

echo "백엔드 서버를 디버그 모드로 시작합니다..."
echo "실행 디렉토리: $SCRIPT_DIR"
echo "로그 파일: ${LOG_FILE}"

# backend 디렉토리로 이동하여 uvicorn 실행
cd "$SCRIPT_DIR" || exit 1 # Exit if cd fails

# 상세 로깅 레벨로 서버 시작 (로그 파일과 콘솔에 동시 출력)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug --use-colors 2>&1 | tee ${LOG_FILE}

# 실행 방법:
# 프로젝트 루트에서 ./backend/run_with_debug.sh 실행 