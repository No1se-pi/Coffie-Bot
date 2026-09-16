from __future__ import annotations

import runpy
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SYNC = runpy.run_path(str(ROOT / "scripts" / "sync_coffeeanddot_menu.py"), run_name="menu_sync")


def _source() -> dict:
    return SYNC["load_source"](ROOT / "configs" / "coffeeanddot-menu.json")


def test_pdf_menu_expands_to_expected_categories_and_variants() -> None:
    items = SYNC["expand_items"](_source())

    assert len(items) == 46
    assert Counter(item.category_name for item in items) == {
        "Классика": 11,
        "Чай": 1,
        "Авторский чай": 3,
        "Холодные напитки": 18,
        "Авторский кофе": 7,
        "Матча": 6,
    }
    assert len({SYNC["normalized"](item.name) for item in items}) == len(items)


def test_pdf_prices_and_sizes_are_preserved_in_minor_units() -> None:
    items = {item.name: item for item in SYNC["expand_items"](_source())}

    assert dict(items["Эспрессо"].prices) == {"36 мл": 12_000}
    assert dict(items["Капучино"].prices)["550 мл"] == 42_000
    assert dict(items["Чай листовой"].prices)["900 мл"] == 30_000
    assert dict(items["Лимонад"].prices)["900 мл"] == 70_000
    assert dict(items["Коктейль с урбечем"].prices)["550 мл"] == 80_000
    assert dict(items["Матча-латте"].prices)["450 мл"] == 42_000


def test_syrup_catalog_is_deduplicated_and_priced() -> None:
    catalog = _source()["modifier_catalog"]

    assert catalog["syrup_price"] == 40
    assert len(catalog["syrups"]) == 39
    assert len({SYNC["normalized"](name) for name in catalog["syrups"]}) == 39
    assert catalog["syrups"].count("Лаванда") == 1


def test_volume_modifier_keeps_exact_size_and_plant_milk_prices() -> None:
    source = _source()
    items = SYNC["expand_items"](source)
    synchronizer = SYNC["MenuSynchronizer"](None, source, apply=True)
    synchronizer._desired_items = items
    synchronizer.item_ids = {
        SYNC["normalized"](item.name): f"id-{index}" for index, item in enumerate(items)
    }

    group = next(
        value
        for value in synchronizer._desired_groups()
        if value["name"] == "Объём и молоко · Капучино"
    )
    options = dict(group["options_raw"])

    assert group["required"] is True
    assert options["250 мл"] == 0
    assert options["350 мл"] == 7_000
    assert options["350 мл · Кокосовое"] == 16_000
    assert options["550 мл · Банановое"] == 39_000
