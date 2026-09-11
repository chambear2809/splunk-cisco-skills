<!-- Generated from skills/catalog.yaml; schema: 1; entry-sha256: 90a42c0a91c880298474feafe27330389dc2ad84ea10610d5386132887d8bbae. -->

Deploy Splunk Observability Cloud for a Cisco AI Pod via the umbrella that composes splunk-observability-cisco-nexus-integration, splunk-observability-cisco-intersight-integration, and splunk-observability-nvidia-gpu-integration via subprocess + Python deep-merge, then adds AI-Pod-specific blocks: NIM, vLLM, Milvus, NetApp Trident, Pure Portworx, Redfish scrapes; dual-pipeline filtering; the k8s_attributes/nim processor; OpenShift defaults; the rbac.customRules patch (when --nim-scrape-mode endpoints); --workshop-mode multi-tenant pattern; and the OpenShift SCC helper.

Read and follow the instructions in skills/splunk-observability-cisco-ai-pod-integration/SKILL.md to help the user. If more detail is needed, also read skills/splunk-observability-cisco-ai-pod-integration/reference.md.
