"""
This module defines the RelToName class, which provides a mapping from instance IDs to their corresponding
names for specified entities. It queries the ODS database to build this mapping and allows for efficient
retrieval of names based on instance IDs.
"""

from typing import Any

import pandas as pd
from odsbox import ConI
from odsbox.proto import ods

import logging


class RelToName:
    """Provides a mapping from instance IDs to names for specified related entities."""

    log = logging.getLogger(__name__)

    def __init__(self, con_i: ConI, entities: list[str] | None):
        self._entity_to_id_to_name: dict[str, dict[int, str]] = {}

        for entity_name in entities or []:
            entity = con_i.mc.entity_no_throw(entity_name)
            if entity is None:
                self.log.warning("Entity '%s' not found in %s", entity_name, con_i.con_i_url)
                continue

            df = con_i.query({entity.name: {}, "$attributes": {"id": 1, "name": 1}, "$options": {"$rowlimit": 1001}})

            if not df.empty:
                if len(df) >= 1001:
                    self.log.warning(
                        "Entity '%s' has more than 1000 entries; only first 1000 will be cached", entity_name
                    )
                id_to_name = dict(zip(df["id"].astype(int), df["name"].astype(str)))
                self._entity_to_id_to_name[entity.name] = id_to_name

    def name(self, entity: str | ods.Model.Entity, iid: str | int) -> str | int:
        """
        Returns the name corresponding to the given instance ID for the specified entity.
        If the entity or instance ID is not found, the original instance ID is returned.
        """
        entity_name = entity if isinstance(entity, str) else entity.name
        id_to_name = self._entity_to_id_to_name.get(entity_name)
        if id_to_name is None:
            return iid

        return id_to_name.get(int(iid), iid)

    def names(self, entity: str | ods.Model.Entity, iids: list[str | int]) -> list[str | int]:
        """
        Returns a list of names corresponding to the given list of instance IDs for the specified entity.
        If the entity or any instance ID is not found, the original instance ID is returned for those entries.
        """
        entity_name = entity if isinstance(entity, str) else entity.name
        id_to_name = self._entity_to_id_to_name.get(entity_name)
        if id_to_name is None:
            return iids

        return [id_to_name.get(int(iid), iid) for iid in iids]

    def map_series(self, entity: str | ods.Model.Entity, series: pd.Series[Any]) -> pd.Series[Any]:
        """Map a Series of relation IDs to names. Returns the series unchanged if no mapping exists."""
        entity_name = entity if isinstance(entity, str) else entity.name
        id_to_name = self._entity_to_id_to_name.get(entity_name)
        if id_to_name is None:
            return series

        def _resolve(v: Any) -> Any:
            return id_to_name.get(int(v), v) if pd.notna(v) else v

        return series.map(_resolve)
