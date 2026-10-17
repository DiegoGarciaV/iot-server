from pprint import pprint

from smart_locker.models.config_model import ApplicationConfig
from smart_locker.db.db_connector import DBConnector
from smart_locker.db.exceptions import FailedConnectionException

configs = ApplicationConfig(
    db_database="test_db",
    db_user="test_user",
    db_password="test_password",
    db_host="localhost"
)

try:
    mysql_connector = DBConnector(config=configs)

except FailedConnectionException as e:

    print(e.message)
    pprint(e.metadata)
