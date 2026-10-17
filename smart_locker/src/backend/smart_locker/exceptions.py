
from typing import Any, Dict, Optional


class SmartLockerException(Exception):
    """
    ### SmartLockerException
    Generic domain exception.
    """

    def __init__(self, 
        message: Optional[str] = None, 
        error_code: Optional[int] = 500,
        metadata: Optional[Dict[str, Any]] = None,
    ):

        self.error_code = error_code
        self.message = message
        self.metadata = metadata


class NotFoundException(SmartLockerException):
    """
    ### NotFoundException
    Generic domain exception for missing objects errors.
    """

    def __init__(self, message = None, metadata = None):
        super().__init__(
            message=message,
            metadata=metadata,
            error_code=404,
        )

class BadParametersException(SmartLockerException):
    """
    ### BadParametersException
    Generic domain exception for wrong parameters errors.
    """

    def __init__(self, message = None, metadata = None):
        super().__init__(
            message=message,
            metadata=metadata,
            error_code=400,
        )


class ConflictedDataException(SmartLockerException):
    """
    ### ConflictedDataException
    Generic domain exception for confliected data errors.
    """

    def __init__(self, message = None, metadata = None):
        super().__init__(
            message=message,
            metadata=metadata,
            error_code=409
        )
