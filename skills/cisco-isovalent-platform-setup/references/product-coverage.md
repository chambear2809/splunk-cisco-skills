# Isovalent Product and Feature Coverage

Coverage reviewed 2026-09-30 against upstream Cilium/Tetragon releases and
current Cisco Isovalent product material. The feature status in
`catalog.json` describes what this repository's skill can safely render,
apply, discover, validate, or hand off. It does not imply that a licensed
feature is included in an OSS chart or that a product's full installer is
implemented here.

## Product map

| Product area | Product capabilities | This skill's coverage |
| --- | --- | --- |
| Networking for Kubernetes | Cilium CNI, IPAM and routing, policies, service connectivity, Gateway API/Ingress, Cluster Mesh, BGP, encryption, Hubble | OSS Cilium installation and common Kubernetes workflows are rendered/applied. Multi-Pool IPAM, newer APIs, and Enterprise networking surfaces are separately marked as discovery-only or gated when release-specific configuration and validation are absent. |
| Runtime Security | Tetragon observability and enforcement; Kubernetes, VM, edge, and hybrid coverage; Enterprise rules, Connection Logs, risk scoring, alerting, and analytics | OSS/Enterprise Kubernetes Tetragon install, observe-only starter policies, export, metrics, and validation are covered. Enforcement policy design, Enterprise policy content, conversion, Connection Log/alerting workflows, and non-Kubernetes host lifecycle remain explicitly gated or out of scope. |
| Networking for Virtualization | Isovalent Private Networks and Network Bridge for VM/Kubernetes connectivity and migration | Product is identified and handed off. The skill has no VM control-plane, migration, bridge, or private-network renderer. |
| Isovalent Load Balancer | Standalone or in-cluster deployment; Tier 1 XDP L3/L4 and Tier 2 Envoy L7; VIP/service/backend APIs; BGP/BFD, L2, IPv6 translation, tenancy | Product is identified and access-gated. Existing Cilium LB IPAM, BGP, and L2 support is not equivalent to deploying or configuring Isovalent Load Balancer. |
| Isovalent Enterprise Platform | Unified product release and operating model across the portfolio | The Kubernetes Cilium/Tetragon slice is covered. Cross-product rollout and lifecycle orchestration are handed off. |
| Hubble Enterprise / Timescape / DNSProxy | Enterprise observability, historical flow storage, and DNS HA | Existing chart paths remain separately version-pinned and entitlement-gated; confirm current customer chart/version support before upgrade. |
| Product tiers and entitlements | Essentials/Advantage tiers vary by product; Networking for Virtualization is Advantage-only, Runtime Security can be standalone, and Load Balancer has its own Essentials offer | Check the customer's Cisco order/entitlements. The skill does not infer purchased tiers, licensed node quantities, or enabled features. |

Cisco's current product overview positions the platform across Kubernetes,
virtualization, runtime security, and load balancing. The July 2026 Enterprise
Platform 26.05 announcement describes a unified operating model for Kubernetes,
VMs, and load balancing. Those releases are product coverage signals; they do
not establish chart versions or make separate installers interchangeable.
Isovalent's Networking 1.19 materials also describe Enterprise policy tiers,
BGP route import, and Timescape enhancements; Runtime Security 1.18 material
adds updated policy and detection workflows. The matching product-specific
features are listed in `catalog.json` with their actual implementation status.
Cisco's current offer description makes clear that product availability and
feature levels depend on the customer order: Networking for Kubernetes has
Essentials and Advantage tiers; Runtime Security can be purchased standalone
or with Kubernetes Networking; Networking for Virtualization is Advantage-only;
and Load Balancer is separately entitled. Treat entitlement as a preflight
input rather than assuming that an Enterprise license unlocks every feature.

## Feature coverage decisions

- **Cilium fundamentals:** The skill models CNI, kube-proxy replacement, IPAM,
  native/tunnel routing, Kubernetes and Cilium policy, DNS/FQDN, L7 visibility,
  Ingress, Gateway API, service mesh, Cluster Mesh, egress gateway, BGP, LB
  IPAM, L2 announcements, WireGuard/IPsec, host firewall, bandwidth manager,
  Hubble, metrics, and distribution constraints.
