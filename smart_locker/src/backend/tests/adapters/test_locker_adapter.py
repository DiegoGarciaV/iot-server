

from smart_locker.adapters.locker_adapter import LockerAdapter
from tests.test_connector import mysql_connector

locker_adapter = LockerAdapter(connector=mysql_connector)

lockers = locker_adapter.get_all()

for locker in lockers:

    print(
f"""Locker ID: {locker.id}
    Status: {locker.status}
    """)