# Handoff — ACME / cert-manager / Let's Encrypt

Triggered by `--mode public --public-ca-name acme`. This doc
covers two flavours:

- Direct ACME client on a Splunk host (acme.sh, certbot).
- cert-manager on a Kubernetes-fronted Splunk (e.g. Splunk Web
  behind an ingress).

## Direct ACME on a Splunk host

Best for **Splunk Web 8000 only** when it terminates TLS directly
and is reachable from the internet on port 80 (HTTP-01 challenge)
or when the operator can add DNS TXT records on demand (DNS-01
challenge). Inter-Splunk surfaces (8089, 9997, 8088, KV Store
EKU) are NOT well-suited to public ACME because:

- They live on private hostnames that public CAs can't validate.
- They typically use private FQDNs not in any public DNS.
- They need long-lived certs (Let's Encrypt's 90-day cert
  triggers a rolling-restart every ~60 days).

For Splunk Web with `acme.sh`:

```bash
# Install acme.sh on the SH host
curl https://get.acme.sh | sh

# Issue a cert via DNS-01 (recommended; doesn't need port 80 open)
~/.acme.sh/acme.sh \
    --issue \
    --dns dns_route53 \
    -d splunk.example.com \
    --keylength 2048 \
    --cert-file /opt/splunk/etc/auth/myssl/web/splunk-web-cert.pem \
    --key-file  /opt/splunk/etc/auth/myssl/web/splunk-web-key.pem \
    --fullchain-file /opt/splunk/etc/auth/myssl/web/splunk-web-fullchain.pem \
    --reloadcmd "/opt/splunk/bin/splunk restart splunkweb"
```

The `--reloadcmd` triggers a Splunk restart on every renewal.
For cluster-wide rotation, use the rotation-runbook instead.

## cert-manager on Kubernetes

For Splunk Operator for Kubernetes (SOK) deployments where Splunk
Web runs behind an ingress controller. This is the cleanest
public-CA story because cert-manager handles renewal end-to-end.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: splunk-web-tls
  namespace: splunk
spec:
  secretName: splunk-web-tls
  dnsNames:
    - splunk.example.com
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

The ingress controller terminates TLS with the cert-manager
secret. Splunk Web inside the cluster runs with its own
internal-CA cert (this skill's Private mode covers that part).

Key constraint: **cert-manager-managed Let's Encrypt certs are
90 days max.** Plan for a rolling restart every 60 days. Use
the kubectl-side `cert-manager.io/issue-temporary-certificate`
+ rotation runbook so search head pods pick up the new cert
without disruption.

## DNS-01 vs HTTP-01

- **HTTP-01** — requires inbound port 80 from the internet to the
  challenge responder (cert-manager / acme.sh). Common in
  Kubernetes; harder for Splunk Enterprise on a corp DMZ.
- **DNS-01** — requires API access to your DNS provider so the
  ACME client can write TXT records. Works behind firewalls.
  Recommended for Splunk Enterprise.

## Splunk Cloud HEC custom-domain BYOC via ACME

Not currently supported. Splunk Cloud's ACS does not expose a
self-service BYOC endpoint for HEC custom-domain certs. Operators
who want a custom HEC domain on Splunk Cloud open a Splunk
Support ticket; ACME automation isn't possible end-to-end on
Splunk Cloud today.

See [splunk-cloud-ufcp-handoff.md](splunk-cloud-ufcp-handoff.md).

## Verify before installing

```bash
bash splunk-platform-pki-rendered/pki/install/verify-leaf.sh \
    --cert splunk-platform-pki-rendered/pki/signed/web-splunk.example.com.pem \
    --ca   splunk-platform-pki-rendered/pki/install/cabundle.pem
```

Let's Encrypt's chain ships with a single intermediate
("R10" / "R11" / etc.) signed by ISRG Root X1. Concatenate them
into `cabundle.pem`.

## Splunk-side rotation order

90-day Let's Encrypt certs require **automated** rolling restart
(running the runbook every 60 days). Most operators wire this
into:

- A scheduled saved search that detects "cert expires in less
  than 30 days" via the SSL Certificate Checker (Splunkbase 3172).
- An ITSI / Splunk On-Call notification that pages the platform
  team.
- A scheduled job that runs the rotation runbook unattended in a
  maintenance window.
