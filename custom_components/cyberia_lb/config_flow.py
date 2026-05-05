"""Config flow for Cyberia Lebanon."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CyberiaApiError, CyberiaAuthError, CyberiaClient
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_PASSWORD_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class CyberiaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cyberia Lebanon."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            data, errors = await self._async_validate_credentials(
                username, password
            )
            if not errors:
                unique = data.get("username") or username
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                title = data.get("account_name") or unique
                return self.async_create_entry(
                    title=f"Cyberia {title}",
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual reconfiguration from the existing config entry."""
        entry = self._get_reconfigure_entry()
        return await self._async_step_update_entry(
            "reconfigure",
            entry.data[CONF_USERNAME],
            user_input,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        return await self._async_step_update_entry(
            "reauth_confirm",
            entry.data[CONF_USERNAME],
            user_input,
        )

    async def _async_step_update_entry(
        self,
        step_id: str,
        current_username: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Validate credentials and update the current config entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            data, errors = await self._async_validate_credentials(
                current_username, password
            )
            if not errors:
                entry = (
                    self._get_reconfigure_entry()
                    if step_id == "reconfigure"
                    else self._get_reauth_entry()
                )
                unique = data.get("username") or current_username
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_mismatch()
                title = data.get("account_name") or unique
                self.hass.config_entries.async_update_entry(
                    entry, title=f"Cyberia {title}"
                )
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=STEP_PASSWORD_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"username": current_username},
        )

    async def _async_validate_credentials(
        self, username: str, password: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Validate submitted Cyberia credentials."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)
        client = CyberiaClient(session, username, password)
        try:
            data = await client.async_validate()
        except CyberiaAuthError:
            errors["base"] = "invalid_auth"
            data = {}
        except CyberiaApiError:
            errors["base"] = "cannot_connect"
            data = {}
        except Exception:  # noqa: BLE001
            errors["base"] = "unknown"
            data = {}
        return data, errors
