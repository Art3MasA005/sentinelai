class ServiceError(Exception):
    """Expected, user-facing error; `status` becomes the HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
