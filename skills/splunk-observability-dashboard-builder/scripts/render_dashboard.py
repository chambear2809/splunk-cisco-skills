#!/usr/bin/env python3
"""Render Splunk Observability Cloud classic dashboard API payloads."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


CHART_TYPE_ALIASES = {
    "time_series": "TimeSeriesChart",
    "timeseries": "TimeSeriesChart",
    "timeserieschart": "TimeSeriesChart",
    "timeseries_chart": "TimeSeriesChart",
    "timeSeries": "TimeSeriesChart",
    "TimeSeries": "TimeSeriesChart",
    "TimeSeriesChart": "TimeSeriesChart",
    "single_value": "SingleValue",
    "singlevalue": "SingleValue",
    "SingleValue": "SingleValue",
    "list": "List",
    "List": "List",
    "table": "TableChart",
    "table_chart": "TableChart",
    "TableChart": "TableChart",
    "heatmap": "Heatmap",
    "Heatmap": "Heatmap",
    "text": "Text",
    "markdown": "Text",
    "Text": "Text",
}

SUPPORTED_CLASSIC_CHART_TYPES = {"TimeSeriesChart", "SingleValue", "List", "TableChart", "Heatmap", "Text"}

UNVERIFIED_CLASSIC_CHART_ALIASES = {
    "pie": "pie/donut charts",
    "piechart": "pie/donut charts",
    "pie_chart": "pie/donut charts",
    "donut": "pie/donut charts",
    "donutchart": "pie/donut charts",
    "donut_chart": "pie/donut charts",
    "event": "event feed charts",
    "events": "event feed charts",
    "eventfeed": "event feed charts",
    "eventfeedchart": "event feed charts",
    "event_feed": "event feed charts",
    "event_feed_chart": "event feed charts",
}

PLOT_TYPE_ALIASES = {
    "line": "LineChart",
    "linechart": "LineChart",
    "LineChart": "LineChart",
    "area": "AreaChart",
    "areachart": "AreaChart",
    "AreaChart": "AreaChart",
    "column": "ColumnChart",
    "bar": "ColumnChart",
    "columnchart": "ColumnChart",
    "ColumnChart": "ColumnChart",
    "histogram": "Histogram",
    "Histogram": "Histogram",
}

VALUE_UNITS = {
    "Bit",
    "Kilobit",
    "Megabit",
    "Gigabit",
    "Terabit",
    "Petabit",
    "Exabit",
    "Zettabit",
    "Yottabit",
    "Byte",
    "Kibibyte",
    "Mebibyte",
    "Gibibyte",
    "Tebibyte",
    "Pebibyte",
    "Exbibyte",
    "Zebibyte",
    "Yobibyte",
    "Nanosecond",
    "Microsecond",
    "Millisecond",
    "Second",
    "Minute",
    "Hour",
    "Day",
    "Week",
}

DIRECT_SECRET_KEYS = {
    "token",
    "access_token",
    "api_token",
    "sf_token",
    "x_sf_token",
    "password",
    "secret",
    "client_secret",
    "api_key",
}


class SpecError(Exception):
    """Raised when a dashboard spec cannot be rendered safely."""


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SpecError("PyYAML is required to read YAML specs; use JSON or install PyYAML.") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SpecError("Spec root must be a mapping/object.")
    return data


def normalize_chart_type(value: Any) -> str:
    raw = str(value or "TimeSeriesChart")
    key = raw.replace("-", "_").replace(" ", "_")
    return CHART_TYPE_ALIASES.get(raw) or CHART_TYPE_ALIASES.get(key) or raw


def unverified_classic_chart_type(value: Any) -> str:
    raw = str(value or "")
    normalized = raw.replace("-", "_").replace(" ", "_")
    compact = normalized.replace("_", "").lower()
    return UNVERIFIED_CLASSIC_CHART_ALIASES.get(normalized.lower()) or UNVERIFIED_CLASSIC_CHART_ALIASES.get(compact, "")


def normalize_plot_type(value: Any) -> str:
    raw = str(value or "LineChart")
    key = raw.replace("-", "_").replace(" ", "_")
    return PLOT_TYPE_ALIASES.get(raw) or PLOT_TYPE_ALIASES.get(key) or raw


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "chart"


def get_layout(chart: dict[str, Any]) -> dict[str, int]:
    layout = chart.get("layout") if isinstance(chart.get("layout"), dict) else {}
    return {
        "row": int(layout.get("row", chart.get("row", 0))),
        "column": int(layout.get("column", chart.get("column", 0))),
        "width": int(layout.get("width", chart.get("width", 6))),
        "height": int(layout.get("height", chart.get("height", 1))),
    }


def extract_publish_labels(program: str) -> list[str]:
    labels: list[str] = []
    for match in re.finditer(r"\.publish\s*\((?P<args>[^)]*)\)", program, flags=re.DOTALL):
        args = match.group("args")
        label_match = re.search(r"\blabel\s*=\s*(['\"])(?P<label>.*?)\1", args, flags=re.DOTALL)
        if label_match:
            labels.append(label_match.group("label"))
            continue
        positional_match = re.search(r"^\s*(['\"])(?P<label>.*?)\1", args, flags=re.DOTALL)
        if positional_match:
            labels.append(positional_match.group("label"))
    return labels


def walk_secret_keys(value: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            key_lower = key_text.lower().replace("-", "_")
            if key_lower in DIRECT_SECRET_KEYS and child not in ("", None):
                errors.append(f"{child_path} must not contain a secret value; use --token-file for live API operations.")
            if key_lower.endswith("_token") and not key_lower.endswith("_token_file") and child not in ("", None):
                errors.append(f"{child_path} looks like a token value; use --token-file for live API operations.")
            errors.extend(walk_secret_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(walk_secret_keys(child, f"{path}[{index}]"))
    return errors


def validate_spec(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    mode = str(spec.get("mode", "classic-api"))
    if mode not in {"classic-api", "modern-ui-advisory", "dashboard-studio-advisory"}:
        errors.append("mode must be classic-api, modern-ui-advisory, or dashboard-studio-advisory.")
    if mode != "classic-api":
        warnings.append(f"{mode} is advisory only; no native Observability API payloads will be rendered.")

    for key in ("sections", "subsections", "section_tabs", "logs_charts", "service_maps"):
        if key in spec and mode == "classic-api":
            errors.append(f"{key} is a modern-dashboard-only feature and cannot be rendered by the classic API.")

    errors.extend(walk_secret_keys(spec))

    if mode != "classic-api":
        dashboard = spec.get("dashboard")
        charts = spec.get("charts")
        if dashboard is not None and not isinstance(dashboard, dict):
            errors.append("dashboard must be a mapping when present.")
        if charts is not None and not isinstance(charts, list):
            errors.append("charts must be a list when present.")
        return errors, warnings

    dashboard_group = spec.get("dashboard_group")
    dashboard = spec.get("dashboard")
    charts = spec.get("charts")
    if not isinstance(dashboard_group, dict):
        errors.append("dashboard_group must be a mapping with name or id.")
    elif not dashboard_group.get("id") and not dashboard_group.get("name"):
        errors.append("dashboard_group requires either id or name.")
    if not isinstance(dashboard, dict):
        errors.append("dashboard must be a mapping with at least name.")
    elif not dashboard.get("name"):
        errors.append("dashboard.name is required.")
    if not isinstance(charts, list) or not charts:
        errors.append("charts must be a non-empty list.")

    seen_cells: dict[tuple[int, int], str] = {}
    seen_ids: set[str] = set()
    if isinstance(charts, list):
        for index, chart in enumerate(charts):
            if not isinstance(chart, dict):
                errors.append(f"charts[{index}] must be a mapping.")
                continue
            if not chart.get("name"):
                errors.append(f"charts[{index}].name is required.")
            name = str(chart.get("name") or f"chart-{index + 1}")
            chart_id = str(chart.get("id") or slug(name))
            if chart_id in seen_ids:
                errors.append(f"Duplicate chart id: {chart_id}")
            seen_ids.add(chart_id)

            chart_type = normalize_chart_type(chart.get("type"))
            if chart_type not in SUPPORTED_CLASSIC_CHART_TYPES:
                unverified_type = unverified_classic_chart_type(chart.get("type"))
                if unverified_type:
                    errors.append(
                        f"{chart_id}: {unverified_type} are documented product chart types, but this "
                        "renderer does not have a verified classic /v2/chart schema for them. "
                        "Use mode: modern-ui-advisory or represent the need with metric/text charts."
                    )
                else:
                    errors.append(f"{chart_id}: unsupported chart type {chart.get('type')!r}.")
            plot_type = normalize_plot_type(chart.get("plot_type"))
            if chart_type == "TimeSeriesChart" and plot_type not in {"LineChart", "AreaChart", "ColumnChart", "Histogram"}:
                errors.append(f"{chart_id}: unsupported plot_type {chart.get('plot_type')!r}.")
            unit = chart.get("unit") or chart.get("valueUnit")
            if unit and str(unit) not in VALUE_UNITS:
                warnings.append(f"{chart_id}: unit {unit!r} is not in the documented valueUnit enum.")

            if chart_type == "Text":
                if not chart.get("markdown") and not chart.get("text"):
                    errors.append(f"{chart_id}: Text charts require markdown or text.")
            else:
                program = str(chart.get("program_text") or chart.get("programText") or "")
                if not program.strip():
                    errors.append(f"{chart_id}: non-text charts require program_text.")
                elif not re.search(r"(^|[.\s])publish\s*\(", program):
                    errors.append(f"{chart_id}: program_text must publish at least one stream with publish().")
                publish_labels = extract_publish_labels(program)
                if chart.get("publish_label_options") and publish_labels:
                    valid_labels = set(publish_labels)
                    for option_index, option in enumerate(chart["publish_label_options"]):
                        if not isinstance(option, dict):
                            errors.append(f"{chart_id}: publish_label_options[{option_index}] must be a mapping.")
                            continue
                        option_label = str(option.get("label", ""))
                        if option_label and option_label not in valid_labels:
                            errors.append(
                                f"{chart_id}: publish_label_options[{option_index}].label "
                                f"{option_label!r} does not match any SignalFlow publish label."
                            )
                if (
                    (chart.get("unit") or chart.get("value_prefix") or chart.get("value_suffix"))
                    and not chart.get("publish_label_options")
                    and not chart.get("publish_label")
                    and len(publish_labels) != 1
                ):
                    errors.append(
                        f"{chart_id}: unit/value formatting without publish_label_options requires exactly "
                        "one SignalFlow publish label or an explicit publish_label."
                    )

            try:
                layout = get_layout(chart)
            except (TypeError, ValueError):
                errors.append(f"{chart_id}: layout values must be integers.")
                continue
            if layout["column"] < 0 or layout["column"] > 11:
                errors.append(f"{chart_id}: column must be between 0 and 11.")
            if layout["width"] < 1 or layout["width"] > 12:
                errors.append(f"{chart_id}: width must be between 1 and 12.")
            if layout["column"] + layout["width"] > 12:
                errors.append(f"{chart_id}: column + width must not exceed 12.")
            if layout["row"] < 0 or layout["height"] < 1:
                errors.append(f"{chart_id}: row must be >= 0 and height must be >= 1.")
            for row in range(layout["row"], layout["row"] + layout["height"]):
                for column in range(layout["column"], layout["column"] + layout["width"]):
                    cell = (row, column)
                    if cell in seen_cells:
                        errors.append(f"{chart_id}: layout overlaps {seen_cells[cell]} at row {row}, column {column}.")
                    else:
                        seen_cells[cell] = chart_id

    return errors, warnings


def normalize_time(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if not isinstance(value, dict):
        raise SpecError("chart time must be a mapping.")
    if value.get("type") == "absolute":
        return {"type": "absolute", "start": int(value["start"]), "end": int(value["end"])}
    range_ms = value.get("range_ms", value.get("range", 3600000))
    return {"type": "relative", "range": int(range_ms)}


def prepare_output_dir(output_dir: Path, clean: bool = True) -> None:
    resolved = output_dir.resolve()
    protected = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if resolved in protected:
        raise SpecError(f"Refusing to use protected output directory: {output_dir}")

    if output_dir.exists():
        if not output_dir.is_dir():
            raise SpecError(f"Output path exists and is not a directory: {output_dir}")
        children = list(output_dir.iterdir())
        if clean and children:
            marker = output_dir / "metadata.json"
            is_prior_render = False
            if marker.is_file():
                try:
                    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
                    is_prior_render = (
                        marker_payload.get("mode") == "classic-api"
                        and isinstance(marker_payload.get("rendered_files"), list)
                        and "apply-plan.json" in marker_payload["rendered_files"]
                    )
                except (OSError, json.JSONDecodeError):
                    is_prior_render = False
            if not is_prior_render:
                raise SpecError(
                    f"Refusing to clean non-rendered output directory: {output_dir}. "
                    "Choose an empty directory or a prior dashboard render directory."
                )
            shutil.rmtree(output_dir)
    (output_dir / "charts").mkdir(parents=True, exist_ok=True)


def chart_payload(chart: dict[str, Any]) -> dict[str, Any]:
    chart_type = normalize_chart_type(chart.get("type"))
    payload: dict[str, Any] = {
        "name": chart["name"],
        "description": chart.get("description", ""),
    }
    if chart.get("tags"):
        payload["tags"] = chart["tags"]
    if chart.get("customProperties"):
        payload["customProperties"] = chart["customProperties"]

    if chart_type == "Text":
        payload["options"] = {
            "type": "Text",
            "markdown": chart.get("markdown", chart.get("text", "")),
        }
        return payload

    options: dict[str, Any] = {
        "type": chart_type,
        "includeZero": bool(chart.get("include_zero", chart.get("includeZero", False))),
        "showEventLines": bool(chart.get("show_event_lines", chart.get("showEventLines", False))),
        "unitPrefix": chart.get("unit_prefix", chart.get("unitPrefix", "Metric")),
    }
    if chart_type == "TimeSeriesChart":
        options["defaultPlotType"] = normalize_plot_type(chart.get("plot_type"))
        options["lineChartOptions"] = {"showDataMarkers": bool(chart.get("show_data_markers", False))}
        options["areaChartOptions"] = {"showDataMarkers": bool(chart.get("show_data_markers", False))}
        options["stacked"] = bool(chart.get("stacked", False))
    if chart.get("y_axis_label") or chart.get("y_min") is not None or chart.get("y_max") is not None:
        options["axes"] = [
            {
                "label": chart.get("y_axis_label", ""),
                "min": chart.get("y_min"),
                "max": chart.get("y_max"),
                "lowWatermark": chart.get("low_watermark"),
                "lowWatermarkLabel": chart.get("low_watermark_label"),
                "highWatermark": chart.get("high_watermark"),
                "highWatermarkLabel": chart.get("high_watermark_label"),
            },
            {"label": "", "min": None, "max": None},
        ]
    time_options = normalize_time(chart.get("time"))
    if time_options:
        options["time"] = time_options
    if chart.get("publish_label_options"):
        options["publishLabelOptions"] = chart["publish_label_options"]
    elif chart.get("unit") or chart.get("value_prefix") or chart.get("value_suffix"):
        publish_labels = extract_publish_labels(str(chart.get("program_text", chart.get("programText", ""))))
        publish_label = chart.get("publish_label") or (publish_labels[0] if len(publish_labels) == 1 else chart.get("name"))
        options["publishLabelOptions"] = [
            {
                "label": publish_label,
                "displayName": chart.get("display_name", chart.get("name")),
                "valueUnit": chart.get("unit"),
                "valuePrefix": chart.get("value_prefix"),
                "valueSuffix": chart.get("value_suffix"),
                "yAxis": int(chart.get("y_axis", 0)),
            }
        ]
    for passthrough in (
        "colorBy",
        "colorRange",
        "colorScale",
        "colorScale2",
        "groupBy",
        "groupBySort",
        "legendOptions",
        "onChartLegendOptions",
        "programOptions",
        "refreshInterval",
        "secondaryVisualization",
        "showSparkLine",
        "sortBy",
        "sortDirection",
        "sortProperty",
        "timeStampHidden",
    ):
        if passthrough in chart:
            options[passthrough] = chart[passthrough]

    payload["programText"] = chart.get("program_text", chart.get("programText"))
    payload["options"] = options
    return payload


def dashboard_payload(spec: dict[str, Any], chart_keys: list[str]) -> dict[str, Any]:
    dashboard = spec["dashboard"]
    charts = spec["charts"]
    payload: dict[str, Any] = {
        "name": dashboard["name"],
        "description": dashboard.get("description", ""),
        "groupId": spec.get("dashboard_group", {}).get("id") or "${dashboard_group_id}",
        "charts": [],
    }
    if dashboard.get("chart_density"):
        payload["chartDensity"] = dashboard["chart_density"]
    for key in ("filters", "eventOverlays", "selectedEventOverlays", "maxDelayOverride", "tags", "customProperties"):
        if key in dashboard:
            payload[key] = dashboard[key]
    for chart, key in zip(charts, chart_keys):
        layout = get_layout(chart)
        payload["charts"].append(
            {
                "chartId": f"${{chart:{key}}}",
                "row": layout["row"],
                "column": layout["column"],
                "width": layout["width"],
                "height": layout["height"],
            }
        )
    return payload


def render(spec: dict[str, Any], output_dir: Path, clean: bool = True) -> dict[str, Any]:
    errors, warnings = validate_spec(spec)
    if errors:
        raise SpecError("\n".join(errors))
    if spec.get("mode", "classic-api") != "classic-api":
        raise SpecError("Advisory modes do not render classic API payloads.")

    prepare_output_dir(output_dir, clean=clean)

    chart_keys: list[str] = []
    chart_plan: list[dict[str, str]] = []
    for index, chart in enumerate(spec["charts"], start=1):
        key = str(chart.get("id") or slug(chart["name"]))
        chart_keys.append(key)
        filename = f"{index:02d}-{slug(key)}.json"
        payload = chart_payload(chart)
        path = output_dir / "charts" / filename
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        chart_plan.append(
            {
                "key": key,
                "id": str(
                    chart.get("chart_id")
                    or chart.get("chartId")
                    or chart.get("observability_id")
                    or chart.get("api_id")
                    or ""
                ),
                "payload_file": f"charts/{filename}",
                "name": payload["name"],
            }
        )

    group = spec["dashboard_group"]
    group_payload = {
        "name": group.get("name", ""),
        "description": group.get("description", ""),
    }
    if group.get("customProperties"):
        group_payload["customProperties"] = group["customProperties"]
    (output_dir / "dashboardgroup.json").write_text(json.dumps(group_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    dashboard = dashboard_payload(spec, chart_keys)
    (output_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    plan = {
        "api_version": spec.get("api_version"),
        "mode": "classic-api",
        "realm": spec.get("realm", ""),
        "dashboard_group": {
            "id": group.get("id", ""),
            "payload_file": "dashboardgroup.json",
            "name": group.get("name", ""),
        },
        "charts": chart_plan,
        "dashboard": {
            "id": str(spec["dashboard"].get("id", "")),
            "payload_file": "dashboard.json",
            "name": spec["dashboard"]["name"],
        },
        "warnings": warnings,
    }
    (output_dir / "apply-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata = {
        "mode": "classic-api",
        "rendered_files": ["dashboardgroup.json", "dashboard.json", "apply-plan.json"] + [item["payload_file"] for item in chart_plan],
        "warnings": warnings,
        "coverage_note": "Classic Observability API payloads only. Modern dashboard sections, logs charts, and service maps are advisory until a public API is verified.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("splunk-observability-dashboard-rendered"))
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    try:
        spec = load_structured(args.spec)
        errors, warnings = validate_spec(spec)
        if errors:
            raise SpecError("\n".join(errors))
        if args.validate_only:
            result = {"ok": True, "warnings": warnings}
        else:
            result = render(spec, args.output_dir)
        if args.json_output:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if warnings:
                for warning in warnings:
                    print(f"WARNING: {warning}")
            if args.validate_only:
                print("Dashboard spec passed validation.")
            else:
                print(f"Rendered Splunk Observability dashboard payloads to {args.output_dir}")
        return 0
    except (OSError, json.JSONDecodeError, SpecError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
