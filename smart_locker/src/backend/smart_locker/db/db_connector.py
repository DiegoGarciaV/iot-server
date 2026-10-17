from typing import Any, Dict, List, Optional

from mysql import connector as db_conn
from mysql.connector import MySQLConnection, Error as DBError, errorcode

from smart_locker.db.exceptions import FailedConnectionException, MalformedQueryException
from smart_locker.models.config_model import ApplicationConfig


class DBConnector:

    def __init__(self, config: ApplicationConfig) -> None:

        self.user = config.db_user
        self.password = config.db_password
        self.host = config.db_host
        self.database = config.db_database
        self.start_connection()

    def start_connection(self) -> None:
        try:
            self.connection: MySQLConnection = db_conn.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                database=self.database,
            )

        except DBError as e:
            raise FailedConnectionException(
                db_host=self.host,
                error_message=e.msg,
            )

    def close_connection(self) -> None:

        self.connection.close()
        self.is_connected = False

    def run_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:

        connection = self.connection
        if not (connection and connection.is_connected()):
            self.start_connection()

        with self.connection.cursor(dictionary=True) as cursor:
            try:
                cursor.execute(query, params)
                queried_rows = cursor.fetchall()
                return [row for row in queried_rows]

            except DBError as e:
                raise MalformedQueryException(
                    error_code=e.errno,
                    error_message=e.msg,
                )