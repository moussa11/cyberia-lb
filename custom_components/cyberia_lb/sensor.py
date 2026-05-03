"""Sensors for Cyberia Lebanon."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import CyberiaCoordinator


@dataclass(frozen=True, kw_only=True)
class CyberiaSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[CyberiaSensorEntityDescription, ...] = (
    CyberiaSensorEntityDescription(
        key="account_count",
        translation_key="account",
        icon="mdi:account",
        value_fn=lambda d: d.get("account_username"),
        attrs_fn=lambda d: {
            "account_name": d.get("account_name"),
            "accounts": d.get("accounts") or [],
        },
    ),
    CyberiaSensorEntityDescription(
        key="data_used",
        translation_key="data_used",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("data_used_mb"),
    ),
    CyberiaSensorEntityDescription(
        key="data_total",
        translation_key="data_total",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("data_total_mb"),
    ),
    CyberiaSensorEntityDescription(
        key="data_remaining",
        translation_key="data_remaining",
        icon="mdi:download-network-outline",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("data_remaining_extra_mb"),
    ),
    CyberiaSensorEntityDescription(
        key="plan",
        translation_key="plan",
        icon="mdi:web",
        value_fn=lambda d: d.get("plan_name"),
        attrs_fn=lambda d: {
            "details": d.get("details") or {},
            "raw_summary": d.get("raw_text"),
        },
    ),
    CyberiaSensorEntityDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:cash",
        value_fn=lambda d: d.get("balance_raw"),
    ),
    CyberiaSensorEntityDescription(
        key="validity",
        translation_key="validity",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.get("validity"),
        attrs_fn=lambda d: {"raw": d.get("validity_raw")},
    ),
    CyberiaSensorEntityDescription(
        key="days_until_expiry",
        translation_key="days_until_expiry",
        icon="mdi:calendar-end",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("days_until_expiry"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyberiaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CyberiaSensor(coordinator, entry, description) for description in SENSORS
    )


class CyberiaSensor(CoordinatorEntity[CyberiaCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description: CyberiaSensorEntityDescription

    def __init__(
        self,
        coordinator: CyberiaCoordinator,
        entry: ConfigEntry,
        description: CyberiaSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=f"Cyberia {(coordinator.data or {}).get('account_name') or entry.title.removeprefix('Cyberia ')}",
            model=(coordinator.data or {}).get("plan_name"),
            configuration_url=BASE_CONFIGURATION_URL,
        )

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


BASE_CONFIGURATION_URL = "https://myaccount.cyberia.net.lb"
