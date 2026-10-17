from typing import Any

from pydantic import BaseModel

from smart_locker.db.db_connector import DBConnector
from smart_locker.exceptions import NotFoundException


class SmartLockerAdapter[ModelType: BaseModel]:
    """
    ### SmartLockerAdapter
    Generic data access adapter. Each subclass binds a pydantic model and the
    table it is stored in, e.g. `class LockerAdapter(SmartLockerAdapter[LockerModel])`.
    """

    model: type[ModelType]
    table_name: str
    primary_key: str = "id"

    def __init__(self, connector: DBConnector) -> None:

        self.connector = connector

    def get_by_key(self, key: Any) -> ModelType:

        rows = self.connector.run_query(
            f"SELECT * FROM `{self.table_name}` WHERE `{self.primary_key}` = %s",
            (key,),
        )
        if not rows:
            raise NotFoundException(
                message=f"{self.model.__name__} with {self.primary_key}={key} was not found.",
                metadata={"table": self.table_name, "key": key},
            )

        return self._to_model(rows[0])

    def get_all(self) -> list[ModelType]:

        rows = self.connector.run_query(f"SELECT * FROM `{self.table_name}`")
        return [self._to_model(row) for row in rows]

    def _to_model(self, row: dict[str, Any]) -> ModelType:

        return self.model.model_validate(row)
