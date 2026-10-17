from pprint import pprint

from smart_locker.db.exceptions import MalformedQueryException
from tests.test_connector import mysql_connector

try:
    print("Running well formed query")
    result = mysql_connector.run_query("SELECT * FROM test_table")
    pprint(result)

except MalformedQueryException as e:
    print(e.message)

try:
    print("\nRunning malformed query")
    result = mysql_connector.run_query("SELECdT * FROM test_table")
    pprint(result)

except MalformedQueryException as e:
    print(e.message)

except Exception as e:
    print("#"*20)
    print("Raised exception:")
    print(str(e.errno))
    print(str(e.msg))

