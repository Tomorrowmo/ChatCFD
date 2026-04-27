"""Automated simulation quality checks."""

import numpy as np

NAME = "check"
DESCRIPTION = """自动检查仿真数据质量。检测：负密度/负压力、NaN/Inf、极端值、标量异常。
无需参数，自动扫描所有 zone 和标量。
适用：快速诊断仿真结果是否可信。"""
DEFAULTS = {}

_CHECKS = [
    {
        "patterns": ["pressure", "density", "temperature"],
        "name": "negative_value",
        "check": lambda arr: float(np.min(arr)) < 0,
        "detail": lambda name, arr: f"{name}: min={float(np.min(arr)):.4g} (should be > 0)",
        "severity": "error",
    },
    {
        "patterns": None,
        "name": "nan_inf",
        "check": lambda arr: bool(np.any(~np.isfinite(arr))),
        "detail": lambda name, arr: f"{name}: {int(np.sum(~np.isfinite(arr)))} NaN/Inf values ({np.sum(~np.isfinite(arr))/len(arr)*100:.1f}%)",
        "severity": "error",
    },
    {
        "patterns": None,
        "name": "extreme_outlier",
        "check": lambda arr: bool(np.any(np.abs(arr - np.nanmean(arr)) > 10 * np.nanstd(arr))) if np.nanstd(arr) > 0 else False,
        "detail": lambda name, arr: (
            f"{name}: {int(np.sum(np.abs(arr - np.nanmean(arr)) > 10 * np.nanstd(arr)))} extreme outliers "
            f"(> 10σ from mean={float(np.nanmean(arr)):.4g})"
        ),
        "severity": "warning",
    },
    {
        "patterns": ["mach"],
        "name": "high_mach",
        "check": lambda arr: float(np.max(arr)) > 50,
        "detail": lambda name, arr: f"{name}: max={float(np.max(arr)):.4g} (> 50, likely unphysical)",
        "severity": "warning",
    },
]


def _match_pattern(scalar_name, patterns):
    if patterns is None:
        return True
    return any(p in scalar_name.lower() for p in patterns)


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    zones = post_data.get_zones()
    if zone_name:
        zones = [zone_name] if zone_name in zones else []
    if not zones:
        return {"error": "No zones to check."}

    findings = []

    for zone in zones:
        scalars = post_data.get_scalar_names(zone)
        for scalar in scalars:
            try:
                arr = post_data.get_scalar(zone, scalar)
            except ValueError:
                continue
            if len(arr) == 0:
                continue

            for rule in _CHECKS:
                if not _match_pattern(scalar, rule["patterns"]):
                    continue
                try:
                    if rule["check"](arr):
                        findings.append({
                            "zone": zone,
                            "scalar": scalar,
                            "check": rule["name"],
                            "detail": rule["detail"](scalar, arr),
                            "severity": rule["severity"],
                        })
                except Exception:
                    pass

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    if not findings:
        summary = f"All checks passed for {len(zones)} zone(s). No issues found."
    else:
        parts = []
        if errors:
            parts.append(f"{len(errors)} error(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        detail_lines = [f"[{f['severity'].upper()}] {f['zone']}: {f['detail']}" for f in findings[:10]]
        summary = f"Found {', '.join(parts)} in {len(zones)} zone(s):\n" + "\n".join(detail_lines)

    return {
        "type": "numerical",
        "summary": summary,
        "data": {
            "zones_checked": len(zones),
            "errors": errors,
            "warnings": warnings,
            "total_issues": len(findings),
        },
        "output_files": [],
    }
