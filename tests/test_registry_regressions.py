#!/usr/bin/env python3
"""Regression tests for app_registry.json and deployment role matrices."""

import json
from collections import Counter

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase


# Skill directories under skills/ that intentionally have no entry in
# skill_topologies. Currently empty: every on-disk skill should appear.
SKILL_TOPOLOGY_EXEMPTIONS: set[str] = set()

SPLUNKBASE_APP_COVERAGE_IDS = {
    "263",
    "1747",
    "1761",
    "1809",
    "1841",
    "2731",
    "2881",
    "2882",
    "2883",
    "2890",
    "3088",
    "3110",
    "3411",
    "3435",
    "3449",
    "3471",
    "4147",
    "4607",
    "4882",
    "4992",
    "5234",
    "5238",
    "5247",
    "5391",
    "5558",
    "5580",
    "6361",
    "6785",
    "6872",
    "6999",
    "7000",
    "7180",
    "7214",
    "7245",
    "7404",
    "7416",
    "7417",
    "7538",
    "7539",
    "7557",
    "7569",
    "7719",
    "7777",
    "7828",
    "8365",
    "8485",
    "8566",
    "8704",
}


def _on_disk_skill_dirs() -> set[str]:
    skills_root = REPO_ROOT / "skills"
    out: set[str] = set()
    for entry in skills_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == "shared":
            continue
        if (entry / "SKILL.md").is_file():
            out.add(entry.name)
    return out


