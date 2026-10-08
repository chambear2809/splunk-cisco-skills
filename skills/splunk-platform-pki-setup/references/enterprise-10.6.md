# Enterprise 10.6 certificate and secret changes

Enterprise 10.6 supports `$8$` encrypted configuration values. Existing `$7$`
values remain readable; conversion occurs only when an operator runs the
Splunk re-encryption commands. For inter-Splunk TLS, keep TLS 1.2 or 1.3 and
review public CA certificates for Client Authentication EKU removal. Replace
public certificates containing both Server Authentication and Client
Authentication EKUs before March 1, 2027. These platform changes do not qualify
any app or package for Enterprise 10.6 compatibility.
