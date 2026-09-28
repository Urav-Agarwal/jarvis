"""
Permission tiers for JARVIS v4.

Every tool call passes through tier_for() before execution:

    READ    observe only (battery, time, running apps, screenshots)
    LOW     open apps, volume, media, navigation — easily reversible
    MEDIUM  type/click/keyboard, create/move/copy files, drag —
            touches the world but undoable
    HIGH    delete, send messages, post, shutdown/restart, install,
            anything irreversible — ALWAYS requires spoken confirmation

Tiers come from config/permissions.yaml (tool-name overrides first,
then risk field fallback). The executor gate uses requires_confirmation()
to decide whether to queue a ConfirmationManager action; the audit log
records the tier with every decision.
"""

import os

import yaml


_DEFAULT_TIERS = {
    "READ": "READ",
    "LOW": "LOW",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
}

# Sensible defaults for tools without a config entry. Anything NOT
# listed falls back to the catalogue's risk field, then MEDIUM.
_RISK_TO_TIER = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "read": "READ",
}

_TIER_ORDER = {"READ": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


class PermissionRegistry:
    """
    Loads config/permissions.yaml (optional) and answers two
    questions for the executor gate: what tier is this tool, and does
    it need spoken confirmation this time?
    """

    def __init__(self, config_path: str | None = None):
        self.overrides = {}
        self.confirm_always = set()
        self.confirm_never = set()

        path = config_path or os.path.join(
            "config", "permissions.yaml"
        )

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

        except FileNotFoundError:
            data = {}

        except Exception:
            data = {}

        overrides = data.get("tool_tiers") or {}

        for tool_name, tier in overrides.items():
            tier = str(tier).upper().strip()

            if tier in _TIER_ORDER:
                self.overrides[str(tool_name)] = tier

        self.confirm_always.update(
            str(name)
            for name in (data.get("always_confirm") or [])
        )

        self.confirm_never.update(
            str(name)
            for name in (data.get("never_confirm") or [])
        )

    def tier_for(self, tool_name: str, risk: str = "medium") -> str:
        """Config override wins, then the catalogue risk, then MEDIUM."""

        override = self.overrides.get(tool_name)

        if override:
            return override

        return _RISK_TO_TIER.get(
            (risk or "medium").lower(), "MEDIUM"
        )

    def requires_confirmation(
        self,
        tool_name: str,
        tier: str,
        catalogue_flag: bool = False,
    ) -> bool:
        """
        HIGH always confirms. MEDIUM confirms only when the catalogue
        flags the specific tool. READ/LOW never do (unless the config
        forces it via always_confirm).
        """

        if tool_name in self.confirm_never:
            return False

        if tool_name in self.confirm_always:
            return True

        if tier == "HIGH":
            return True

        if tier == "MEDIUM":
            return bool(catalogue_flag)

        return bool(catalogue_flag and tier == "HIGH")


_DEFAULT_REGISTRY = None


def get_registry() -> PermissionRegistry:
    global _DEFAULT_REGISTRY

    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = PermissionRegistry()

    return _DEFAULT_REGISTRY


def tier_for(tool_name: str, risk: str = "medium") -> str:
    return get_registry().tier_for(tool_name, risk)


def requires_confirmation(
    tool_name: str,
    tier: str,
    catalogue_flag: bool = False,
) -> bool:
    return get_registry().requires_confirmation(
        tool_name, tier, catalogue_flag
    )
