from enum import Enum
from typing import Optional

from pydantic import BaseModel

class LockerStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DEPOSITING = "depositing"
    OCCUPIED = "occupied"
    PICKING_UP = "picking_up"
    UNAVAILABLE = "unavailable"


class LockerModel(BaseModel):
    id: int
    status: LockerStatus = LockerStatus.AVAILABLE
