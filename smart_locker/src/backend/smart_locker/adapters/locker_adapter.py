from smart_locker.adapters.base_adapter import SmartLockerAdapter
from smart_locker.models.locker_model import LockerModel

class LockerAdapter(SmartLockerAdapter[LockerModel]):

    model = LockerModel
    table_name = "locker"
