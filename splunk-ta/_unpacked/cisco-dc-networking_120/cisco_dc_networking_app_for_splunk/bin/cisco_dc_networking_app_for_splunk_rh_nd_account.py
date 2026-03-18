import import_declare_test
from cisco_nexus_dashboard_validation import ValidateNexusDashboardCreds
from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    SingleModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.splunk_aoblib.rest_migration import ConfigMigrationHandler
from splunk import rest
import requests
import re
from splunktaucclib.rest_handler.error import RestError
import json
import logging
import traceback
import common.log as log
import common.proxy as proxy

logger = log.get_logger("cisco_dc_nd_validation")
from common.utils import GetSessionKey, get_sslconfig, read_conf_file

util.remove_http_proxy_env_vars()


class AccountHandler(ConfigMigrationHandler):
    """Account Handler."""

    def handleCreate(self, confInfo):
        """Handle creation of account in config file."""
        super(AccountHandler, self).handleCreate(confInfo)
        self.create_apic_accounts()

    def handleRemove(self, confInfo):
        """Handle the delete operation."""
        try:
            session_key = GetSessionKey().session_key
            inputs_file = read_conf_file(session_key, "inputs")
            created_inputs = list(inputs_file.keys())
            input_list = []
            input_type_list = ["cisco_nexus_dashboard"]

            for _input in created_inputs:
                nd_input = _input.split("://")
                if nd_input[0] in input_type_list:
                    configured_account = inputs_file.get(_input).get("nd_account")
                    if configured_account:
                        accounts = configured_account.split(",")
                        for acc in accounts:
                            if acc == self.callerArgs.id:
                                input_list.append(nd_input[1])
                                break

            if input_list:
                raise RestError(
                    500,
                    f'"{self.callerArgs.id}" cannot be deleted because it is in use by the following inputs: {input_list}',
                )
            else:
                super(ConfigMigrationHandler, self).handleRemove(confInfo)
        except Exception as e:
            raise RestError(500, f"An error occurred while deleting account: {e}")

    def create_apic_accounts(self):
        """Creates APIC accounts."""
        try:
            header = {"Content-Type": "application/json"}
            token = None
            api_data = {}
            sites = {}
            entered_data = self.callerArgs.data
            name_of_acc = self.callerArgs.id.strip()
            hosts = entered_data.get("nd_hostname")[0].strip().split(",")
            hosts = [each.strip() for each in hosts if each.strip()]
            proxy_fields = [
                "nd_proxy_type",
                "nd_proxy_url",
                "nd_proxy_port",
                "nd_proxy_username",
                "nd_proxy_password"
            ]
            proxy_info = {
                field: next(iter(entered_data.get(field, [])), None)
                for field in proxy_fields
            }
            proxy_data = proxy.get_proxies(proxy_info)
            api_data = {
                "userName": entered_data.get("nd_username")[0].strip(),
                "userPasswd": entered_data.get("nd_password")[0].strip(),
            }
            if (
                entered_data.get("nd_authentication_type")[0] == "remote_user_authentication"
                and entered_data.get("nd_login_domain")
                and entered_data.get("nd_login_domain")[0]
            ):
                api_data["domain"] = entered_data.get("nd_login_domain")[0].strip()
            elif entered_data.get("nd_authentication_type")[0] == "local_user_authentication":
                api_data["domain"] = "local"
            else:
                api_data["domain"] = "DefaultAuth"

            success = False
            for host in hosts:
                try:
                    host = host.strip()
                    if entered_data.get("nd_port")[0].strip():
                        host += f":{entered_data.get('nd_port')[0].strip()}"

                    # Login API call
                    url = f"https://{host}/login"
                    data = json.dumps(api_data)
                    logger.info(f"Making an API call to the url {url}.")
                    resp = requests.post(
                        url,
                        data=data,
                        headers=header,
                        verify=get_sslconfig(),
                        timeout=180,
                        proxies=proxy_data
                    )
                    if resp.ok:
                        logger.info(
                            f"Successfully received the response for the url {url}."
                        )
                        resp = resp.json()
                        token = resp.get("token")
                        header["Authorization"] = f"Bearer {token}"
                    else:
                        logger.error(
                            f"Login API call failed for the host {host}. Response: {resp.text}."
                        )
                        continue

                    # Sites API call
                    url = f"https://{host}/mso/api/v1/sites"
                    sites = {}
                    logger.info(f"Making an API call to the url {url}.")
                    resp = requests.get(
                        url, headers=header, verify=get_sslconfig(), timeout=180, proxies=proxy_data
                    )
                    if resp.ok:
                        logger.info(
                            f"Successfully received the API call for the url {url}."
                        )
                        resp = resp.json().get("sites")
                        for each in resp:
                            urls = ", ".join(each.get("urls"))
                            urls = urls.replace("https://", "").replace("http://", "")
                            sites[each.get("name")] = urls
                        logger.info(f"Collected a total of {len(sites)} sites.")
                        success = True
                        break
                    else:
                        if resp.status_code != 404:
                            logger.error(
                                f"Failed to fetch APIC sites for the host {host}. Response: {resp.text}."
                            )
                        else:
                            logger.info(f"No APIC sites found for the host {host}.")
                        continue
                except Exception as e:
                    logger.error(
                        f"Error occurred while fetching site details. Host: {host}. Error: {str(e)}"
                    )
                    continue

            if success:
                errors = False
                count = 1
                for key, value in sites.items():
                    raw_name = f"{name_of_acc}_{count}_{key}"
                    safe_name = re.sub(r'[^A-Za-z0-9]', '_', raw_name)
                    try:
                        logger.debug(f"Creating ACI account for site: {key}")
                        account_stanza = {}
                        account_stanza.update(
                            {
                                "name": safe_name,
                                "apic_hostname": value,
                                "apic_port": "443",
                                "apic_authentication_type": "password_authentication",
                            }
                        )
                        rest.simpleRequest(
                            "/servicesNS/nobody/cisco_dc_networking_app_for_splunk/configs/"
                            "conf-cisco_dc_networking_app_for_splunk_aci_account",
                            self.getSessionKey(),
                            postargs=account_stanza,
                            rawResult=True,
                            method="POST",
                            raiseAllErrors=True,
                        )
                        logger.debug(
                            f"Successfully created ACI account for site: {key}"
                        )
                        count = count + 1
                    except Exception as err:
                        errors = True
                        logger.error(
                            f"Failed to create ACI account for site: {key}. Error: {str(err)}"
                        )
                if not errors:
                    logger.info(
                        "Successfully created ACI accounts for the all the fetched sites."
                    )
        except Exception as e:
            logger.error(f"Error in fetching sites. Error: {str(e)}")


