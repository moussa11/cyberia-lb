"""The Cyberia Lebanon integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CyberiaApiError, CyberiaAuthError, CyberiaClient
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import CyberiaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = CyberiaClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await client.async_validate()
    except CyberiaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CyberiaApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = CyberiaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    account_name = (coordinator.data or {}).get("account_name")
    if account_name and entry.title != f"Cyberia {account_name}":
        hass.config_entries.async_update_entry(entry, title=f"Cyberia {account_name}")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
