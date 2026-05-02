# Cyberia Lebanon Home Assistant integration

Custom Home Assistant integration for monitoring a Cyberia Lebanon account through the Account Management Center at `myaccount.cyberia.net.lb`.

This integration is modeled after `alfa-lb`: it creates sensors for subscription/account status, plan, expiry, and traffic usage. Cyberia's portal is an ASP.NET/SharePoint site, so the integration signs in by posting the login form with its hidden fields and then parses the authenticated account pages.

## Current status

The login flow and first residential account management page have been verified. The integration logs in, opens the first residential account with the portal's `Manage` postback, and parses plan/type, traffic usage, remaining extra traffic, balance, expiry date, and account table rows.

For unlimited plans, Cyberia may not expose a monthly total quota. In that case `Data total` is unavailable while `Data used` and `Data remaining` show the values Cyberia exposes.

## Installation

Copy `custom_components/cyberia_lb` into your Home Assistant `custom_components` directory, restart Home Assistant, then add the integration from Settings > Devices & services.

## Credentials

Use the Cyberia Account Management Center username and password, not the old subscription username unless that is also your portal login.