fields = [
    field.RestField(
        'nd_hostname',
        required=True,
        encrypted=False,
        default='',
        validator=ValidateNexusDashboardCreds()
    ),
    field.RestField(
        'nd_port',
        required=True,
        encrypted=False,
        default='8089',
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        )
    ),
    field.RestField(
        'nd_authentication_type',
        required=True,
        encrypted=False,
        default='local_user_authentication'
    ),
    field.RestField(
        'nd_username',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=200,
            min_len=1,
        )
    ),
    field.RestField(
        'nd_password',
        required=True,
        encrypted=True,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=1,
        )
    ),
    field.RestField(
        'nd_login_domain',
        required=False,
        encrypted=False,
        default=None,
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'nd_enable_proxy',
        required=False,
        encrypted=False,
        default=0
    ),
    field.RestField(
        'nd_proxy_type',
        required=False,
        encrypted=False,
        default=False
    ),
    field.RestField(
        'nd_proxy_url',
        required=False,
        encrypted=False,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'nd_proxy_port',
        required=False,
        encrypted=False,
        default='',
        validator=validator.Number(
            max_val=65535,
            min_val=1,
        )
    ),
    field.RestField(
        'nd_proxy_username',
        required=False,
        encrypted=False,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    ),
    field.RestField(
        'nd_proxy_password',
        required=False,
        encrypted=True,
        default='',
        validator=validator.String(
            max_len=8192,
            min_len=0,
        )
    )
]
model = RestModel(fields, name=None)


endpoint = SingleModel(
    "cisco_dc_networking_app_for_splunk_nd_account", model, config_name="nd_account"
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AccountHandler,
    )
