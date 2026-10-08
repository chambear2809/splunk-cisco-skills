# Splunk Enterprise 10.6 Lab Validation

Validation date: `2026-10-05`

## Isolated fresh install

- Package: `splunk-10.6.0.5-86587d4e3b27-linux-amd64.tgz`
- Official package: [Splunk Enterprise 10.6.0.5 Linux x86_64](https://download.splunk.com/products/splunk/releases/10.6.0.5/linux/splunk-10.6.0.5-86587d4e3b27-linux-amd64.tgz)
- SHA-512 verified: `c5f26fedc65b3959d63283106560f4318131357d3239404d8f12f18415a31901a6dc7357e04167eb840de73995b0100435ad09a1ded08674a6ec2a4f05337643`
- Installed version/build: `10.6.0.5` / `86587d4e3b27`
- Isolated home: `/opt/splunk-10.6-lab-kvdiag-20261005` (stopped and removed after validation)
- Host identity: AMD Ryzen AI Developer Platform 1 (`rex`), with `ID=amd-ryzen-ai-developer-platform`, `ID_LIKE=debian`, and version codename `rex`. Splunk 10.6 lists Debian 13 x86_64 as supported, but this custom OS does not identify as Debian 13; this is functional lab evidence, not a certification claim. See [Splunk Enterprise 10.6 system requirements](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.6/plan-your-splunk-enterprise-installation/system-requirements-for-use-of-splunk-enterprise-on-premises).

The host setup workflow installed the package into the dedicated home, configured the selected ports before first start, and ran without boot-start registration. The updated `scripts/validate.sh` passed the binary, service, version, SSH-based REST authentication, server-info, and KV Store checks. The controller could not reach the management port directly, so validation used the target's loopback management endpoint through the pinned SSH connection.

### Selected free ports

| Service | Port |
| --- | ---: |
| Management | 28089 |
| Web | 28000 |
| App server | 28065 |
| KV Store | 28191 |
| IPC broker | 28194 |
| PostgreSQL | 35432 |
| PostgreSQL primary / Traefik primary | 35433 |
| PostgreSQL replica / Traefik replica | 35434 |
| PostgreSQL Patroni | 38008 |
| PostgreSQL pgbouncer | 36432 |
| PostgreSQL nanny | 35435 |
| Nascent etcd peer | 32380 |
| Nascent etcd client | 32379 |

## KV Store result

Authenticated status reached `member=ready` and `cohosted.status=ready` about 54 seconds after setup returned. `migrationStatus=NotStarted` is expected for this fresh install because there was no prior KV Store database to migrate. The initial startup log showed HTTP 404 responses while the cohosted KV process looked up `postgres:kvstore.pdl`; later health checks and the authenticated readiness check succeeded. No internal credentials were created or edited manually.

The sanitized doctor smoke evidence no longer produced `SAD-KVSTORE-FAILED`. It still reported incomplete evidence and `strict_ready=false`, as expected from a snapshot containing only host, REST, and KV Store checks rather than a full operational health sweep.

Splunk's [10.6 cohosted KV Store migration guidance](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.6/administer-the-app-key-value-store/upgrade-to-a-cohosted-kv-store) and [10.6 sidecar port settings](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.6/splunk-sidecars/sidecar-configuration-settings) are the references used for the migration and port checks.

## Existing instance

The primary `/opt/splunk` instance was not upgraded. At the time of this
validation, it contained ITSI `5.0.1` and no verified backup-restoration
evidence; see the dated follow-up below for the updated ITSI 5.0.2 compatibility
and deferred-migration path. The lab waiver applied to the disk-space threshold
only. The primary service remained active, and its directory owner, group,
mode, and path were the same before and after removing the isolated test home.

### Primary-host follow-up — 2026-10-06

The prior ITSI compatibility hold is superseded by the repository-verified ITSI
`5.0.2` package evidence: the selected package is listed for Enterprise 10.6.
ITSI 5.0.x still requires deferring the cohosted PostgreSQL KV Store migration.
The host and KV Store skills now render and document the pre-upgrade
`postgresMigrateOnStartup = false` setting and post-upgrade checks. This
sequencing change does not itself validate a backup restore or establish
readiness for the primary upgrade.

Read-only checks on `192.168.68.92` confirmed the primary remains Enterprise
`10.4.3`, ITSI `5.0.1`, and active with boot-start enabled. The Enterprise root
filesystem was 70% used; the explicit lab storage waiver is recorded above.
The KV Store data directory measured 526 MB. Existing KV backup archives were
dated 2026-09-09, and an older 10.4.2 full-tree archive was present, but neither
was accepted as current restore evidence. Authenticated KV status and a fresh
backup/restore test are still required before the primary upgrade. The local
Splunk credential profiles tested so far do not authenticate to this host;
passwordless SSH access as `cisco` does not provide Splunk management API
authentication.

The selected current packages for Splunkbase IDs `2731`, `2679`, `2772`,
`3258`, `2911`, `2770`, and `3411` were downloaded, inspected for package
identity/version, and SHA-256 recorded on 2026-10-06. Their selected releases
explicitly list Enterprise 10.6. This updated the UCS TA, Box TA, security
appliance, syslog/web-proxy, and SOAR skills from conditional to supported;
other conditionals remain where one or more selected packages lack explicit
Enterprise 10.6 evidence or the skill needs product-level evidence.

## Reusable isolated validation instance

A later validation pass installed a separate Enterprise `10.6.0.5` instance at
`/opt/splunk-10.6-lab-core-20261005`; it remains available for additional skill
validation. It is configured on selected lab ports: management `28089`, Web
`28000`, HEC `28088`, receiving `29997`, KV Store `28191`, and IPC broker
`28194`. It has no boot-start registration. The primary `/opt/splunk`
installation was left unchanged.

The isolated instance passed fresh-install host validation and authenticated KV
Store readiness checks. The app installer installed a synthetic app at version
`1.0.0` and updated it to `1.1.0`. The KV Store workflow created a synthetic
collection and lookup, made a backup, restored it, and verified that its test
row remained available. Authenticated KV status reported the member and
cohosted service ready, including after restore.

The HEC workflow configured TLS on port `28088`; a test event was acknowledged
and found in index `lab106`. A Universal Forwarder `10.6.0.5` runs separately
from `/opt/splunkforwarder` at
`/opt/splunkforwarder-10.6-lab-core-20261005`, with management port `29089`
and receiver `29997`. Its validator confirmed the configured TCP management
listener, IPC port, service, and output target. A synthetic UF event was
received in `lab106`. Both events used sourcetype `lab106_json`.

The full admin doctor sweep completed `340` checks with no failures. The live
data-source readiness collector completed eight of eight selected read-only
searches and observed both HEC and UF events. Its generic dashboard dependency
checks found lab-environment macro and saved-search gaps, so that dashboard
result is not evidence about the synthetic app's compatibility. The separate
Historical matrix at that run: `54` supported, `47`
conditional, `1` blocked, `6` delegated, and `61` not applicable across all
`169` canonical skills. Functional lab checks do not independently establish
vendor compatibility for a package or official OS certification for this
custom Debian-derived OS.

The focused 10.6 and affected-workflow regression suites passed `420` tests
with `1,209` subtests. All `379` Bats tests passed. Repository catalog,
compatibility, shared-helper, documented-flag, orphan-source, tracked
configuration, Bash syntax, ShellCheck, and `git diff --check` checks passed.
The earlier serial pytest run was stopped after roughly 57 minutes without
completing. The repository review below records the subsequent complete run
and verification of its two failures.

## Repository review, 2026-10-07

The complete Python 3.11 suite finished with `4,847` passed, `27` skipped,
`3,185` subtests passed, and two failures. The failures were:

- `test_sc4s_clustered_ingest_uses_bundle_managed_hec`: the mocked readback of
  all 21 indexes exceeded its five-minute timeout under parallel load. The
  bounded timeout now matches the profile setup regression's 15-minute
  allowance; all index, bundle, and REST-routing assertions remain intact.
- `test_uf_validation_rejects_wrong_management_port`: the run loaded an older
  assertion before the forwarder error message and test were aligned during
  the review. The final test checks the exact effective-port error.

The subsequent focused run covering both cases and the complete forwarder
regressions passed `38` tests and `21` subtests. All `379` Bats tests passed.
The HEC renderer regression subset passed `16` tests and `5` subtests after
correcting Python escape syntax; generated Cloud scripts remained byte-identical.
Skill contracts passed for all `169` canonical skills. Shell syntax,
ShellCheck, Python lint, workflow validation, generated-document freshness,
tracked JSON/YAML, pre-commit hooks, dependency audits, and secret scans passed.
First-party Python compiled on Python 3.10, 3.11, and 3.14. All `409`
first-party modules compiled with syntax warnings treated as errors on 3.14.

Portability regressions cover relocated checkouts with spaces, offline audit
execution without site packages or local credentials, four-segment Splunk
versions, Kubernetes resource quantities, and forwarder configuration parsing.
The distribution contract in `CONTRIBUTING.md` requires bundled shared helpers
and delegated sibling skills. This review used local mocks and offline checks;
the live lab evidence above retains its original validation date.

## Isovalent demo EKS validation

Read-only validation date: `2026-10-05`. AWS access used the configured
`duo-sso` role. The temporary kubeconfig was created under a mode-`0700`
directory and removed after inspection; no cluster resources were changed.

- Cluster: `isovalent-demo`, region `us-east-1`, EKS control plane `1.36`
  (`v1.36.4-eks-cfb47f5`), status `ACTIVE`.
- Three worker nodes were Ready and reported kubelet `v1.34.4-eks-f69f56f`.
- The Cilium, Cilium DNS proxy, and Cilium Envoy DaemonSets each had `3/3`
  desired pods ready. The Cilium Operator pods were Ready.
- No `enterprise.splunk.com` CRDs or Splunk Enterprise Operator Helm release
  were present. Splunk Observability Collector releases/pods are present but do
  not provide evidence for the Splunk Enterprise Kubernetes operator workflow.
- The skill's exact Operator `3.1.0` compatibility gate rejected both
  Enterprise `10.6.0.5` on Kubernetes `1.36` and Enterprise `10.4.1` on
  Kubernetes `1.36`: its documented Kubernetes ceiling is `1.34`, and its
  Enterprise matrix does not list 10.6.

The EKS cluster is useful for read-only Cilium/EKS discovery and for proving
that the Kubernetes skill fails closed on this live version tuple. It is not a
valid target for applying the repo-selected Splunk Operator/POD bundle. The
Kubernetes skill remains blocked for Enterprise 10.6 pending an explicitly
compatible product release and a supported Kubernetes version.

## Isolated experimental 10.6 SOK smoke test

On `2026-10-06`, an explicitly unverified, non-production experiment was run
using a temporary EKS `1.34` cluster and Splunk Operator `3.1.0`. The bundle
used `--allow-unverified-versions`; live preflight emitted the expected warning
that Enterprise `10.6.0.5` is not in the documented Kubernetes `1.34` release
list. The skill's normal compatibility gate remains blocked for the
Operator/Enterprise `3.1.0` / `10.6.0.5` combination.

The S1 standalone reached `Ready` with one ready replica. The Enterprise
container reported `Splunk 10.6.0.5 (build 86587d4e3b27)`, and the Operator
Deployment reached `1/1`. The skill's status phase passed after its Operator
Helm readback was corrected to compare equivalent Kubernetes resource
quantities (for example, `1000m` and `1`). This verifies experimental runtime
behavior for this exact single-node lab topology. It is not Splunk support
evidence and does not promote the Enterprise 10.6 Kubernetes compatibility
status.

The isolated cluster was `splunk106-sok-validation-20261005` in `us-east-1`,
with one `m5.2xlarge` worker and temporary EBS CSI / gp3 storage. The cluster,
worker group, Operator, standalone, and test PVCs were deleted after validation;
cleanup was checked against AWS cluster and CloudFormation state. The live
operator/Enterprise pairing remains unsupported or unlisted by the [Splunk
Operator compatibility matrix](https://help.splunk.com/en/splunk-enterprise/splunk-operator-for-kubernetes-guide/3.1/splunk-operator-for-kubernetes-overview/splunk-operator-compatibility-matrix).

## Validation continuation — 2026-10-07

The current catalog assessment is **59 supported, 42 conditional, 1 blocked,
6 delegated, and 61 not applicable** across 169 skills. The historical 54/47
counts above describe the earlier assessment; they are not the current matrix.
The [workflow ledger](SPLUNK_ENTERPRISE_10_6_VALIDATION_LEDGER.md) tracks
compatibility separately from functional results and records package
dependencies and required readback. The [conditional review](skills/shared/references/enterprise-10.6-conditional-review.md)
covers every current conditional skill. Pending entries remain pending until
live evidence or an external blocker is recorded.

This continuation preserved the complete working tree in a protected source
snapshot before edits. The reproducible Ubuntu 24.04 x86_64 runner uses
owner-only workspace, interpreter, and temporary directories. Its SC4S
clustered-ingest regression reproduced repeated credential/profile parsing;
the earlier timeout adjustment alone is not accepted as defect closure.

The KV Store contract now uses plain `kvstore-status`, supports explicit
offline Enterprise versions, checks explicit version expectations against
the live installation, and rejects the removed startup-upgrade setting on
10.3 and later. Parallel backup does not promise cross-collection point-in-time
consistency, and collection definitions must exist before restore.

The SOK baseline is Operator **3.2.0**, with official chart/CRD hashes and
exact Operator/Enterprise image tag verification. Focused checks passed
67 tests, 81 subtests, and 12 Bats tests, including stale generation rejection,
Queue `secretKeyRef`, and preview PostgreSQL resource rejection. This is
repository/integration evidence; the historical 3.1.0 experiment above does
not qualify the new baseline or the coupled POD bundle.

Live knowledge-object checks found and corrected wildcard ACL rejection
and the invalid saved-search REST parameter. The corrected skill scripts
applied and read back a macro, disabled saved search, CSV lookup, and Dashboard
Studio view on the reusable 10.6.0.5 lab. The macro and dashboard searches
returned two retained test events; the CSV lookup returned one test row.
These checks do not establish product-source ingest or premium-app readiness.

### Evidence collected during this continuation

- All 34 SC4S/SC4SNMP regression methods passed on the protected Ubuntu runner, with 12 subtests, in 1,601.81 seconds. Repeated credential parsing was corrected and new batching regressions passed. This is mock integration evidence; collector live ingestion is still pending.
- Fresh Enterprise 10.6.0.5 installation on Ubuntu 24.04 x86_64 passed the corrected host validator. Corrected HEC apply and status, restart, TLS ingest and indexed canary search passed. The initial service-user ownership defect was reproduced and fixed.
- A separate restored 10.4.3 environment upgraded to 10.6.0.5 without ITSI. Controlled KV definitions, lookup and record survived migration and restart. Cohosted KV was ready; migration status was `Migration_Succeeded` immediately after upgrade and `NotStarted` after restart. These exact observations are retained without inferring undocumented lifecycle semantics.
- Standalone Monitoring Console apply, restart and health checks passed after omitting the unsupported 10.6 `mc_auto_config` key. Representative shipped indexer, process and license searches returned data. Dashboard Studio rendered the retained canary value in the browser.
- Corrected private-CA scripts passed strict OpenSSL chain verification. Web HTTPS with the generated leaf certificate returned a CA-verified response after restart. REST, HEC, forwarding, mutual TLS and distributed certificate changes remain separate pending workflows.
- Operator 3.2.0 S1 on EKS 1.34 passed skill status, ingest/search, native app installation, KV readback and persistence after pod replacement. Its namespace, PVCs and three EBS volumes were deleted and deletion verified. C3 and M4 remain pending; S1 does not qualify App Framework or the coupled POD bundle.

The first complete Ubuntu test run finished in 3,838.25 seconds with **400 failures, 4,674 passes, 33 skips and 2,972 passing subtests**. Missing runner prerequisites and permissions are being corrected and the latest source requires a new complete run. Earlier Bats checks passed all 379 tests, dependency audits reported no known vulnerabilities, and MCP protocol checks passed on Python 3.10 and 3.14. These receipts do not constitute final validation sign-off.

The second complete Ubuntu run finished in 3,753.94 seconds with **7 failures, 4,875 passes, 31 skips and 3,185 passing subtests**. Failures exposed stale evidence/version assertions, permission-sensitive test fixtures, missing test command prerequisites and a forwarder listener quoting defect. Focused corrections are being verified. That run used an earlier source snapshot and does not qualify subsequent changes; a complete run of the final source remains required.

The corrected standalone restart workflow passed on the existing secondary lab: the expected listeners returned, cohosted KV Store was ready with `migrationStatus=NotStarted`, and the controlled collection, lookup and three indexed events were retained. The primary daemon remained unchanged. This pass does not qualify clustered restart variants.

Primary administration access was restored with the authorized password reset. Both protected primary credential profiles authenticate against the inventoried host. A fresh cold installation/data archive and parallel KV backup were taken. The archive checksum was verified before restoring a 10.4.3 clone in a loopback-only network namespace with outbound activity disabled. Follow-up comparison qualified all 25 readable collection value differences as runtime state or regenerated identifiers; 106 records in the ITSI services collection match by identity and stable fields. The recovery data-readback gate passed with those explicit qualifications; 32 nonreadable collections and the lack of independent archive BSON/WiredTiger decoding remain recorded limits. A replacement protected off-host compressed backup has been verified in durable controller storage: decompression reproduced all 61,443,870,720 archive bytes and the original SHA256. The earlier temporary controller directory disappeared for an undetermined reason; the original primary archive remained intact throughout recovery. The clone remains on the primary physical host; off-host restoration has not yet been rehearsed.

The entitled ITSI 5.0.2 download returned HTTP 403 through both available authenticated download paths. Those historical download failures were resolved on 2026-10-07 by a user-supplied local ITSI 5.0.2 archive, verified as SA-ITOA build 117138 with full package SHA256. Functional ITSI update and migration-deferral rehearsal remain pending. The primary remains on Enterprise 10.4.3 and ITSI 5.0.1. No primary Enterprise upgrade or unsupported installation rollback has been performed.

## Additional verification — 2026-10-07

The third complete isolated Ubuntu run passed: **4,898 tests, 31 skips and 3,208 passing subtests in 3,798.94 seconds (63 minutes 18 seconds)**. The retained source snapshot SHA256 is `64a758b1650b5c9f1c1e9e7bb1f4aecc2de166e052dbb5f2401db0d4da3ccb45`. New credential-terminal and Galileo console-path corrections collected afterward require supplemental checks and final source qualification.

AppDynamics OAuth and application read access passed. Observability API access, one labeled synthetic metric ingestion and exact metric readback passed. Galileo health and authenticated project listing passed. These are credential/readiness results; they do not qualify the default integration workflows. The user confirmed this tenant is Galileo despite its UI branding and authorized a one-off exception to the legacy onboarding-date gate, limited to this disposable validation with exact-object cleanup. Its onboarding date remains unknown.

Galileo one-off synthetic validation passed project/log-stream creation, one trace and tool-span backend readback, and visible UI counts of one session, trace and span. Cleanup initially hit HTTP500; authenticated SDK deletion succeeded and exact project/stream GET requests returned HTTP404. The original project inventory was visibly restored. Enterprise export and evaluator/control variants remain pending. See `skills/shared/references/enterprise-10.6-galileo-one-off-evidence.json`.

Galileo cleanup qualification: both isolated test projects and streams are absent through exact-ID HTTP404 checks. MinIO connection-refused errors during deletion prevent verification of backing-object removal. Retained protected ownership ledgers identify only this run’s objects for the tenant infrastructure owner to verify after storage recovery. Physical cleanup and storage-dependent export remain explicit external gaps; API absence alone does not close them.

### 2026-10-07 isolated ITSI and C3 follow-up

The isolated clone now runs ITSI 5.0.2 on Enterprise 10.4.3. All six object-migration prechecks passed without skips, and migration reported terminal success at 21:51:15 UTC. Typed readback corrects the earlier service-count description: the 106 collection rows comprise 33 KPI templates, 40 KPI base searches and 33 KPI threshold templates; configured services, entities and glass tables are absent. Representative native-view validation and the Enterprise upgrade rehearsal remain open.

SOK C3 on EKS 1.34.11 and Enterprise 10.6.0.5 passed ingest/search, deployer bundle delivery, lookup readback, Monitoring Console search, and indexed/KV persistence after sequential indexer and search-head pod replacement. Both Helm releases and the owned namespace were removed, and AWS returned zero of its 21 recorded EBS volumes. M4, remote AppFramework and the independent POD qualification remain open.

### 2026-10-07 collector and ITSI native follow-up

SC4S 3.47.0 and SC4SNMP 1.17, pinned to reviewed image digests, passed the selected Docker Compose workflows on Ubuntu 24.04 x86_64 against fresh Enterprise 10.6.0.5. Repository checks reported 30 and 12 passes respectively, with zero warnings/failures. Authenticated CA/hostname-verified searches observed three parsed Cisco ASA events in `netfw` (`cisco:asa`), 75 SNMP polling events, 30 traps, and 510 metric measurements. Optional collector self-monitoring streams were not populated. Neither inspected collector image ships Splunk view files; companion packages require separate qualification. All ten owned containers, their volumes, two fixture processes, both temporary HEC inputs, and generated remote runtime/secret directories were removed. Synthetic indexed data remains on the disposable target until final target cleanup.

The isolated Enterprise 10.4.3 / ITSI 5.0.2 recovery clone now passes native fixture apply, live validation, and a second preview with three unchanged objects. Live HTTP 400 responses identified mandatory entity-type drilldown lists and top-level list-valued entity aliases/informational fields; repository regressions cover the corrected contracts. The fixture has one entity type, one entity, and one disabled service with an embedded KPI. This does not yet qualify ITSI on Enterprise 10.6: populated views, KPI data, restart persistence and the deferred Enterprise upgrade remain required.

Functional ledger after these collector results: **14 pass, 4 partial, 4 blocked, 86 pending, 61 not applicable**. Compatibility remains **59 supported, 42 conditional, 1 blocked, 6 delegated, 61 not applicable**.

### 2026-10-07 REST and HEC PKI follow-up

Generated private CA/intermediate/leaf assets now protect REST and HEC on the disposable Ubuntu 24.04 Enterprise 10.6.0.5 target. Authenticated REST and HEC health checks verify both CA and hostname; each endpoint accepts TLS 1.2 and TLS 1.3. After restart, both certificate passphrases are encrypted in Splunk `$8$` format, current KV Store and the cohosted Pdl service are ready, and the retained SmartStore canary still returns exactly one event. The certificate-parent traversal defect is corrected in the renderer and covered by regressions. PKI remains partial until forwarding/S2S, mutual TLS and distributed workflows are validated.

### 2026-10-07 ITSI view and entitlement follow-up

The isolated ITSI 5.0.2 clone renders its Entity Overview with the synthetic device type, one fixture entity and its host/environment dimensions. The fixture is manually created and has N/A discovery health; no populated entity-metrics claim is made. Its bounded source KPI search returns one row with value one and no warnings/errors. The Service Analyzer reports premium ITSI licensing required, and the UI identifies the deployment as IT Essentials Work. Lab owner must supply an already-available protected ITSI license file or licensed lab/profile before premium service monitoring can be qualified. An initial blank page resulted from the temporary validation bridge dropping session cookies; correcting that bridge restored timezone config without changing Splunk timezone preferences. The primary host remains on 10.4.3.


### 2026-10-07 Enterprise upgrade rehearsal and M4 follow-up

The isolated recovery clone completed Enterprise **10.4.3 → 10.6.0.5** with ITSI **5.0.2** and explicit `postgresMigrateOnStartup=false`. Authenticated checks before and after a second restart report KV Store ready on wiredTiger and `migrationStatus=NotStarted`. All 106 original template/base-search records retained their identities and stable fields. Native fixture validation passed on 10.6.0.5 before and after restart; the test event remains searchable exactly once. Entity Overview on the upgraded deployment displays the fixture entity and host/environment dimensions. Premium Service Analyzer and scheduled service/KPI health remain blocked by the existing ITSI license entitlement. The primary remains **10.4.3 / ITSI 5.0.1**. The protected 61,953,034,240-byte pre-Enterprise clone archive is retained; its additional off-host copy is still transferring, while the original primary off-host archive remains verified.

SOK M4 now passed its qualified core checks on EKS 1.34.11: four indexers across two sites, three SHC members, replication/search and site factors met, retained event/KV data after sequential member replacements. A static lookup fixture initially failed delivery to one replacement member; the reviewed per-app `always_overwrite` mode and version 1.1 delivered matching CSV hashes to all three members, and another replacement retained them. This does not qualify preservation of runtime-populated lookup data. Both releases and the namespace were deleted, all **23 recorded EBS volumes** are absent, and the four owned loopback forwards were terminated. Remote AppFramework and independent POD qualification remain open.

The fifth source snapshot (`10f2d9f22171881194277f77377dfd6a35be2691b7bc199e982db1dd13406a2f`) omitted repository directory symlinks. Its full test run was stopped and cannot qualify the source. A corrected snapshot must preserve these links and receive a complete run within the 120-minute bound. Auxiliary checks passed all 379 Bats tests, 442 shell syntax checks, MCP checks on Python 3.10 and 3.14, and secret-argument regressions; lint, dependency and generated-document follow-up remains in progress.

Current functional ledger: **14 pass, 5 partial, 4 blocked, 85 pending, 61 not applicable**. Compatibility counts remain unchanged. ITSI configuration is partial because live native fixtures passed while premium service monitoring and remaining configuration workflows are open.

### 2026-10-08 UTC remote AppFramework follow-up

SOK S1 remote AppFramework passed package installation, version 1.0.0 → 1.1.0 update, authenticated app/lookup readback, and persistence after pod replacement. The selected development deployment uses EKS 1.34.11, Operator 3.2.0, Enterprise 10.6.0.5 and encrypted gp3 storage. The observed update used its 900-second polling interval; it does not qualify manual triggering. Operator 3.2.0 adds empty premium-app status defaults; the validator now accepts only those exact version-bound defaults while retaining rejection of changed settings and stale state. Focused repository checks passed 77 tests and 104 subtests. Both owned Helm releases, namespace, all three recorded volumes, fixture object versions, temporary IAM identity/key and protected temporary files were deleted and verified. See `skills/shared/references/enterprise-10.6-sok-appframework-evidence.json`.

A separate C3 cluster-scope AppFramework run is provisioning with polling disabled to exercise the documented manual-update path. It has not yet passed its three-member delivery, update or persistence gates. The corrected sixth source snapshot preserves all 169 repository directory symlinks; its full Ubuntu suite remains in progress. New source corrections made after that snapshot require a final complete run before sign-off.

### 2026-10-08 UTC — C3 remote app delivery and sixth full suite

- C3 cluster-scope remote App Framework passed app 1.0.0 install, manual same-object update to 1.1.0 with polling disabled, and exact lookup readback on all three search heads. The updated app and lookup persisted after replacing one search-head pod; cluster replication/search and SHC health passed. The corrected generated status check exited zero. Root focused regressions: 98 passed and 120 subtests in 43.58 seconds.
- Cleanup remains open while the C3 target is used for SHC KV follow-up; a refreshed inventory records 21 owned EBS volumes. This qualifies the development-profile SOK workflow, independently of POD.
- Sixth full Ubuntu suite: 4,927 passed, 31 skipped, 3,208 subtests passed, zero JUnit failures/errors, 3,807.14 seconds. Source snapshot SHA-256: `a936a10a1685a794690bfb0c0dfcf070b089b09d54b07bc5cb423504c74a26bc`. Latest subsequent code corrections require another full run before final sign-off.
- Security Essentials 3.8.3 and Lookup Editor 4.0.8 were installed on the disposable fresh 10.6.0.5 Ubuntu host and retained after restart. Package presence checks passed; functional UI and data checks are still being completed.

## 2026-10-08 UTC — clustered KV restore and recovery-copy verification

- Three-member C3 legacy WiredTiger parallel backup and restore passed. Collection definitions were present on all members before restore; an owned test record was changed and then recovered with matching definition and record hashes on all three members. All KV Stores were ready. Archive: 17,905 bytes, SHA-256 `5bda19171d98261657302d94e2c9b9427bd1a2d14e4bafef32cb7099a4d5fa29`. Parallel consistency remains qualified by a quiescent fixture.
- Corrected the generated SHC restore script to enable maintenance only for point-in-time restore; the original parallel attempt exited before restoring because FULL_LOCK requires a static captain. Root regressions: 35 passed and 16 subtests in 6.29 seconds. The temporary credential profile was deleted; C3 teardown remains pending.
- The ITSI 5.0.2 pre-Enterprise-upgrade cold recovery archive was copied off host, preserving all 61,953,034,240 decompressed bytes and original SHA-256 `7b947164600aa1f8dbf8c14bc0585ea64a1c528038159226c748d6113bfb2868`. Compressed copy: 35,241,454,231 bytes. Primary upgrade and its observation period have not started.

## 2026-10-08 UTC — C3 cleanup and app restart checks

- C3 namespace and both releases deleted; all 21 recorded EBS volumes absent. Scoped AppFramework IAM user/key/policy and all `apps/c3/` fixture versions deleted, protected access files removed. Temporary EKS cluster deletion is in progress.
- Lookup File Editing 4.0.8 selected standalone workflow passed with 13/0/0 completion checks. Both handler searches returned Online after a fresh restart, and the two-row CSV readback was retained. An intermediate backup-handler Offline indication and protocol errors remain documented; no package hotfix was applied.
- SSE 3.8.3 inventory dashboard is populated with ingested Cisco ASA fixture data and survived restart. Content Mapping classification remains open; verified AI Toolkit/PSC packages have been acquired for the optional model workflow.
- Functional ledger: 15 pass, 6 partial, 4 blocked, 83 pending and 61 not applicable. Compatibility remains 59 supported, 42 conditional, 1 blocked, 6 delegated and 61 not applicable.

## 2026-10-08 UTC — core workflow closure and applicability review

- CIM 8.5.0 selected Authentication workflow passed on the Ubuntu 24.04 standalone running Enterprise 10.6.0.5. Three separately submitted events, normalized fields, model settings, and accelerated summaries survived controlled restart. Setup and audit views were checked in the browser; deprecated and configuration-only views are qualified separately. Five original configuration files were restored exactly, and the owned index, eventtype, and index data were verified absent. See [CIM evidence](skills/shared/references/enterprise-10.6-cim-evidence.json).
- Enterprise Ingest Actions mask, eval, and drop workflows passed through the owning conf-REST apply. Indexed test data proved masking, evaluation, and selective dropping; three retained events and the rules survived restart. The owned app, index data, and effective rules were verified absent after cleanup restart. S3 routing is a separate handoff. See [Ingest Actions evidence](skills/shared/references/enterprise-10.6-ingest-actions-evidence.json).
- Native SHC searchable rolling restart replaced all three member processes. All members returned to ready and retained five replicated KV records after 877 seconds. Temporary startup/PDL errors preclude a zero-downtime claim. The cluster fixture dashboard subsequently completed its search and displayed 20 events spanning sequence 1–20 on a search-head member. Native PKI qualification and topology cleanup remain open.
- DB Connect retained four unique rising-timestamp records and its checkpoint across restart. Input and Connection Health views were populated without operation errors. Two stock HEC diagnostic panels use query/logger names that differ from the installed runtime; their vendor defect remains a partial-result qualification. Owned DBX input, connection, identity, HEC token, PostgreSQL container/volume, and temporary password/token files were deleted. The four indexed rows remain temporarily for federated-search validation.
- A separate disposable Ubuntu standalone was installed for sequential federated-search consumer and Deployment Server validation. Native cluster default certificates lack endpoint SANs; global TLS verification has not been enabled on that cluster. Temporary private federation network rules and provider account remain owned cleanup items.
- The ninth full suite is running against frozen source SHA-256 `6e9305b32fabc9cb7d5b9d7331594efc5164ed8eb29b341e8a1813402fe9336a`. Auxiliary checks passed 379 Bats tests, syntax checks for 442 scripts, MCP tests on Python 3.10 and 3.14 (17 tests and 24 subtests each), corrected secret checks (35 tests and seven subtests), dependency vulnerability audits, and snapshot catalog/generated-document checks. Informational ShellCheck findings and pre-existing formatting drift remain qualified. One unused test import was subsequently removed and five focused tests passed; newer evidence and applicability edits require current generated-document checks and are not silently included in the frozen suite result.
- Applicability review corrected five Cloud service workflows from Enterprise conditional to not applicable: DDAA, ACS administration, its allowlist alias, Data Manager, and Ingest Processor. Historical classifications/dates remain in the [applicability evidence](skills/shared/references/enterprise-10.6-cloud-applicability-evidence.json). Current compatibility counts are **59 supported, 37 conditional, one blocked, six delegated, and 66 not applicable**. Current functional ledger is **18 pass, 10 partial, eight blocked, 67 pending, and 66 not applicable**. Exact selected releases of the Secure Access companion, GitHub add-on, CyberArk EPM add-on, and Connect for OTLP lack established Enterprise 10.6 vendor qualification; owners and next actions are recorded in the package-review evidence. Package pins were preserved.
- Primary upgrade remains gated by license-dependent ITSI premium recovery views. The primary remains Enterprise 10.4.3 / ITSI 5.0.1; recovery artifacts remain retained and the 24-hour post-upgrade observation period has not begun.


## 2026-10-08 UTC — ninth suite and isolated rerun

The ninth frozen-source run completed in **3,855.50 seconds** with **4,992 passing tests, 31 skips, 3,216 passing subtests, and one failure**. The relocated-library source-copy test could not read two mode-0600 root-owned bytecode cache files introduced into its workspace during the run. The source archive contains no bytecode cache files; the retained evidence identifies workspace contamination, while the exact root command that created those files is not established. This run is not a full-suite pass.

A tenth snapshot preserves 169 skill-directory symlinks and current source/applicability changes: SHA-256 `0a49d495862c274831a3e247cd9adcf675d5e97798c9490a9455fdd748a2734a`. Its isolated runner checks source ownership/readability before starting, disables bytecode generation, and reserves its workspace exclusively for tests. The 120-minute bound remains in place. Results are pending.


## 2026-10-08 UTC — federation lifecycle, collector and Galileo export

- Standard Splunk-to-Splunk federation passed owning REST apply and live validation, four unique records, provider disable/enable, restart retention, and negative CA/hostname controls. HTTP contract defects and provider/index sequencing were corrected. The unsupported global toggle refused before mutation. Exact provider/index objects and reader identity/password were deleted. Temporary AWS rule cleanup awaits Duo sign-in. The standalone consumer's reversible hostname-to-loopback workaround for cohosted KV authorization remains explicitly qualified; it is not suitable for native clustered roles.
- Corrected SSH restart listener probing passed on the consumer with port8089, healthy current/cohosted KV, and four retained records. Focused federation/restart regressions passed **70 tests**. These code edits follow the tenth frozen snapshot and require final full-suite coverage.
- External Linux Collector0.158.0 passed pinned official installation, owning validation, exact-host recent CPU/memory backend readback, and one correlated APM trace/span. Restart recovered recent metrics. Owning uninstall removed service/package/configuration/receivers and token-bearing files; the owned package repository/key and normalized controller token copy were removed. The persistent user token was preserved. Enterprise TA compatibility and Platform pairing remain separate qualifications.
- Galileo Observe export delivered exactly one correlated trace to Enterprise HEC and retained it after restart. Splunk HEC input/index/data/token cleanup passed. New Galileo project/stream deletion returned HTTP500 because MinIO refused connections; both exact objects remain HTTP200. The tenant infrastructure owner must restore storage and perform exact-ID cleanup and physical-object verification. Prior October7 evidence is preserved separately.
- Current functional ledger: **19 pass,12 partial,8 blocked,64 pending,66 not applicable**. Compatibility remains **59 supported,37 conditional,1 blocked,6 delegated,66 not applicable**. The primary remains10.4.3/ITSI5.0.1; premium ITSI licensing, final tests, remaining workflows and cleanup still gate completion.

### 2026-10-08 UTC — tenth full Ubuntu suite

The owner-isolated tenth frozen-source run passed **4,994 tests and 3,216 subtests**, with **31 skips**, zero JUnit failures/errors and exit status zero in **3,853.06 seconds** (64 minutes). Snapshot SHA-256: `0a49d495862c274831a3e247cd9adcf675d5e97798c9490a9455fdd748a2734a`. Retained report hashes and environment qualifications are recorded in `enterprise-10.6-full-tenth-suite-evidence.json`. Later federation, restart and ASA corrections still require a final full run. This result does not replace live workflow gates.

### 2026-10-08 UTC — ASA dashboard and ingestion validation

ASA **6.1.2** ships `cisco_asa_dashboard`; its earlier no-dashboard description was incorrect and is fixed. Exact package identity/checksum, install, configured SC4S **3.47.0** TCP/UDP ingestion, parsed Cisco ASA fields, populated main dashboard panels, successful optional CIM searches, four-record restart persistence and owned asset/token cleanup passed. The browser capture shows the initial two events; the later four-record result and post-restart panels were verified by API. Categories without corresponding connection fixtures legitimately return zero. Real ASA hardware remains unqualified.

The initial test token omitted SC4S’s internal index from its allowlist, rejecting batches. After correction, both new transport records arrived. Existing shared internal diagnostics follow normal retention; owned collector/container/volume, app, HEC input, fixture index/data and temporary secret files are absent. A subsequent cleanup restart exposed a collision between a custom PostgreSQL listener and an outgoing ephemeral connection. Runtime reservations for the custom ports restored active/cohosted KV readiness; protected restoration evidence is retained while the reusable lab exists.

Current functional ledger: **20 pass, 12 partial, 8 blocked, 63 pending and 66 not applicable**. Compatibility remains **59 supported, 37 conditional, 1 blocked, 6 delegated and 66 not applicable**. Later ASA/federation/restart code changes still require final full-suite coverage. Deployment Server, Agent Management and workload-management preparations are ready for review; AWS cleanup remains gated by expired Duo authentication.


### 2026-10-08 UTC — authorized AWS cleanup

AWS access was restored and cleanup used an ownership-verified exact resource allowlist. Nine disposable native cluster/standalone hosts and their nine EBS disks were removed. The validation bucket and all 12 object versions, two scoped IAM roles, temporary instance profile, two federation network rules, unused native security group/key pair and 13 obsolete local secret-bearing files were deleted and verified. The temporary storage profile was detached from the retained lab after its SmartStore fixture app, input and data were removed. The retained lab restarted successfully: current/cohosted KV are ready and search works.

Protected **isovalent-demo**, **genailens** and **streaming-eks-delay-demo** cluster configuration, nodegroup membership/scaling/status and preserved EC2 states/disks/security groups remained unchanged. One streaming nodegroup modification timestamp advanced without configuration changes; no cleanup mutation targeted protected resources. The primary, reusable AWS lab, recovery artifacts and persistent product credentials are preserved. See [cleanup evidence](skills/shared/references/enterprise-10.6-aws-cleanup-evidence.json).

Federated search closes as a qualified selected-workflow pass after exact AWS rule and disposable consumer cleanup. Current functional totals are **21 pass, 11 partial, 8 blocked, 63 pending and 66 not applicable**. Compatibility classifications are unchanged. Galileo tenant project/stream cleanup remains externally blocked by its unavailable storage service; the infrastructure owner and exact-ID cleanup action remain recorded. Final full-suite coverage, remaining live workflows and the primary upgrade gates are still outstanding.
