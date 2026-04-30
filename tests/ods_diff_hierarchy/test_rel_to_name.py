"""Tests for RelToName using a mocked ConI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from odsbox_diff.ods_diff_hierarchy.rel_to_name import RelToName


def _make_con_i(entity_name: str, id_to_name: dict[int, str]) -> MagicMock:
    """Build a ConI mock that exposes ``mc.entity_no_throw`` and ``query``."""
    con_i = MagicMock()
    con_i.con_i_url = "http://test"
    entity_obj = SimpleNamespace(name=entity_name)
    con_i.mc.entity_no_throw.side_effect = lambda n: entity_obj if n == entity_name else None
    df = pd.DataFrame({"id": list(id_to_name.keys()), "name": list(id_to_name.values())})
    con_i.query.return_value = df
    return con_i


class TestRelToName:
    def test_none_entities_yields_empty_cache(self) -> None:
        con_i = MagicMock()
        r = RelToName(con_i, None)
        assert r.name("AoUnit", 5) == 5

    def test_resolves_known_id(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter", 2: "second"})
        r = RelToName(con_i, ["AoUnit"])
        assert r.name("AoUnit", 1) == "meter"
        assert r.name("AoUnit", 2) == "second"

    def test_returns_id_for_unknown_id(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter"})
        r = RelToName(con_i, ["AoUnit"])
        assert r.name("AoUnit", 999) == 999

    def test_returns_id_for_uncached_entity(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter"})
        r = RelToName(con_i, ["AoUnit"])
        assert r.name("AoOther", 1) == 1

    def test_unknown_entity_logs_warning(self, caplog: object) -> None:
        con_i = MagicMock()
        con_i.con_i_url = "http://test"
        con_i.mc.entity_no_throw.return_value = None
        r = RelToName(con_i, ["Missing"])
        # Cache should be empty
        assert r.name("Missing", 1) == 1

    def test_names_list(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter", 2: "second"})
        r = RelToName(con_i, ["AoUnit"])
        assert r.names("AoUnit", [1, 2, 999]) == ["meter", "second", 999]

    def test_names_uncached_returns_input(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter"})
        r = RelToName(con_i, ["AoUnit"])
        assert r.names("AoOther", [1, 2]) == [1, 2]

    def test_map_series(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter", 2: "second"})
        r = RelToName(con_i, ["AoUnit"])
        s = pd.Series([1, 2, 999, None])
        out = r.map_series("AoUnit", s)
        assert out.iloc[0] == "meter"
        assert out.iloc[1] == "second"
        assert out.iloc[2] == 999
        assert pd.isna(out.iloc[3])

    def test_map_series_uncached_returns_unchanged(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter"})
        r = RelToName(con_i, ["AoUnit"])
        s = pd.Series([1, 2])
        out = r.map_series("AoOther", s)
        assert out is s

    def test_accepts_entity_object(self) -> None:
        con_i = _make_con_i("AoUnit", {1: "meter"})
        r = RelToName(con_i, ["AoUnit"])
        entity = SimpleNamespace(name="AoUnit")
        assert r.name(entity, 1) == "meter"  # type: ignore[arg-type]
