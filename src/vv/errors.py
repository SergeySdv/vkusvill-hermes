from enum import StrEnum


class Code(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    CONSTRAINT_FAILED = "CONSTRAINT_FAILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    STORAGE_ERROR = "STORAGE_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class VVError(Exception):
    def __init__(self, code: Code, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
