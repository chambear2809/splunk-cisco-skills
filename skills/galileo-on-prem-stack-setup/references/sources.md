# Sources and Version Review

Review these official pages and the entitled chart before each supported
release update:

- Installation methods (four methods; galileoctl UI required for first install, CLI as workstation/CI alternative): <https://helm.galileo.ai/docs/getting-started/installation/>
- Deployment process: <https://helm.galileo.ai/docs/deployment/deployment-guide/>
- Umbrella chart and CRD controls: <https://helm.galileo.ai/docs/deployment/galileo-stack/>
- Configuration: <https://helm.galileo.ai/docs/guides/configuration/>
- galileoctl: <https://helm.galileo.ai/docs/guides/galileoctl/>
- Air-gap: <https://helm.galileo.ai/docs/deployment/airgapped-deployment/>
- Operations: <https://helm.galileo.ai/docs/post-deployment/overview/>
- Upgrades and ongoing operations: <https://helm.galileo.ai/docs/post-deployment/upgrades-ongoing-operations/>
- Agent Skills specification: <https://agentskills.io/specification>
- Helm chart hooks: <https://helm.sh/docs/topics/charts_hooks/>
- Helm CRDs: <https://helm.sh/docs/chart_best_practices/custom_resource_definitions/>

The documentation currently contains conflicting examples for Kubernetes
floors, release names, timeouts, optional-service ownership, component counts,
embedded-service production support, storage-provider support, monitoring
components, sizing and DR. Do not resolve a conflict by guessing. The pinned
chart plus written Galileo/CSE direction is the release-specific authority.
