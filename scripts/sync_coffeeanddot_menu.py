#!/usr/bin/env python3
"""Synchronize one venue menu with a reviewed JSON source through the admin API.

The command is deliberately dry-run by default. It never deletes content: rows
missing from the source are archived through the same audited API used by the
admin panel. The password is read from ``COFFIE_ADMIN_PASSWORD`` so it cannot
leak into shell history or process arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "coffeeanddot-menu.json"


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("ё", "е").split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--base-url", default="https://coffeeanddot.ru/api/v1")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--apply", action="store_true", help="Apply the printed plan")
    return parser.parse_args()


class ApiError(RuntimeError):
    pass


class AdminApi:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def login(self, username: str, password: str) -> None:
        response = self.request(
            "POST", "/auth/password", {"username": username, "password": password}
        )
        self.token = str(response["access_token"])

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": "menu-sync/1"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{method} {path}: {exc.reason}") from exc
        return {} if not raw else json.loads(raw)

    def list_all(self, path: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        page = 1
        result: list[dict[str, Any]] = []
        while True:
            response = self.request("GET", f"{path}{separator}page={page}&page_size=100")
            result.extend(response["items"])
            if len(result) >= int(response.get("total", len(result))):
                return result
            page += 1


@dataclass
class DesiredItem:
    category_name: str
    name: str
    base_name: str
    volume: str
    price_minor: int
    description: str | None
    sort_order: int
    prices: tuple[tuple[str, int], ...]
    tags: frozenset[str]
    flavors: tuple[str, ...]
    flavor_label: str
    aliases: tuple[str, ...]


@dataclass
class Report:
    actions: list[str] = field(default_factory=list)
    categories_created: int = 0
    categories_updated: int = 0
    categories_archived: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_restored: int = 0
    items_archived: int = 0
    modifier_groups_created: int = 0
    modifier_groups_updated: int = 0
    modifier_groups_restored: int = 0
    modifier_groups_archived: int = 0

    def add(self, message: str) -> None:
        self.actions.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if key != "actions"}


def load_source(path: Path) -> dict[str, Any]:
    source = json.loads(path.read_text(encoding="utf-8"))
    category_names = [normalized(value["name"]) for value in source["categories"]]
    if len(category_names) != len(set(category_names)):
        raise ValueError("Source contains duplicate categories")
    syrups = source["modifier_catalog"]["syrups"]
    if len({normalized(value) for value in syrups}) != len(syrups):
        raise ValueError("Source contains duplicate syrup options")
    return source


def expand_items(source: dict[str, Any]) -> list[DesiredItem]:
    result: list[DesiredItem] = []
    seen: set[str] = set()
    for category in source["categories"]:
        for position, row in enumerate(category["items"]):
            flavors = tuple(row.get("flavors", []))
            description = row.get("description")
            if flavors:
                flavor_text = f"{row.get('flavor_label', 'Вкус')}: {', '.join(flavors)}."
                description = f"{description} {flavor_text}".strip() if description else flavor_text
            prices = tuple((volume, int(rubles) * 100) for volume, rubles in row["prices"].items())
            name = row["name"]
            key = normalized(name)
            if key in seen:
                raise ValueError(f"Source contains duplicate menu item: {name}")
            seen.add(key)
            aliases = list(row.get("aliases", []))
            # The previous production menu represented sizes as separate cards.
            # Treat those names as aliases so the smallest-size row is adopted
            # and the remaining rows are archived without breaking history.
            aliases.extend(f"{name} {volume}" for volume, _price in prices)
            volumes = [volume.removesuffix(" мл") for volume, _price in prices]
            volume_label = prices[0][0] if len(prices) == 1 else f"{' / '.join(volumes)} мл"
            result.append(
                DesiredItem(
                    category_name=category["name"],
                    name=name,
                    base_name=name,
                    volume=volume_label,
                    price_minor=prices[0][1],
                    description=description,
                    sort_order=position * 10,
                    prices=prices,
                    tags=frozenset(row.get("tags", [])),
                    flavors=flavors,
                    flavor_label=row.get("flavor_label", "Вкус"),
                    aliases=tuple(aliases),
                )
            )
    return result


def changed_fields(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in desired.items() if current.get(key) != value}


def find_item(
    desired: DesiredItem,
    by_name: dict[str, list[dict[str, Any]]],
    already_used: set[str],
) -> dict[str, Any] | None:
    candidate_names = [desired.name, *desired.aliases]
    for candidate_name in candidate_names:
        candidates = [
            value
            for value in by_name.get(normalized(candidate_name), [])
            if value["id"] not in already_used
        ]
        if len(candidates) == 1:
            return candidates[0]
    return None


def option_payload(
    options: list[tuple[str, int]], existing: dict[str, Any] | None
) -> list[dict[str, Any]]:
    current = {normalized(value["name"]): value for value in (existing or {}).get("options", [])}
    result = []
    for index, (name, price_minor) in enumerate(options):
        previous = current.get(normalized(name))
        result.append(
            {
                "id": previous["id"] if previous else None,
                "name": name,
                "price_delta_minor": price_minor,
                "allows_quantity": False,
                "max_quantity": 1,
                "enabled": True,
                "sort_order": index,
            }
        )
    return result


def comparable_group(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_id": value["venue_id"],
        "name": value["name"],
        "description": value.get("description"),
        "min_selections": value["min_selections"],
        "max_selections": value["max_selections"],
        "required": value["required"],
        "enabled": value["enabled"],
        "sort_order": value["sort_order"],
        "item_ids": sorted(value["item_ids"]),
        "options": [
            {
                "name": option["name"],
                "price_delta_minor": option["price_delta_minor"],
                "allows_quantity": option["allows_quantity"],
                "max_quantity": option["max_quantity"],
                "enabled": option["enabled"],
                "sort_order": option["sort_order"],
            }
            for option in value["options"]
        ],
    }


class MenuSynchronizer:
    def __init__(self, api: AdminApi, source: dict[str, Any], *, apply: bool) -> None:
        self.api = api
        self.source = source
        self.apply = apply
        self.report = Report()
        self.venue: dict[str, Any] | None = None
        self.category_ids: dict[str, str] = {}
        self.item_ids: dict[str, str] = {}

    def run(self) -> Report:
        venues = self.api.list_all("/admin/venues?include_archived=true")
        self.venue = next(
            (value for value in venues if value["slug"] == self.source["venue_slug"]),
            None,
        )
        if not self.venue:
            raise RuntimeError(f"Venue {self.source['venue_slug']!r} was not found")
        self._sync_categories()
        self._sync_items()
        self._sync_modifier_groups()
        self._archive_removed_items_and_categories()
        return self.report

    @property
    def venue_id(self) -> str:
        assert self.venue is not None
        return str(self.venue["id"])

    def _sync_categories(self) -> None:
        current = [
            value
            for value in self.api.list_all("/admin/menu/categories?include_archived=true")
            if value["venue_id"] == self.venue_id
        ]
        active = {
            normalized(value["name"]): value for value in current if value["archived_at"] is None
        }
        for category in self.source["categories"]:
            key = normalized(category["name"])
            desired = {
                "name": category["name"],
                "description": None,
                "sort_order": category["sort_order"],
                "visible": True,
            }
            existing = active.get(key)
            if existing:
                updates = changed_fields(existing, desired)
                self.category_ids[key] = existing["id"]
                if updates:
                    self.report.categories_updated += 1
                    self.report.add(f"UPDATE category {category['name']}: {sorted(updates)}")
                    if self.apply:
                        self.api.request(
                            "PATCH", f"/admin/menu/categories/{existing['id']}", updates
                        )
                continue
            self.report.categories_created += 1
            self.report.add(f"CREATE category {category['name']}")
            if self.apply:
                created = self.api.request(
                    "POST",
                    "/admin/menu/categories",
                    {"venue_id": self.venue_id, **desired},
                )
                self.category_ids[key] = created["id"]

    def _sync_items(self) -> None:
        desired_items = expand_items(self.source)
        current = [
            value
            for value in self.api.list_all("/admin/menu/items?include_archived=true")
            if value["venue_id"] == self.venue_id
        ]
        by_name: dict[str, list[dict[str, Any]]] = {}
        for value in current:
            by_name.setdefault(normalized(value["name"]), []).append(value)
        used: set[str] = set()

        for desired in desired_items:
            category_id = self.category_ids.get(normalized(desired.category_name))
            if self.apply and category_id is None:
                raise RuntimeError(f"Category id missing for {desired.category_name}")
            existing = find_item(desired, by_name, used)
            payload = {
                "category_id": category_id,
                "name": desired.name,
                "description": desired.description,
                "price_minor": desired.price_minor,
                "volume": desired.volume,
                "available": True,
                "visible": True,
                "sort_order": desired.sort_order,
            }
            if existing:
                used.add(existing["id"])
                if existing["archived_at"] is not None:
                    self.report.items_restored += 1
                    self.report.add(f"RESTORE item {existing['name']}")
                    if self.apply:
                        existing = self.api.request(
                            "POST", f"/admin/menu/items/{existing['id']}/restore"
                        )
                comparable_payload = {
                    key: value for key, value in payload.items() if value is not None
                }
                updates = changed_fields(existing, comparable_payload)
                if updates:
                    self.report.items_updated += 1
                    self.report.add(f"UPDATE item {existing['name']} -> {desired.name}")
                    if self.apply:
                        existing = self.api.request(
                            "PATCH", f"/admin/menu/items/{existing['id']}", updates
                        )
                self.item_ids[normalized(desired.name)] = existing["id"]
                continue

            self.report.items_created += 1
            self.report.add(f"CREATE item {desired.name}: {desired.price_minor // 100} ₽")
            if self.apply:
                created = self.api.request(
                    "POST",
                    "/admin/menu/items",
                    {
                        **payload,
                        "old_price_minor": None,
                        "points_price": None,
                        "composition": None,
                        "labels": [],
                    },
                )
                self.item_ids[normalized(desired.name)] = created["id"]

        self._current_items = current
        self._used_item_ids = used
        self._desired_items = desired_items

    def _desired_groups(self) -> list[dict[str, Any]]:
        catalog = self.source["modifier_catalog"]
        desired_items = self._desired_items
        groups: list[dict[str, Any]] = []

        for index, item in enumerate(desired_items):
            if len(item.prices) == 1 and "milk" not in item.tags:
                continue
            base_price = item.prices[0][1]
            options: list[tuple[str, int]] = []
            for volume, price_minor in item.prices:
                options.append((volume, price_minor - base_price))
                if "milk" in item.tags:
                    milk_price = int(catalog["plant_milk_prices"][volume]) * 100
                    options.extend(
                        (
                            f"{volume} · {milk_name}",
                            price_minor - base_price + milk_price,
                        )
                        for milk_name in catalog["plant_milk"]
                    )
            groups.append(
                {
                    "name": (
                        f"Объём и молоко · {item.base_name}"
                        if "milk" in item.tags
                        else f"Объём · {item.base_name}"
                    ),
                    "description": (
                        "Выберите объём и обычное либо растительное молоко."
                        if "milk" in item.tags
                        else "Выберите объём напитка."
                    ),
                    "min_selections": 1,
                    "max_selections": 1,
                    "required": True,
                    "enabled": True,
                    "sort_order": index,
                    "item_ids": [self.item_ids[normalized(item.name)]],
                    "options_raw": options,
                }
            )

        groups.extend(
            [
                {
                    "name": "Сироп",
                    "description": "Один сироп на выбор.",
                    "min_selections": 0,
                    "max_selections": 1,
                    "required": False,
                    "enabled": True,
                    "sort_order": 10,
                    "item_ids": [
                        self.item_ids[normalized(item.name)]
                        for item in desired_items
                        if "syrup" in item.tags
                    ],
                    "options_raw": [
                        (name, int(catalog["syrup_price"]) * 100) for name in catalog["syrups"]
                    ],
                },
                {
                    "name": "Дополнительно",
                    "description": "Дополнительные опции для кофейных напитков.",
                    "min_selections": 0,
                    "max_selections": len(catalog["extra"]),
                    "required": False,
                    "enabled": True,
                    "sort_order": 20,
                    "item_ids": [
                        self.item_ids[normalized(item.name)]
                        for item in desired_items
                        if "extra" in item.tags
                    ],
                    "options_raw": [
                        (name, int(catalog["extra_price"]) * 100) for name in catalog["extra"]
                    ],
                },
            ]
        )

        flavor_index = 100
        flavor_sets: dict[str, tuple[tuple[str, ...], str, list[str]]] = {}
        for item in desired_items:
            if not item.flavors:
                continue
            key = normalized(item.base_name)
            previous = flavor_sets.setdefault(key, (item.flavors, item.flavor_label, []))
            previous[2].append(self.item_ids[normalized(item.name)])
        for base_key, (flavors, label, item_ids) in flavor_sets.items():
            base_name = next(
                item.base_name for item in desired_items if normalized(item.base_name) == base_key
            )
            groups.append(
                {
                    "name": f"{label} · {base_name}",
                    "description": f"Обязательный выбор для «{base_name}».",
                    "min_selections": 1,
                    "max_selections": 1,
                    "required": True,
                    "enabled": True,
                    "sort_order": flavor_index,
                    "item_ids": item_ids,
                    "options_raw": [(name, 0) for name in flavors],
                }
            )
            flavor_index += 1
        return groups

    def _sync_modifier_groups(self) -> None:
        if not self.apply:
            current = self.api.request(
                "GET",
                f"/admin/pricing/modifier-groups?venue_id={self.venue_id}&include_archived=true",
            )["items"]
            all_item_ids_known = len(self.item_ids) == len(self._desired_items)
            desired_groups = self._desired_groups() if all_item_ids_known else []
            desired_names = {normalized(group["name"]) for group in desired_groups} or {
                normalized(name)
                for name in {
                    "Сироп",
                    "Дополнительно",
                    *{
                        (
                            f"Объём и молоко · {item.base_name}"
                            if "milk" in item.tags
                            else f"Объём · {item.base_name}"
                        )
                        for item in self._desired_items
                        if len(item.prices) > 1 or "milk" in item.tags
                    },
                    *{
                        f"{item.flavor_label} · {item.base_name}"
                        for item in self._desired_items
                        if item.flavors
                    },
                }
            }
            active_by_name = {
                normalized(value["name"]): value
                for value in current
                if value["archived_at"] is None
            }
            if all_item_ids_known:
                for group in desired_groups:
                    key = normalized(group["name"])
                    existing = active_by_name.get(key)
                    payload = {
                        "venue_id": self.venue_id,
                        "name": group["name"],
                        "description": group["description"],
                        "min_selections": group["min_selections"],
                        "max_selections": group["max_selections"],
                        "required": group["required"],
                        "enabled": group["enabled"],
                        "sort_order": group["sort_order"],
                        "item_ids": sorted(group["item_ids"]),
                        "options": option_payload(group["options_raw"], existing),
                    }
                    if existing is None:
                        self.report.modifier_groups_created += 1
                        self.report.add(f"CREATE modifier group {group['name']}")
                    elif comparable_group(existing) != comparable_group(payload):
                        self.report.modifier_groups_updated += 1
                        self.report.add(f"UPDATE modifier group {group['name']}")
            else:
                # Before the first apply, planned item ids do not exist yet.
                # Report group upserts conservatively without guessing links.
                for key in sorted(desired_names):
                    existing = active_by_name.get(key)
                    if existing:
                        self.report.modifier_groups_updated += 1
                        self.report.add(f"UPSERT modifier group {existing['name']}")
                    else:
                        self.report.modifier_groups_created += 1
                        self.report.add(f"CREATE modifier group {key}")
            for value in current:
                if value["archived_at"] is None and normalized(value["name"]) not in desired_names:
                    self.report.modifier_groups_archived += 1
                    self.report.add(f"ARCHIVE modifier group {value['name']}")
            return

        current = self.api.request(
            "GET",
            f"/admin/pricing/modifier-groups?venue_id={self.venue_id}&include_archived=true",
        )["items"]
        by_name: dict[str, list[dict[str, Any]]] = {}
        for value in current:
            by_name.setdefault(normalized(value["name"]), []).append(value)
        desired_names: set[str] = set()

        for group in self._desired_groups():
            key = normalized(group["name"])
            desired_names.add(key)
            candidates = by_name.get(key, [])
            existing = next((value for value in candidates if value["archived_at"] is None), None)
            if existing is None:
                existing = next(iter(candidates), None)
            if existing and existing["archived_at"] is not None:
                self.report.modifier_groups_restored += 1
                self.report.add(f"RESTORE modifier group {group['name']}")
                existing = self.api.request(
                    "POST", f"/admin/pricing/modifier-groups/{existing['id']}/restore"
                )
            payload = {
                "venue_id": self.venue_id,
                "name": group["name"],
                "description": group["description"],
                "min_selections": group["min_selections"],
                "max_selections": group["max_selections"],
                "required": group["required"],
                "enabled": group["enabled"],
                "sort_order": group["sort_order"],
                "item_ids": sorted(group["item_ids"]),
                "options": option_payload(group["options_raw"], existing),
            }
            if existing:
                if comparable_group(existing) != comparable_group(payload):
                    self.report.modifier_groups_updated += 1
                    self.report.add(f"UPDATE modifier group {group['name']}")
                    self.api.request(
                        "PUT",
                        f"/admin/pricing/modifier-groups/{existing['id']}",
                        payload,
                    )
            else:
                self.report.modifier_groups_created += 1
                self.report.add(f"CREATE modifier group {group['name']}")
                self.api.request("POST", "/admin/pricing/modifier-groups", payload)

        for value in current:
            if value["archived_at"] is None and normalized(value["name"]) not in desired_names:
                self.report.modifier_groups_archived += 1
                self.report.add(f"ARCHIVE modifier group {value['name']}")
                self.api.request("POST", f"/admin/pricing/modifier-groups/{value['id']}/archive")

    def _archive_removed_items_and_categories(self) -> None:
        for value in self._current_items:
            if value["archived_at"] is not None or value["id"] in self._used_item_ids:
                continue
            # Aliases are only candidates for selecting the single row that survives.
            # Every other active row must be archived, including former size variants
            # and accidental duplicates with the same normalized product name.
            self.report.items_archived += 1
            self.report.add(f"ARCHIVE item {value['name']}")
            if self.apply:
                self.api.request("POST", f"/admin/menu/items/{value['id']}/archive")

        current_categories = [
            value
            for value in self.api.list_all("/admin/menu/categories?include_archived=true")
            if value["venue_id"] == self.venue_id and value["archived_at"] is None
        ]
        desired_categories = {normalized(value["name"]) for value in self.source["categories"]}
        for value in current_categories:
            if normalized(value["name"]) in desired_categories:
                continue
            self.report.categories_archived += 1
            self.report.add(f"ARCHIVE category {value['name']}")
            if self.apply:
                self.api.request("POST", f"/admin/menu/categories/{value['id']}/hide")


def main() -> int:
    # Windows consoles often default to cp1251, which cannot print the ruble
    # sign used in the dry-run report.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    password = os.environ.get("COFFIE_ADMIN_PASSWORD")
    if not password:
        print("COFFIE_ADMIN_PASSWORD is required", file=sys.stderr)
        return 2
    source = load_source(args.config)
    api = AdminApi(args.base_url)
    api.login(args.username, password)
    synchronizer = MenuSynchronizer(api, source, apply=args.apply)
    report = synchronizer.run()
    print("APPLY" if args.apply else "DRY-RUN")
    for action in report.actions:
        print(f"- {action}")
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print(f"desired_categories={len(source['categories'])}")
    print(f"desired_items={len(expand_items(source))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
