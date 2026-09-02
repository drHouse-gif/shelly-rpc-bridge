# Third-party notices

Shelly Toolkit project code is distributed under the MIT License. It vendors no
third-party source or compiled frontend package.

The Home Assistant runtime supplies these directly used libraries:

| Project | Purpose | License |
| --- | --- | --- |
| Home Assistant Core | Integration, config entry, storage, diagnostics, repairs, services, WebSocket and panel APIs | Apache License 2.0 |
| aiohttp | HTTP and WebSocket client/server primitives, including digest authentication | Apache License 2.0 |
| Voluptuous | Runtime schemas and validation | BSD 3-Clause |

Development and CI additionally use:

| Project | Purpose | License |
| --- | --- | --- |
| pytest | Python test runner | MIT |
| pytest-homeassistant-custom-component | Home Assistant custom-integration test fixtures | MIT |
| Ruff | Python linting and formatting | MIT |
| mypy | Static type checking | MIT |
| HACS Action | HACS repository validation | MIT |
| Home Assistant hassfest action | Home Assistant metadata/manifest validation | Apache License 2.0 |

The table is an attribution summary, not a replacement for each dependency's
license text. HACS installs the integration source; dependencies continue to be
provided under their respective licenses.
