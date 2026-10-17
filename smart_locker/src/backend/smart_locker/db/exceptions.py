
from typing import Any, Dict, Optional

from smart_locker.exceptions import BadParametersException, SmartLockerException


class DBException(SmartLockerException):
    """
    ### DBException
    Generic class for database errors.
    """


class FailedConnectionException(DBException):
    """
    ### FailedConnectionException
    An exception raised when a database connection attempt has failed.
    """
    def __init__(self, db_host: str, error_message: str):
        super().__init__(
            message=f"Connection to database at {db_host} has failed.", 
            metadata={
                "upstream_errors": error_message,
            }
        )

class MalformedQueryException(BadParametersException):
    """
    ### MalformedQueryException
    An exception raised when a query execution returns error
    """
    def __init__(self, error_code, error_message: str):
        super().__init__(
            message=f"The following error has ocurred while executing the query: \n\t{error_message}", 
            metadata={
                "upstream_errors": error_message,
                "db_error_code": error_code,
            }
        )