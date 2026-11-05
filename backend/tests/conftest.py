import os
os.environ["SCHEDULER_ENABLED"] = "false"  # 실제 DB의 예약 이체를 테스트 중 실행하지 않는다.

# 실제 DB·비밀값을 읽지 않고 테스트 의존성으로 메모리 DB를 주입한다.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-only-32-characters-long")
