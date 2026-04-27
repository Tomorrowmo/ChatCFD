"""Physical variable mapping: O(1) lookup from raw solver variable names
to standardised physical quantities.

Loads ``post_engine/config/physical_mapping.json`` (generated in P0) and
exposes query helpers used by parsers, the engine, and MCP tools.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class PhysicalMapping:
    """O(1) lookup from (solver_id, raw_name) to physical quantity metadata."""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), "config", "physical_mapping.json"
            )
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        self._solver_profiles: dict[str, dict] = data.get("solver_profiles", {})
        self._standard_quantities: dict[str, dict] = data.get("standard_quantities", {})
        self._value_ranges: dict[str, dict] = data.get("value_ranges", {})
        self._ambiguity_table: list[dict] = data.get("ambiguity_table", [])

        # ---- build O(1) indices ------------------------------------------------
        # (solver_id, raw_name) -> mapping entry  (with solver_id baked in)
        self._solver_lookup: dict[tuple[str, str], dict] = {}
        # raw_name -> list of {solver_id, ...entry}  (for solver-less queries)
        self._alias_to_standard: dict[str, list[dict]] = {}

        for solver_id, profile in self._solver_profiles.items():
            for entry in profile.get("mappings", []):
                raw = entry["raw_name"]
                enriched = {**entry, "solver_id": solver_id}
                self._solver_lookup[(solver_id, raw)] = enriched

                self._alias_to_standard.setdefault(raw, []).append(enriched)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, raw_name: str, solver_id: str | None = None) -> dict | None:
        """Core query: *raw_name* + optional *solver_id* -> mapping entry.

        Returns
        -------
        dict
            Keys: ``physical_name``, ``conversion``, ``confidence``,
            ``ambiguity_risk``, ``notes``, ``solver_id``, ``type``,
            ``vector_components``.
        dict with ``ambiguous=True``
            If *solver_id* is ``None`` and the raw name maps to multiple
            distinct physical quantities.
        None
            If the raw name is unknown.
        """
        if solver_id is not None:
            entry = self._solver_lookup.get((solver_id, raw_name))
            return dict(entry) if entry else None

        candidates = self._alias_to_standard.get(raw_name)
        if not candidates:
            return None

        # De-duplicate by physical_name – if every candidate points to the
        # same physical quantity the result is unambiguous.
        unique_physical = {c["physical_name"] for c in candidates}
        if len(unique_physical) == 1:
            # Return the first candidate (arbitrary but deterministic).
            return dict(candidates[0])

        return {
            "ambiguous": True,
            "candidates": [dict(c) for c in candidates],
        }

    def disambiguate_by_range(
        self, raw_name: str, min_val: float, max_val: float
    ) -> dict | None:
        """Use value-range heuristics for LOW-confidence / ambiguous variables.

        For each candidate physical quantity that the *raw_name* could map to,
        check whether ``[min_val, max_val]`` overlaps the expected range
        defined in ``value_ranges``.  Return the best match or ``None``.
        """
        candidates = self._alias_to_standard.get(raw_name)
        if not candidates:
            return None

        unique_physical = {c["physical_name"] for c in candidates if c["physical_name"]}
        best_entry: dict | None = None
        best_overlap: float = -1.0

        for phys_name in unique_physical:
            vr = self._value_ranges.get(phys_name)
            if vr is None:
                continue
            r_min = vr["min"]
            r_max = vr["max"]

            # Compute overlap ratio
            overlap_lo = max(min_val, r_min)
            overlap_hi = min(max_val, r_max)
            if overlap_hi < overlap_lo:
                continue  # no overlap
            overlap = overlap_hi - overlap_lo
            span = max(max_val - min_val, r_max - r_min, 1e-12)
            ratio = overlap / span

            if ratio > best_overlap:
                best_overlap = ratio
                # Pick the first candidate that maps to this physical name
                for c in candidates:
                    if c["physical_name"] == phys_name:
                        best_entry = dict(c)
                        break

        return best_entry

    def get_standard_info(self, physical_name: str) -> dict | None:
        """Return ``{display_name, unit, type, notes}`` for a standard
        physical quantity, or ``None``.

        Falls back to ``value_ranges`` when a quantity is declared only
        there — coordinate_x/y/z live there in the current mapping file
        but still carry display_name + unit.
        """
        info = self._standard_quantities.get(physical_name)
        if info:
            return dict(info)
        vr = self._value_ranges.get(physical_name)
        if vr and (vr.get("display_name") or vr.get("unit")):
            return {
                k: vr[k]
                for k in ("display_name", "unit", "type", "notes")
                if k in vr
            }
        return None

    def get_all_raw_names(self, solver_id: str) -> list[str]:
        """List every known raw variable name for *solver_id*."""
        profile = self._solver_profiles.get(solver_id)
        if not profile:
            return []
        return [e["raw_name"] for e in profile.get("mappings", [])]


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
_instance: PhysicalMapping | None = None


def get_mapping() -> PhysicalMapping:
    """Return (and lazily create) the module-level singleton."""
    global _instance
    if _instance is None:
        _instance = PhysicalMapping()
    return _instance