- **Current API and release surfaces:** Cilium's current docs include Gateway
  API v1.6 resources and GAMMA, MCS-API, and expanded IPv6 and networking
  features. This renderer only enables a subset of controller/chart flags; it
  does not automatically create Gateway routes, MCS resources, validate dual
  stack cloud routing, or provide full release acceptance for those features.
  Those gaps are `discover_only` until implementation and validation exist.
- **Enterprise Networking:** Enterprise release materials describe multi-
  network, multicast, policy tiers, route import, Network Policy Change
  Tracker, Envoy HA, and Timescape enhancements. These are explicitly
  `gated_private` when their product-specific support, values, APIs, or
  entitlements are not covered by the public chart renderer.
- **Tetragon:** Tetragon supports TracingPolicy and TracingPolicyNamespaced,
  process/network/file/syscall observability, in-kernel filtering, and
  enforcement. This skill's bundled policies are observe-only. Enforcement is
  not an unsupported Tetragon product feature; it is unsupported by this
  skill's reviewed policy bundle because the skill does not author or validate
  customer enforcement semantics.
- **Enterprise Runtime Security:** Enterprise materials list older-kernel
  support, enhanced TLS/SSL visibility, rule conversion, curated CVE policies,
  and detection/analytics such as risk scoring and toxic combinations. These
  remain gated in the catalog; the OSS starter policies and metrics validator
  are not evidence of these capabilities.
- **Load balancing:** Standard Cilium service load balancing, Ingress/Gateway,
  LB IPAM, and BGP/L2 announcement are tracked separately from Isovalent Load
  Balancer. The latter has its own standalone/in-cluster modes, two-tier
  dataplane, CRDs, routing, monitoring, and tenant controls; this repository
  does not render those product APIs.

## Version and source evidence

As of 2026-09-30, upstream lists Cilium 1.20.2 and Tetragon 1.7.1 as the latest
stable public releases. The OSS chart contract uses those versions. Enterprise
chart pins in this repository are retained as last cluster-validated evidence;
the private Isovalent Helm index was not available for independent latest
version verification, so the skill does not label those pins current. Resolve
and review entitled chart values before an Enterprise upgrade.

Upstream Cilium 1.20.2 documents Kubernetes 1.33–1.36 as e2e-tested and a
Linux 5.10-or-equivalent base requirement. Tetragon documents Linux 4.19 or
newer with BTF and required BPF configuration; older kernels may lack specific
features. The renderer currently does not compare the Kubernetes server
version to the Cilium support range, and its numeric kernel check can flag
equivalent distro kernels. Treat these as explicit preflight limits and verify
the exact Enterprise/provider matrix independently.

Primary product and technical sources:

- [Isovalent Enterprise Platform overview](https://isovalent.com/)
- [Enterprise Platform 26.05](https://isovalent.com/blog/post/isovalent-enterprise-platform-2605-bringing-kubernetes-vms-and-load-balancing-into-one-operating-model/)
- [Isovalent Networking for Kubernetes 1.19](https://isovalent.com/blog/post/isovalent-networking-for-kubernetes-119-bgp-route-import-policy-tiers-and-timescape-enhancements/)
- [Isovalent Runtime Security 1.18](https://isovalent.com/blog/post/isovalent-runtime-security-118/)
- [Cisco Isovalent Enterprise Platform Offer Description](https://www.cisco.com/c/dam/en_us/about/doing_business/legal/OfferDescriptions/Isovalent-Enterprise-for-Cilium.pdf)
- [Networking for Virtualization](https://isovalent.com/products/networking-for-virtualization/)
- [Isovalent Load Balancer technical deep dive](https://isovalent.com/blog/post/isovalent-load-balancer-technical-deep-dive/)
- [Isovalent Enterprise Tetragon documentation](https://docsnext.isovalent.com/project/tetragon/index.html)
- [Cilium 1.20.2 documentation](https://docs.cilium.io/en/stable/)
- [Cilium 1.20.2 and maintained release branches](https://github.com/cilium/cilium)
- [Tetragon releases](https://github.com/cilium/tetragon/releases)
- [Tetragon enforcement modes](https://tetragon.io/docs/concepts/tracing-policy/mode/)
- [Tetragon kernel requirements FAQ](https://tetragon.io/docs/installation/faq/)
- [Cilium Gateway API](https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/gateway-api/)
- [Cilium GAMMA](https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/gamma/)
- [Cilium MCS-API](https://docs.cilium.io/en/stable/network/clustermesh/mcsapi/)
