#!/bin/bash
# 디버그 모드에서 백엔드 서버 실행

# 가상 환경 확인 및 활성화
if [ -d "venv" ]; then
    echo "가상 환경을 활성화합니다..."
    source venv/bin/activate
else
    echo "가상 환경이 존재하지 않습니다. 먼저 ./setup.sh 를 실행하세요."
    exit 1
fi

# 실행 디렉토리 및 로그 파일 설정
LOG_DIR="./logs"
LOG_FILE="${LOG_DIR}/backend_$(date +%Y%m%d_%H%M%S).log"

# 로그 디렉토리 생성
mkdir -p ${LOG_DIR}

echo "백엔드 서버를 디버그 모드로 시작합니다..."
echo "로그 파일: ${LOG_FILE}"

# 상세 로깅 레벨로 서버 시작 (로그 파일과 콘솔에 동시 출력)
# backend 디렉토리에서 app.main:app 으로 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug --use-colors 2>&1 | tee ${LOG_FILE}

# 실행 방법:
# chmod +x run_with_debug.sh
# ./run_with_debug.sh 