class RegistryRegressionTests(ShellScriptRegressionBase):
    def test_enterprise_networking_registry_declares_companion_ta_dependency(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        enterprise_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7539"
        )
        enhanced_netflow_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "6872"
        )

        self.assertEqual(enterprise_entry["app_name"], "cisco-catalyst-app")
        self.assertEqual(enterprise_entry.get("install_requires"), ["7538"])
        self.assertEqual(enhanced_netflow_entry["skill"], "cisco-catalyst-enhanced-netflow-setup")
        self.assertEqual(enhanced_netflow_entry["app_name"], "splunk_app_stream_ipfix_cisco_hsl")
        self.assertIn(
            "cisco-catalyst-enhanced-netflow-add-on-for-splunk_*",
            enhanced_netflow_entry.get("package_patterns", []),
        )


    def test_app_registry_declares_deployment_roles_and_complete_role_support(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = [
            "search-tier",
            "indexer",
            "heavy-forwarder",
            "universal-forwarder",
            "external-collector",
        ]
        allowed_values = {"required", "supported", "none"}

        self.assertEqual(registry.get("deployment_roles"), expected_roles)

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                role_support = app.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(sorted(role_support.keys()), sorted(expected_roles))
                self.assertTrue(set(role_support.values()).issubset(allowed_values))


    def test_app_registry_declares_capabilities_for_every_app(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_capabilities = {
            "needs_custom_rest",
            "needs_search_time_objects",
            "needs_kvstore",
            "needs_python_runtime",
            "needs_packet_capture",
            "uf_safe",
        }

        apps_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                capabilities = app.get("capabilities")
                self.assertIsInstance(capabilities, dict)
                self.assertEqual(set(capabilities.keys()), expected_capabilities)
                self.assertTrue(all(isinstance(value, bool) for value in capabilities.values()))

        self.assertEqual(
            apps_by_id["7538"]["capabilities"],
            {
                "needs_custom_rest": True,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": True,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )
        self.assertEqual(
            apps_by_id["5238"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": True,
                "uf_safe": True,
            },
        )
        self.assertEqual(
            apps_by_id["5234"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": True,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )


    def test_skill_topologies_cover_registry_skills_and_special_cases(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = set(registry["deployment_roles"])
        allowed_values = {"required", "supported", "none"}
        skill_topologies = {
            entry["skill"]: entry
            for entry in registry.get("skill_topologies", [])
        }

        for app_skill in {app["skill"] for app in registry.get("apps", [])}:
            self.assertIn(app_skill, skill_topologies)

        self.assertIn("cisco-product-setup", skill_topologies)
        self.assertIn("splunk-connect-for-syslog-setup", skill_topologies)
        self.assertIn("splunk-connect-for-snmp-setup", skill_topologies)
        self.assertIn("splunk-agent-management-setup", skill_topologies)
        self.assertIn("splunk-universal-forwarder-setup", skill_topologies)
        self.assertIn("splunk-workload-management-setup", skill_topologies)
        self.assertIn("splunk-hec-service-setup", skill_topologies)
        self.assertIn("splunk-federated-search-setup", skill_topologies)
        self.assertIn("splunk-index-lifecycle-smartstore-setup", skill_topologies)
        self.assertIn("splunk-monitoring-console-setup", skill_topologies)
        self.assertIn("splunk-enterprise-kubernetes-setup", skill_topologies)
        self.assertIn("splunk-observability-otel-collector-setup", skill_topologies)
        self.assertIn("splunk-observability-dashboard-builder", skill_topologies)
        self.assertIn("splunk-observability-native-ops", skill_topologies)
        self.assertIn("splunk-app-install", skill_topologies)

        for skill, topology in skill_topologies.items():
            with self.subTest(skill=skill):
                role_support = topology.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(set(role_support.keys()), expected_roles)
                self.assertTrue(set(role_support.values()).issubset(allowed_values))
                self.assertTrue(set(topology.get("cloud_pairing", [])).issubset(expected_roles))

        sc4s = skill_topologies["splunk-connect-for-syslog-setup"]
        self.assertEqual(sc4s["role_support"]["external-collector"], "required")
        sc4snmp = skill_topologies["splunk-connect-for-snmp-setup"]
        self.assertEqual(sc4snmp["role_support"]["external-collector"], "required")
        observability_otel = skill_topologies["splunk-observability-otel-collector-setup"]
        self.assertEqual(observability_otel["role_support"]["external-collector"], "required")
        self.assertEqual(observability_otel["cloud_pairing"], ["external-collector"])
        observability_dashboards = skill_topologies["splunk-observability-dashboard-builder"]
        self.assertTrue(
            all(value == "none" for value in observability_dashboards["role_support"].values())
        )
        observability_native_ops = skill_topologies["splunk-observability-native-ops"]
        self.assertTrue(
            all(value == "none" for value in observability_native_ops["role_support"].values())
        )
        enterprise_k8s = skill_topologies["splunk-enterprise-kubernetes-setup"]
        self.assertEqual(enterprise_k8s["role_support"]["external-collector"], "none")
        self.assertEqual(enterprise_k8s["cloud_pairing"], [])
        agent_management = skill_topologies["splunk-agent-management-setup"]
        self.assertEqual(agent_management["role_support"]["universal-forwarder"], "supported")
        universal_forwarder = skill_topologies["splunk-universal-forwarder-setup"]
        self.assertEqual(universal_forwarder["role_support"]["universal-forwarder"], "required")
        self.assertEqual(universal_forwarder["cloud_pairing"], ["universal-forwarder"])
        workload_management = skill_topologies["splunk-workload-management-setup"]
        self.assertEqual(workload_management["role_support"]["indexer"], "supported")
        self.assertEqual(workload_management["role_support"]["heavy-forwarder"], "none")
        hec_service = skill_topologies["splunk-hec-service-setup"]
        self.assertEqual(hec_service["role_support"]["heavy-forwarder"], "supported")
        otlp = skill_topologies["splunk-connect-for-otlp-setup"]
        self.assertEqual(otlp["role_support"]["search-tier"], "supported")
        self.assertEqual(otlp["role_support"]["heavy-forwarder"], "supported")
        self.assertEqual(otlp["role_support"]["external-collector"], "supported")
        federated_search = skill_topologies["splunk-federated-search-setup"]
        self.assertEqual(federated_search["role_support"]["search-tier"], "required")
        smartstore = skill_topologies["splunk-index-lifecycle-smartstore-setup"]
        self.assertEqual(smartstore["role_support"]["indexer"], "required")
        monitoring_console = skill_topologies["splunk-monitoring-console-setup"]
        self.assertEqual(monitoring_console["role_support"]["search-tier"], "required")


    def test_role_matrix_keeps_search_tier_only_and_collector_defaults_explicit(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        entries_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }
        self.assertEqual(
            entries_by_id["7539"]["role_support"],
            {
                "search-tier": "required",
                "indexer": "none",
                "heavy-forwarder": "none",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )

        collector_ids = ["7538", "7777", "7404", "5558", "7828", "3471", "5580", "7719"]
        for app_id in collector_ids:
            with self.subTest(app_id=app_id):
                role_support = entries_by_id[app_id]["role_support"]
                self.assertEqual(role_support["search-tier"], "supported")
                self.assertEqual(role_support["heavy-forwarder"], "supported")
                self.assertEqual(role_support["indexer"], "none")
                self.assertEqual(role_support["universal-forwarder"], "none")


    def test_cisco_security_registry_entries_are_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        security_cloud_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7404"
        )
        secure_access_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "5558"
        )
        secure_access_addon_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7569"
        )

        self.assertEqual(security_cloud_entry["skill"], "cisco-security-cloud-setup")
        self.assertEqual(security_cloud_entry["app_name"], "CiscoSecurityCloud")
        self.assertIn("cisco-security-cloud_*", security_cloud_entry.get("package_patterns", []))

        self.assertEqual(secure_access_entry["skill"], "cisco-secure-access-setup")
        self.assertEqual(secure_access_entry["app_name"], "cisco-cloud-security")
        self.assertIn(
            "cisco-secure-access-app-for-splunk_*",
            secure_access_entry.get("package_patterns", []),
        )
        self.assertEqual(secure_access_addon_entry["skill"], "cisco-secure-access-setup")
        self.assertEqual(secure_access_addon_entry["app_name"], "TA-cisco-cloud-security-addon")
        self.assertIn(
            "cisco-secure-access-add-on-for-splunk_*",
            secure_access_addon_entry.get("package_patterns", []),
        )

    def test_public_cisco_first_class_registry_entries_are_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        apps_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }

        expected = {
            "8365": ("cisco-webex-setup", "ta_cisco_webex_add_on_for_splunk", "webex-add-on-for-splunk_*"),
            "4992": ("cisco-webex-setup", "cisco_webex_meetings_app_for_splunk", "webex-app-for-splunk_*"),
            "2731": ("cisco-ucs-ta-setup", "Splunk_TA_cisco-ucs", "splunk-add-on-for-cisco-ucs_*"),
            "1761": ("cisco-secure-email-web-gateway-setup", "Splunk_TA_cisco-esa", "splunk-add-on-for-cisco-esa_*"),
            "1747": ("cisco-secure-email-web-gateway-setup", "Splunk_TA_cisco-wsa", "splunk-add-on-for-cisco-wsa_*"),
            "7557": (
                "cisco-talos-intelligence-setup",
                "Splunk_TA_Talos_Intelligence",
                "cisco-talos-intelligence-for-enterprise-security-cloud_*",
            ),
        }

        for app_id, (skill, app_name, package_pattern) in expected.items():
            with self.subTest(app_id=app_id):
                entry = apps_by_id[app_id]
                self.assertEqual(entry["skill"], skill)
                self.assertEqual(entry["app_name"], app_name)
                self.assertIn(package_pattern, entry.get("package_patterns", []))

        talos_entry = apps_by_id["7557"]
        self.assertEqual(talos_entry["role_support"]["indexer"], "supported")
        self.assertTrue(talos_entry["capabilities"]["needs_custom_rest"])
        self.assertTrue(talos_entry["capabilities"]["needs_python_runtime"])

    def test_scan_registry_entry_is_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "8566"
        )

        self.assertEqual(entry["skill"], "cisco-scan-setup")
        self.assertEqual(entry["app_name"], "splunk-cisco-app-navigator")
        self.assertIn("splunk-cisco-app-navigator-*", entry.get("package_patterns", []))
        self.assertEqual(entry["role_support"]["search-tier"], "required")

    def test_content_library_registry_entry_is_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        content_library_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "5391"
        )

        self.assertEqual(content_library_entry["skill"], "splunk-itsi-config")
        self.assertEqual(content_library_entry["app_name"], "DA-ITSI-ContentLibrary")
        self.assertEqual(content_library_entry.get("install_requires"), ["1841"])
        self.assertIn("splunk-app-for-content-packs_*", content_library_entry.get("package_patterns", []))

    def test_app_registry_splunkbase_ids_are_unique(self):
        """Two registry entries must not share the same Splunkbase ID.

        Many tests look up apps via the dict comprehension
        ``{app["splunkbase_id"]: app}``; duplicate IDs would silently shadow
        each other and weaken the asserts. Empty IDs are allowed only when
        marked ``"N/A"`` (e.g. private packages).
        """
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        all_ids = [
            app.get("splunkbase_id", "")
            for app in registry.get("apps", [])
        ]
        # Filter out the documented "no public ID" sentinel and empty IDs;
        # the other registry tests cover the presence rules separately.
        numeric_ids = [sb_id for sb_id in all_ids if sb_id and sb_id != "N/A"]
        duplicates = [sb_id for sb_id, count in Counter(numeric_ids).items() if count > 1]
        self.assertEqual(
            duplicates,
            [],
            msg=f"Duplicate Splunkbase IDs in app_registry.json: {duplicates}",
        )

    def test_skill_topologies_have_no_orphans_against_filesystem(self):
        """Every on-disk skills/<name>/SKILL.md must appear in skill_topologies.

        Catches the case where a contributor adds a new skill directory but
        forgets to register it in app_registry.json, which would otherwise
        only surface when generated docs go out of date.
        """
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        topology_skills = {
            entry["skill"] for entry in registry.get("skill_topologies", [])
        }
        on_disk = _on_disk_skill_dirs() - SKILL_TOPOLOGY_EXEMPTIONS

        missing = sorted(on_disk - topology_skills)
        self.assertEqual(
            missing,
            [],
            msg=(
                "Skills present on disk but missing from app_registry.json "
                f"skill_topologies: {missing}. Add a topology entry or, "
                "if intentional, list the skill in SKILL_TOPOLOGY_EXEMPTIONS "
                "in tests/test_registry_regressions.py with a justification."
            ),
        )

    def test_skill_topologies_have_no_dangling_entries_against_filesystem(self):
        """Every skill_topologies entry must point at an on-disk skill dir.

        Catches stale topology rows after a skill is renamed or removed.
        """
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        topology_skills = {
            entry["skill"] for entry in registry.get("skill_topologies", [])
        }
        on_disk = _on_disk_skill_dirs()

        dangling = sorted(topology_skills - on_disk)
        self.assertEqual(
            dangling,
            [],
            msg=(
                "skill_topologies references skills that have no "
                f"corresponding skills/<name>/SKILL.md on disk: {dangling}."
            ),
        )

    def test_app_registry_app_skills_resolve_to_known_skill_dirs(self):
        """Every apps[].skill must point at an on-disk skill dir."""
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        on_disk = _on_disk_skill_dirs()
        bad = sorted(
            {
                app["skill"]
                for app in registry.get("apps", [])
                if app.get("skill") and app["skill"] not in on_disk
            }
        )
        self.assertEqual(
            bad,
            [],
            msg=f"app_registry.json apps[] reference unknown skill dirs: {bad}",
        )

    def test_min_splunk_version_field_is_well_formed_when_present(self):
        """``min_splunk_version`` is optional but must be a SemVer-ish string.

        The field documents the lowest Splunk Enterprise / Cloud Platform
        release the app supports. Skill preflight scripts can read it via
        future ``shared_registry_app_min_splunk_version_*`` helpers.

        Allowed shape: ``MAJOR.MINOR`` or ``MAJOR.MINOR.PATCH`` where each
        component is an unsigned integer. Empty / missing is allowed and
        means "no declared minimum."
        """
        import re

        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        version_re = re.compile(r"^\d+\.\d+(\.\d+)?$")

        offenders = []
        for app in registry.get("apps", []):
            value = app.get("min_splunk_version")
            if value is None or value == "":
                continue
            if not isinstance(value, str) or not version_re.fullmatch(value):
                offenders.append(f"{app.get('app_name')}: {value!r}")

        self.assertEqual(
            offenders,
            [],
            msg=(
                "min_splunk_version must be a string of the form MAJOR.MINOR "
                "or MAJOR.MINOR.PATCH. Offenders: " + ", ".join(offenders)
            ),
        )

        # Sanity: the seeded entries are present so the contract is exercised.
        seeded = {
            app["app_name"]: app.get("min_splunk_version", "")
            for app in registry.get("apps", [])
            if app.get("min_splunk_version")
        }
        self.assertIn("SA-ITOA", seeded)
        self.assertIn("SplunkEnterpriseSecuritySuite", seeded)
        self.assertIn("Splunk_AI_Assistant_Cloud", seeded)

    def test_splunkbase_apps_track_latest_verified_release_metadata(self):
        """Every Splunkbase-backed registry app records the latest version we audited."""
        import re

        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        version_re = re.compile(r"^\d+(\.\d+)*([.-][A-Za-z0-9]+)?$")
        date_re = re.compile(r"^[A-Z][a-z]+ \d{1,2}, 20\d{2}$")

        offenders = []
        for app in registry.get("apps", []):
            app_id = str(app.get("splunkbase_id", "")).strip()
            if not app_id.isdigit():
                continue
            version = app.get("latest_verified_version")
            date = app.get("latest_verified_date")
            if not isinstance(version, str) or not version_re.fullmatch(version):
                offenders.append(f"{app_id}/{app.get('app_name')}: bad latest_verified_version {version!r}")
            if not isinstance(date, str) or not date_re.fullmatch(date):
                offenders.append(f"{app_id}/{app.get('app_name')}: bad latest_verified_date {date!r}")

        self.assertEqual(offenders, [], msg="Invalid Splunkbase latest metadata: " + ", ".join(offenders))

    def test_splunkbase_app_coverage_ids_match_latest_audit_set(self):
        """The audited public Splunkbase app set should not shrink or grow silently."""
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        actual_ids = {
            str(app.get("splunkbase_id", "")).strip()
            for app in registry.get("apps", [])
            if str(app.get("splunkbase_id", "")).strip().isdigit()
        }

        self.assertEqual(
            actual_ids,
            SPLUNKBASE_APP_COVERAGE_IDS,
            msg=(
                "Public Splunkbase-backed app coverage changed. Re-audit Splunkbase latest "
                "versions, update registry metadata, then update SPLUNKBASE_APP_COVERAGE_IDS."
            ),
        )

    def test_splunkbase_apps_have_install_metadata_for_generic_and_skill_installers(self):
        """Every public Splunkbase app has enough registry metadata to install it."""
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        offenders = []
        for app in registry.get("apps", []):
            app_id = str(app.get("splunkbase_id", "")).strip()
            if not app_id.isdigit():
                continue
            if not app.get("app_name"):
                offenders.append(f"{app_id}: missing app_name")
            if not app.get("label"):
                offenders.append(f"{app_id}: missing label")
            if not app.get("skill"):
                offenders.append(f"{app_id}: missing skill")
            package_patterns = app.get("package_patterns")
            if not isinstance(package_patterns, list) or not all(
                isinstance(pattern, str) and pattern.strip()
                for pattern in package_patterns
            ):
                offenders.append(f"{app_id}/{app.get('app_name')}: missing package_patterns")

        self.assertEqual(
            offenders,
            [],
            msg="Public Splunkbase apps missing install metadata: " + ", ".join(offenders),
        )

    def test_splunkbase_apps_have_skill_entrypoint_coverage(self):
        """Every public Splunkbase app routes to an install/setup and validation path."""
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        offenders = []
        for app in registry.get("apps", []):
            app_id = str(app.get("splunkbase_id", "")).strip()
            if not app_id.isdigit():
                continue

            app_name = app.get("app_name")
            skill = app.get("skill", "")
            skill_dir = REPO_ROOT / "skills" / skill
            if not (skill_dir / "SKILL.md").is_file():
                offenders.append(f"{app_id}/{app_name}: missing skills/{skill}/SKILL.md")
                continue

            if skill == "splunk-app-install":
                install_entrypoint = skill_dir / "scripts/install_app.sh"
                if not install_entrypoint.is_file():
                    offenders.append(f"{app_id}/{app_name}: missing generic install_app.sh")
                # The generic installer validates by listing installed apps after install.
                list_entrypoint = skill_dir / "scripts/list_apps.sh"
                if not list_entrypoint.is_file():
                    offenders.append(f"{app_id}/{app_name}: missing generic list_apps.sh")
                continue

            setup_entrypoint = skill_dir / "scripts/setup.sh"
            validate_entrypoint = skill_dir / "scripts/validate.sh"
            if not setup_entrypoint.is_file():
                offenders.append(f"{app_id}/{app_name}: missing skills/{skill}/scripts/setup.sh")
            if not validate_entrypoint.is_file():
                offenders.append(f"{app_id}/{app_name}: missing skills/{skill}/scripts/validate.sh")

        self.assertEqual(
            offenders,
            [],
            msg="Public Splunkbase apps missing skill entrypoint coverage: " + ", ".join(offenders),
        )

    def test_splunkbase_install_dependencies_resolve_to_covered_apps(self):
        """Companion app dependencies must resolve to another covered Splunkbase entry."""
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        apps_by_id = {
            str(app.get("splunkbase_id", "")).strip(): app
            for app in registry.get("apps", [])
            if str(app.get("splunkbase_id", "")).strip().isdigit()
        }

        offenders = []
        for app_id, app in apps_by_id.items():
            for dependency_id in app.get("install_requires", []):
                dependency_id = str(dependency_id).strip()
                dependency = apps_by_id.get(dependency_id)
                if dependency is None:
                    offenders.append(
                        f"{app_id}/{app.get('app_name')}: dependency {dependency_id} is not in registry"
                    )
                    continue
                if dependency_id not in SPLUNKBASE_APP_COVERAGE_IDS:
                    offenders.append(
                        f"{app_id}/{app.get('app_name')}: dependency {dependency_id} is not in coverage set"
                    )
                if not dependency.get("skill"):
                    offenders.append(
                        f"{app_id}/{app.get('app_name')}: dependency {dependency_id} has no skill"
                    )

        self.assertEqual(
            offenders,
            [],
            msg="Public Splunkbase app dependencies are not fully covered: " + ", ".join(offenders),
        )

    def test_cisco_scan_setup_scripts_have_expected_invariants(self):
        """Structural invariants of the cisco-scan-setup scripts.

        The cisco-product-setup router depends on a healthy SCAN catalog,
        so any silent regression in the SCAN setup/validate scripts has a
        large blast radius. These checks pin the load-bearing pieces.
        """
        setup_text = (
            REPO_ROOT / "skills/cisco-scan-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")
        validate_text = (
            REPO_ROOT / "skills/cisco-scan-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        # setup.sh contract
        self.assertIn('APP_NAME="splunk-cisco-app-navigator"', setup_text)
        self.assertIn('PACKAGE_GLOB="splunk-cisco-app-navigator-*.tar.gz"', setup_text)
        self.assertIn("source \"${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh\"", setup_text)
        self.assertIn("/configs/conf-products", setup_text)
        self.assertIn("data/transforms/lookups/scan_splunkbase_apps", setup_text)
        self.assertIn("synccatalog", setup_text)
        self.assertIn("synclookup", setup_text)
        self.assertIn("warn_if_current_skill_role_unsupported", setup_text)
        # secrets must come from the credentials helper, never from argv
        self.assertNotIn("--password ", setup_text)
        self.assertNotIn("--token ", setup_text)

        # validate.sh contract
        self.assertIn('APP_NAME="splunk-cisco-app-navigator"', validate_text)
        self.assertIn('SYNC_SEARCH_NAME="SCAN - Splunkbase Catalog Sync"', validate_text)
        # Guardrail thresholds: keep these in sync with the SCAN package
        # under skills/cisco-product-setup/catalog.json.
        self.assertIn("MIN_PRODUCT_COUNT=", validate_text)
        self.assertIn("MIN_SAVED_SEARCH_COUNT=", validate_text)
        self.assertIn("--- Splunkbase Lookup ---", validate_text)
        self.assertIn("--- Catalog Sync Connectivity ---", validate_text)
        self.assertIn("--- Saved Searches ---", validate_text)
        self.assertIn("--- Scheduled Sync Job ---", validate_text)
