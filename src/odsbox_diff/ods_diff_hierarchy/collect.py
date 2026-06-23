import hashlib
import io
import json
import logging
import os
import sys
import zipfile
from typing import Any, cast

from odsbox.model_cache import ModelCache
import odsbox.proto.ods_pb2 as ods
import pandas as pd
from odsbox.con_i import ConI
from requests import HTTPError

from .rel_to_name import RelToName

_log = logging.getLogger(__name__)


class Collector:
    def __init__(
        self,
        con_i: ConI,
        is_null_to_nan: bool = False,
        enum_as_string: bool = True,
        cached_related_entities: list[str] | None = None,
    ) -> None:
        self._con_i = con_i
        self._mc: ModelCache = con_i.mc
        self._is_null_to_nan = is_null_to_nan
        self._enum_as_string = enum_as_string
        self.r2n: RelToName = RelToName(con_i, cached_related_entities)

    def _query_data(self, query: dict[str, Any]) -> pd.DataFrame:
        return self._con_i.query_data(
            query=query, is_null_to_nan=self._is_null_to_nan, enum_as_string=self._enum_as_string
        )

    @staticmethod
    def _print_progress_bar(
        iteration: int,
        total: int,
        prefix: str = "",
        suffix: str = "",
        decimals: int = 1,
        length: int = 50,
        fill: str = "█",
    ) -> None:
        """
        Call in a loop to create terminal progress bar
        @params:
            iteration  - Required  : current iteration (Int)
            total      - Required  : total iterations (Int)
            prefix     - Optional  : prefix string (Str)
            suffix     - Optional  : suffix string (Str)
            decimals   - Optional  : positive number of decimals in percent complete (Int)
            length     - Optional  : character length of bar (Int)
            fill       - Optional  : bar fill character (Str)
        """
        percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
        filled_length = int(length * iteration // total)
        bar = fill * filled_length + "-" * (length - filled_length)
        sys.stdout.write(f"\r{prefix} |{bar}| {percent}% {suffix}")
        sys.stdout.flush()
        # Print New Line on Complete
        if iteration == total:
            print()

    @staticmethod
    def _hash_pandas_row(row: pd.Series[Any]) -> str:
        row_string = "".join([str(item) for item in row.values])
        return hashlib.sha256(row_string.encode()).hexdigest()

    def _collect_bulk_data(
        self,
        lookup: dict[Any, Any],
        path_to_root: str,
        root_id: int,
        show_progress: bool,
    ) -> None:
        log = _log
        sub_matrix_entity = self._mc.entity_by_base_name("AoSubMatrix")
        sub_matrices = self._query_data(
            {
                sub_matrix_entity.name: {path_to_root: root_id},
                "$attributes": {"id": 1, "measurement": 1, "number_of_rows": 1},
            }
        )
        log.debug("Found %s submatrices related to your test", sub_matrices.shape[0])
        sub_matrices.columns = pd.Index(["id", "measurement", "number_of_rows"])
        local_column_entity = self._mc.entity_by_base_name("AoLocalColumn")
        exception_errors: list[str] = []
        log.debug("Load bulk data from ASAM ODS server")
        for sub_matrix_index, submatrix_row in enumerate(sub_matrices.itertuples()):
            if show_progress:
                self._print_progress_bar(sub_matrix_index + 1, sub_matrices.shape[0], "Bulk:", fill="*")
            submatrix_id = submatrix_row.id
            try:
                bulk_data = self._query_data(
                    {
                        local_column_entity.name: {"submatrix": submatrix_id},
                        "$attributes": {
                            "id": 1,
                            "generation_parameters": 1,
                            "values": 1,
                            "flags": 1,
                        },
                    }
                )
                bulk_data.columns = pd.Index(["id", "generation_parameters", "values", "flags"])
                for _, row in bulk_data.iterrows():
                    hash_value = self._hash_pandas_row(row)
                    local_column_id = row.id
                    parent_dictionary = lookup.get((local_column_entity.name, local_column_id), None)
                    if parent_dictionary is None:
                        raise ValueError("parent wasn't added")
                    parent_dictionary["_BULK_HASH"] = hash_value
            except HTTPError as e:
                error_text = f"Unable to retrieve bulk for Submatrix {submatrix_id}: {e}"
                exception_errors.append(error_text)
                sub_matrix_dictionary = lookup.get((sub_matrix_entity.name, submatrix_id), None)
                if sub_matrix_dictionary is None:
                    raise ValueError("parent wasn't added")
                sub_matrix_dictionary["_BULK_HASH_CALCULATION_ERROR"] = error_text
        log.debug("Load bulk data from ASAM ODS server finished")
        for exception_error in exception_errors:
            log.error(exception_error)

    def _get_descriptive(self, descriptive_lookup: dict[Any, Any], entity: ods.Model.Entity, id: int) -> dict[str, Any]:
        log = _log

        descriptive_lookup_key = (entity.name, id)
        cached = descriptive_lookup.get(descriptive_lookup_key, None)
        if cached is not None:
            return cast(dict[str, Any], cached)

        lookup: dict[Any, Any] = {}
        result: dict[str, Any] = {}

        jaquel_query = {entity.name: id}
        log.debug("Collect descriptive by query: %s", jaquel_query)
        tests = self._query_data(jaquel_query)

        id_entry = f"{entity.name}.{self._mc.attribute(entity, 'id').name}"
        name_entry = f"{entity.name}.{self._mc.attribute(entity, 'name').name}"

        for instance in tests.to_dict(orient="records"):
            entry_name = instance[name_entry]
            result[f"{entry_name}"] = instance
            lookup[(entity.name, instance[id_entry])] = instance

        for _name, relation in entity.relations.items():
            if relation.base_name == "children":
                self._add_children_ex(
                    lookup,
                    descriptive_lookup,
                    relation.entity_name,
                    relation.inverse_name,
                    relation.inverse_name,
                    id,
                )

        descriptive_lookup[descriptive_lookup_key] = result
        return result

    def _collect_descriptive(
        self,
        descriptive_lookup: dict[Any, Any],
        entity: ods.Model.Entity,
        instance: dict[Any, Any],
    ) -> None:
        log = _log
        for _name, relation in entity.relations.items():
            relation_entity = self._mc.entity(relation.entity_name)
            if relation_entity.base_name in [
                "AoUnitUnderTest",
                "AoTestEquipment",
                "AoTestSequence",
            ]:
                log.debug(
                    "Found descriptive %s relation at entity %s. Adding them.",
                    relation_entity.name,
                    entity.name,
                )
                entry_name = f"{entity.name}.{relation.name}"
                descriptive_id = instance.get(entry_name, None)
                if descriptive_id is not None and not pd.isna(descriptive_id) and 0 != int(descriptive_id):
                    instance[entry_name] = self._get_descriptive(
                        descriptive_lookup, relation_entity, int(descriptive_id)
                    )

    def _add_children(
        self,
        lookup: dict[Any, Any],
        descriptive_lookup: dict[Any, Any],
        entity_name: str,
        parent_relation_name: str,
        path_to_root: str,
        iid: int,
    ) -> None:
        """Query and attach all child instances of ``entity_name`` under ``iid``.

        Resolves duplicate child names by appending ``_Version:<n>`` (when a
        version attribute exists) or ``_###<index>`` as a last resort. Replaces
        ``AoLocalColumn``'s ``measurement_quantity`` ID with the MQ name to keep
        diffs stable across servers.
        """
        log = _log

        entity = self._mc.entity(entity_name)
        jaquel_query = {entity.name: {path_to_root: iid}}
        measurement_quantity_entity = None
        measurement_quantity_name_entry = None
        local_column_measurement_quantity_entry = None

        if "AoLocalColumn" == entity.base_name:
            attributes = {
                attribute.name: 1
                for _, attribute in entity.attributes.items()
                if attribute.base_name not in ["generation_parameters", "values", "flags"]
            }
            attributes.update({relation.name: 1 for _, relation in entity.relations.items() if 1 == relation.range_max})
            jaquel_query["$attributes"] = attributes
            measurement_quantity_entity = self._mc.entity_by_base_name("AoMeasurementQuantity")
            local_column_measurement_quantity_entry = (
                f"{entity.name}.{self._mc.relation_by_base_name(entity, 'measurement_quantity').name}"
            )
            measurement_quantity_name_entry = f"{measurement_quantity_entity.name}.{self._mc.attribute_by_base_name(measurement_quantity_entity, 'name').name}"

        parent_relation = self._mc.relation(entity, parent_relation_name)
        parent_entry = f"{entity.name}.{parent_relation.name}"
        if parent_relation.range_max != 1:
            # no children relation
            related_entity = self._mc.entity(parent_relation.entity_name)
            related_entity_id_attribute = self._mc.attribute_by_base_name(related_entity, "id")
            parent_entry = f"{parent_relation.entity_name}.{related_entity_id_attribute.name}"
            jaquel_query["$attributes"] = {
                "*": 1,
                f"{parent_relation.name}.{related_entity_id_attribute.name}": 1,
            }

        log.debug("Retrieve children using query: %s", jaquel_query)
        df = self._query_data(jaquel_query)

        self._replace_cached_related(entity, df)

        id_entry = f"{entity.name}.{self._mc.attribute(entity, 'id').name}"
        name_entry = f"{entity.name}.{self._mc.attribute(entity, 'name').name}"
        dict_entry_key_entry = name_entry
        version_attribute = self._mc.attribute_no_throw(entity, "version")
        version_entry = f"{entity.name}.{version_attribute.name}" if version_attribute is not None else None

        if parent_entry not in df.columns:
            raise KeyError(f"Column '{parent_entry}' not found in query result for query: {jaquel_query}")

        for parent_id, children in df.groupby(parent_entry):
            parent_dictionary = lookup.get((parent_relation.entity_name, parent_id), None)
            if parent_dictionary is None:
                raise ValueError("parent wasn't added")

            if version_entry is not None:
                # sort descending
                children.sort_values(by=version_entry, ascending=False)

            children_result = {}
            for instance_index, instance in enumerate(children.drop(columns=[parent_entry]).to_dict(orient="records")):
                instance_id = instance[id_entry]
                self._collect_descriptive(descriptive_lookup, entity, instance)
                children_entry_key = f"{instance[dict_entry_key_entry]}"
                if children_entry_key in children_result:
                    if version_entry is not None:
                        instance_version = instance[version_entry]
                        children_entry_key_with_version = f"{children_entry_key}_Version:{instance_version}"
                        if children_entry_key_with_version not in children_result:
                            children_entry_key = children_entry_key_with_version
                    if children_entry_key in children_result:
                        log.warning(
                            "Name duplicate exists for children at %s.%s(%s): %s.%s(%s)",
                            parent_relation.entity_name,
                            parent_relation.name,
                            parent_id,
                            entity.name,
                            instance_id,
                            children_entry_key,
                        )
                        children_entry_key += f"_###{instance_index}"
                if local_column_measurement_quantity_entry is not None:
                    # We Replace the AoMeasurementQuantity id by the name because the parent is submatrix here and the MQ ids will differ.
                    local_column_measurement_quantity_id = instance.get(local_column_measurement_quantity_entry)
                    if local_column_measurement_quantity_id is not None:
                        assert measurement_quantity_entity is not None
                        local_column_measurement_quantity_dict = lookup.get(
                            (
                                measurement_quantity_entity.name,
                                local_column_measurement_quantity_id,
                            )
                        )
                        if local_column_measurement_quantity_dict is not None:
                            instance[local_column_measurement_quantity_entry] = (
                                local_column_measurement_quantity_dict.get(measurement_quantity_name_entry)
                            )

                children_result[children_entry_key] = instance
                lookup[(entity.name, instance_id)] = instance

            parent_dictionary[f"{parent_relation.inverse_name}"] = children_result

    def _replace_cached_related(self, entity: ods.Model.Entity, df: pd.DataFrame) -> None:
        if df.empty:
            return

        for column in df.columns:
            if "." in column:
                _, relation_or_attribute_name = column.split(".", 1)
                rel: ods.Model.Relation | None = entity.relations.get(relation_or_attribute_name, None)
                if rel is None:
                    continue
                rel_entity = self._mc.entity_no_throw(rel.entity_name)
                if rel_entity is None:
                    continue

                df[column] = self.r2n.map_series(rel.entity_name, df[column])

    def _add_related(
        self,
        lookup: dict[Any, Any],
        descriptive_lookup: dict[Any, Any],
        entity_name: str,
        path_to_root: str,
        root_id: int,
    ) -> None:
        """Attach related ``AoParameterSet`` (and its parameters) and ``AoFile`` instances."""
        log = _log
        entity = self._mc.entity(entity_name)
        for _, relation in entity.relations.items():
            relation_entity = self._mc.entity(relation.entity_name)
            if relation_entity.base_name == "AoParameterSet":
                log.debug(
                    "Found AoParameterSet relation at entity %s. Adding instances.",
                    entity.name,
                )
                self._add_children(
                    lookup,
                    descriptive_lookup,
                    relation_entity.name,
                    relation.inverse_name,
                    f"{relation.inverse_name}.{path_to_root}",
                    root_id,
                )
                param_relation = self._mc.relation(relation_entity, "parameters")
                self._add_children(
                    lookup,
                    descriptive_lookup,
                    param_relation.entity_name,
                    param_relation.inverse_name,
                    f"{param_relation.inverse_name}.{relation.inverse_name}.{path_to_root}",
                    root_id,
                )
            elif relation_entity.base_name == "AoFile":
                log.debug("Found AoFile relation at entity %s. Adding instances.", entity.name)
                self._add_children(
                    lookup,
                    descriptive_lookup,
                    relation_entity.name,
                    relation.inverse_name,
                    f"{relation.inverse_name}.{path_to_root}",
                    root_id,
                )

    def _add_children_ex(
        self,
        lookup: dict[Any, Any],
        descriptive_lookup: dict[Any, Any],
        entity_name: str,
        parent_relation_name: str,
        path_to_root: str,
        root_id: int,
    ) -> None:
        self._add_children(
            lookup,
            descriptive_lookup,
            entity_name,
            parent_relation_name,
            path_to_root,
            root_id,
        )
        self._add_related(lookup, descriptive_lookup, entity_name, path_to_root, root_id)

    def _create_root(
        self,
        lookup: dict[Any, Any],
        descriptive_lookup: dict[Any, Any],
        entity: ods.Model.Entity,
        parent_relation_name: str,
        root_condition: int | str | dict[str, Any],
    ) -> dict[str, Any]:
        """Build the result root dict for the single root instance ``root_condition``.

        Raises:
            ValueError: If no instance with ``root_condition`` exists or if more than one
                root instance is returned.
        """
        result: dict[str, Any] = {}

        condition = (
            root_condition
            if isinstance(root_condition, int) or isinstance(root_condition, dict)
            else json.loads(root_condition)
        )

        log = _log
        log.debug("Retrieve instances of entity %s", entity.name)
        root_df = self._query_data({entity.name: condition, "$options": {"$rowlimit": 2}})
        if root_df.empty:
            raise ValueError(f"Test instance with id {root_condition} does not exist.")
        self._replace_cached_related(entity, root_df)

        id_entry = f"{entity.name}.{self._mc.attribute(entity, 'id').name}"
        parent_relation = self._mc.relation(entity, parent_relation_name)
        parent_entry = f"{entity.name}.{parent_relation.name}"
        instances = root_df.drop(columns=[parent_entry]).to_dict(orient="records")
        if 1 != len(instances):
            raise ValueError(f"there should be only one root but {len(instances)} have been found.")

        instance = instances[0]
        result[entity.name] = instance
        lookup[(entity.name, instance[id_entry])] = instance
        self._collect_descriptive(descriptive_lookup, entity, instance)
        self._add_related(lookup, descriptive_lookup, entity.name, "id", instance[id_entry])

        return result

    @staticmethod
    def _join_path(part_a: str | None, part_b: str | None) -> str | None:
        if part_a is None:
            return part_b
        if part_b is None:
            return part_a
        return f"{part_a}.{part_b}"

    def collect(
        self,
        root_entity_name: str,
        root_condition: int | str | dict[str, Any],
        calculate_bulk_hash: bool = False,
        show_progress: bool = True,
    ) -> tuple[dict[Any, Any], dict[Any, Any]]:
        """Collect a complete instance hierarchy rooted at ``root_condition``.

        Walks the ``children`` chain from the root entity, then collects related
        ``AoMeasurementQuantity``, ``AoSubMatrix`` and ``AoLocalColumn`` instances.
        Optionally hashes bulk data per ``LocalColumn`` for change detection.

        Args:
            root_entity_name: Name of the root entity. Must derive from
                ``AoSubTest`` or ``AoMeasurement``.
            root_condition: Condition to identify the root instance.
                            Can be an integer ID or a JSON string representing a complex condition.
            calculate_bulk_hash: Whether to also hash bulk LocalColumn data.
            show_progress: Show a textual progress bar during bulk hashing.

        Returns:
            A tuple ``(result, lookup)`` where ``result`` is a nested name-keyed
            hierarchy dict suitable for diffing, and ``lookup`` maps
            ``(entity_name, id)`` to the corresponding instance dict.

        Raises:
            ValueError: If the root entity is not an ``AoSubTest`` or
                ``AoMeasurement`` derivative, or if the instance does not exist.
        """
        log = _log
        lookup: dict[tuple[str, Any], Any] = {}
        descriptive_lookup: dict[tuple[str, int], Any] = {}

        parent_relation = None
        entity = self._mc.entity(root_entity_name)
        if "AoSubTest" == entity.base_name:
            parent_relation = self._mc.relation(entity, "parent_test")
        elif "AoMeasurement" == entity.base_name:
            parent_relation = self._mc.relation(entity, "test")
        else:
            raise ValueError("Only entities derived from AoSubTest or AoMeasurement can be used as root.")

        result = self._create_root(lookup, descriptive_lookup, entity, parent_relation.name, root_condition)

        id_entry = f"{entity.name}.{self._mc.attribute(entity, 'id').name}"
        resolved_root_id: int = result[entity.name][id_entry]

        instances_to_collect: list[tuple[str, str, str | None]] = []

        path_to_root_instance: str | None = None

        current_entity = entity
        current_children_relation = self._mc.relation_no_throw(current_entity, "children")
        while current_children_relation is not None:
            path_to_root_instance = self._join_path(current_children_relation.inverse_name, path_to_root_instance)
            instances_to_collect.append(
                (
                    current_children_relation.entity_name,
                    current_children_relation.inverse_name,
                    path_to_root_instance,
                )
            )
            current_entity = self._mc.entity(current_children_relation.entity_name)
            current_children_relation = self._mc.relation_no_throw(current_entity, "children")

        instances_to_collect += [
            (
                self._mc.entity_by_base_name("AoMeasurementQuantity").name,
                "measurement",
                self._join_path("measurement", path_to_root_instance),
            ),
            (
                self._mc.entity_by_base_name("AoSubMatrix").name,
                "measurement",
                self._join_path("measurement", path_to_root_instance),
            ),
            (
                self._mc.entity_by_base_name("AoLocalColumn").name,
                "submatrix",
                self._join_path("submatrix.measurement", path_to_root_instance),
            ),
        ]
        log.debug("Collecting: %s", instances_to_collect)
        for item in instances_to_collect:
            log.info("Retrieve instances of entity %s", item[0])
            item_path = item[2]
            assert item_path is not None
            self._add_children_ex(
                lookup,
                descriptive_lookup,
                entity_name=item[0],
                parent_relation_name=item[1],
                path_to_root=item_path,
                root_id=resolved_root_id,
            )

        if calculate_bulk_hash:
            log.info("Retrieve bulk data")
            bulk_path = self._join_path("measurement", path_to_root_instance)
            assert bulk_path is not None
            self._collect_bulk_data(
                lookup,
                path_to_root=bulk_path,
                root_id=resolved_root_id,
                show_progress=show_progress,
            )

        log.info(
            "Collected %s instances for %s with id %s",
            len(lookup),
            entity.name,
            resolved_root_id,
        )

        return (result, lookup)


def collect(
    con_i: ConI,
    root_entity_name: str,
    root_condition: int | str | dict[str, Any],
    *,
    calculate_bulk_hash: bool = False,
    show_progress: bool = True,
    is_null_to_nan: bool = True,
    enum_as_string: bool = True,
    cached_related_entities: list[str] | None = None,
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    return Collector(
        con_i,
        is_null_to_nan=is_null_to_nan,
        enum_as_string=enum_as_string,
        cached_related_entities=cached_related_entities,
    ).collect(root_entity_name, root_condition, calculate_bulk_hash, show_progress)


def save_collect_results(
    file_path: str,
    data: dict[Any, Any],
    additional_info_for_zip: str | dict[Any, Any] | None = None,
    additional_files_for_zip: list[str] | None = None,
) -> None:
    """Persist a collected hierarchy dict to a ``.json`` or ``.zip`` file.

    For ``.zip`` outputs, ``additional_info_for_zip`` (str or dict) is written as
    ``info.txt`` and any existing files in ``additional_files_for_zip`` are added
    by basename.
    """
    _log.debug("Dump dictionary to file: %s", file_path)
    ext = os.path.splitext(file_path)[1].lower()

    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    if ext == ".zip":
        json_str = json.dumps(data, indent=1, ensure_ascii=False)
        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            _log.debug("Writing JSON to zip file.")
            zf.writestr("result.json", json_str)
            if additional_info_for_zip:
                zf.writestr(
                    "info.txt",
                    (
                        additional_info_for_zip
                        if isinstance(additional_info_for_zip, str)
                        else json.dumps(additional_info_for_zip, indent=2, ensure_ascii=False)
                    ),
                )
            if additional_files_for_zip:
                for additional_file_for_zip in additional_files_for_zip:
                    if os.path.exists(additional_file_for_zip):
                        zf.write(
                            additional_file_for_zip,
                            arcname=os.path.basename(additional_file_for_zip),
                        )
    else:
        # Save as plain JSON
        with open(file_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, indent=1, ensure_ascii=False)


def load_collect_results(file_path: str) -> dict[Any, Any]:
    """Load a collected hierarchy dict previously written by ``save_collect_results``."""
    _log.info("Read dictionary from file: %s", file_path)
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".zip":
        with zipfile.ZipFile(file_path, "r") as zf:
            _log.debug("Reading JSON from zip file.")
            with zf.open("result.json") as json_file:
                _log.debug("Extract zip content.")
                data = json.load(io.TextIOWrapper(json_file, encoding="utf-8"))
    else:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    return cast(dict[Any, Any], data)
