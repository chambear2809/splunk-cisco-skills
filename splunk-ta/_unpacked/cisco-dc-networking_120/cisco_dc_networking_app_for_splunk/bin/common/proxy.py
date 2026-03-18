from urllib.parse import quote_plus


def get_proxy_uri(proxy):
    """
    Construct a proxy URI from the given proxy settings.

    Args:
        proxy (dict): Proxy settings with keys 'proxy_type', 'proxy_url',
                      'proxy_port', 'proxy_username', and 'proxy_password'

    Returns:
        str: The constructed proxy URI or None if proxy settings are incomplete
    """
    if not proxy or not proxy.get("proxy_url") or not proxy.get("proxy_type"):
        return None

    uri = f"{proxy['proxy_type']}://{proxy['proxy_url']}"
    if proxy.get("proxy_port"):
        uri += f":{proxy['proxy_port']}"

    if proxy.get("proxy_username") and proxy.get("proxy_password"):
        credentials = (
            f"{quote_plus(proxy['proxy_username'])}:"
            f"{quote_plus(proxy['proxy_password'])}"
        )
        uri = f"{proxy['proxy_type']}://{credentials}@{uri}"

    return uri


def get_proxies(data):
    """
    Extract proxy settings from the given data and construct a proxies dictionary.

    Args:
        data (dict): Data containing proxy settings with keys 'nd_proxy_type',
                     'nd_proxy_url', 'nd_proxy_port', 'nd_proxy_username',
                     and 'nd_proxy_password'

    Returns:
        dict or None: A dictionary with 'http' and 'https' keys set to the
                      constructed proxy URI or None if proxy settings are incomplete
    """
    proxy_type = (
        data.get("nd_proxy_type")
        or data.get("nexus_9k_proxy_type")
        or data.get("apic_proxy_type")
    )
    proxy_url = (
        data.get("nd_proxy_url")
        or data.get("nexus_9k_proxy_url")
        or data.get("apic_proxy_url")
    )
    proxy_port = (
        data.get("nd_proxy_port")
        or data.get("nexus_9k_proxy_port")
        or data.get("apic_proxy_port")
    )
    proxy_username = (
        data.get("nd_proxy_username")
        or data.get("nexus_9k_proxy_username")
        or data.get("apic_proxy_username")
    )
    proxy_password = (
        data.get("nd_proxy_password")
        or data.get("nexus_9k_proxy_password")
        or data.get("apic_proxy_password")
    )

    proxy = {
        "proxy_type": proxy_type,
        "proxy_url": proxy_url,
        "proxy_port": proxy_port,
        "proxy_username": proxy_username,
        "proxy_password": proxy_password,
    }

    proxy_uri = get_proxy_uri(proxy)
    if proxy_uri:
        return {"http": proxy_uri, "https": proxy_uri}
    return None
