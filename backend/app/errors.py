class BankError(Exception):
    """사용자에게 그대로 보여줄 수 있는 업무 오류. main.py 에서 JSON 응답으로 바뀐다."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
