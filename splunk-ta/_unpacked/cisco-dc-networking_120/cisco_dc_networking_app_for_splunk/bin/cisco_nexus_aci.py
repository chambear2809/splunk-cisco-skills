import import_declare_test

import sys
import requests
import json
import concurrent.futures
import re
import threading
from solnlib import conf_manager
from urllib.parse import parse_qs
from datetime import datetime
from datetime import date, timedelta
from splunklib import modularinput as smi
from nexus_aci_helper import stream_events, validate_input
import common.log as log
from cisco_dc_input_validators import *
from splunklib import modularinput as smi
from common.utils import get_sslconfig
from solnlib.modular_input import checkpointer
from common.consts import ACI_CHKPT_COLLECTION
import traceback
import cisco_dc_aci_session as aci
import common.proxy as proxy
from common import consts
if sys.version_info < (3, 0, 0):
    from urllib import quote_plus
else:
    from urllib.parse import quote_plus

pagelimit = consts.ACI_DATA_PAGE_LIMIT
timeout_val = consts.TIMEOUT


class CISCO_NEXUS_ACI(smi.Script):
    def __init__(self):
        super(CISCO_NEXUS_ACI, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme('cisco_nexus_aci')
        scheme.description = 'ACI'
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                'name',
                title='Name',
                description='Name',
                required_on_create=True
            )
        )
        scheme.add_argument(
            smi.Argument(
                'apic_account',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'apic_input_type',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'apic_arguments',
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'mo_support_object',
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'aci_additional_parameters',
                required_on_create=False,
            )
        )
        return scheme
    
    def format_kv_pair(self, key, value):
        if value.replace(".", "").isdigit():
            return f"{key}={value}"
        elif value == "":
            return f"{key}=\"\""
        else:
            return f"{key}=\"{value}\""

    def ingest_mo_data_in_splunk(self, data, apic_host, ew, index):
        events_ingested_count = 0
        for each in data:
            for key, value in each.items():
                final_data = value.get("attributes")
                if final_data:
                    final_data["component"] = key
                    event_data = json.dumps(final_data)
                    event_data = event_data.replace('\n', '').replace('\r', '')
                    event = smi.Event(data=event_data, index=index, sourcetype="cisco:dc:aci:managed_object", unbroken=True)
                    ew.write_event(event)
                    events_ingested_count += 1
        return events_ingested_count

    def ingest_data_in_splunk(self, modata, attribute_data, apic_class, apic_host, ew, sourcetype, index):
        resp = []
        currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
        resp.append(currentTime)
        events_ingested_count = 0
        if modata:
            for mo_object_data in modata:
                for mo_obj in mo_object_data:
                    mo_attribute_data = mo_object_data[mo_obj]["attributes"]

                    resp = []
                    currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
                    resp.append(currentTime)

                    resp.extend(self.format_kv_pair(k, v) for k, v in mo_attribute_data.items() if v is not None)
                    resp.extend(self.format_kv_pair(k, v) for k, v in attribute_data.items() if v is not None)

                    resp.append(self.format_kv_pair("apic_host", apic_host))
                    resp.append(self.format_kv_pair("actual_host", apic_host))
                    resp.append(self.format_kv_pair("component", apic_class))

                    events_ingested_count += 1
                    event = "\t".join(resp)
                    event = event.replace('\n', '').replace('\r', '')
                    event = smi.Event(data=event, index=index, sourcetype=sourcetype, unbroken=True)
                    ew.write_event(event)

        else:
            resp.extend(self.format_kv_pair(k, v) for k, v in attribute_data.items() if v is not None)

            resp.append(self.format_kv_pair("apic_host", apic_host))
            resp.append(self.format_kv_pair("actual_host", apic_host))
            resp.append(self.format_kv_pair("component", apic_class))

            event = "\t".join(resp)
            event = event.replace('\n', '').replace('\r', '')
            event = smi.Event(data=event, index=index, sourcetype=sourcetype, unbroken=True)
            ew.write_event(event)
            events_ingested_count += 1

        return events_ingested_count

    def get_mo_data(self, session, additional_filters, mo_support_object, host_without_port, ew, logger, index):
        mo_support_objects = mo_support_object.strip()
        mo_support_objects = mo_support_objects.split(" ")
        mo_pg_sz = pagelimit
        if additional_filters and additional_filters.strip():
            additional_filters = additional_filters.strip(' ?&')
            additional_filters = '&' + additional_filters
            additional_filters = re.sub(r'([&?])page=[^&]*', '', additional_filters)
            params_breakdown = parse_qs(additional_filters)
            mo_page_size = int(params_breakdown.get('page-size', [None])[0]) if 'page-size' in params_breakdown else None
            if mo_page_size:
                mo_pg_sz = mo_page_size
            else:
                mo_pg_sz = pagelimit
            additional_filters = re.sub(r'([&?])page-size=[^&]*', '', additional_filters)
            if not additional_filters.strip('&'):
                additional_filters = ''
            else:
                additional_filters = additional_filters.strip(' ?&')
        else:
            additional_filters = ''
        if additional_filters:
            additional_filters = '&' + additional_filters
        for original_mo_support_object in mo_support_objects:
            try:
                mo_pg = 0
                events_ingested_count = 0
                mo_support_object = original_mo_support_object.strip('/')
                if mo_support_object:
                    while True:
                        mo_url = (
                            f"/api/mo/{mo_support_object}.json?page={mo_pg}&page-size={mo_pg_sz}{additional_filters}"
                        )
                        logger.debug(f"Target URL: {mo_url}")
                        moret = session.get(mo_url, timeout=timeout_val)
                        if moret.status_code != 200:
                            logger.error(f"ACI Error: HTTP Query={mo_url} ERROR={moret.reason}")
                            logger.error(f"ACI Error: Response Content:{moret.content}")
                            break
                        else:
                            modata = moret.json().get("imdata", [])
                            if not modata:
                                break
                            mo_pg += 1
                            events_ingested_count += self.ingest_mo_data_in_splunk(
                                modata, host_without_port, ew, index
                            )
                    logger.info(f"Collected a total of {events_ingested_count} events "
                                f"for {mo_support_object} distinguished name.")
            except Exception as e:
                logger.error(f"ACI Error: Failed to fetch distinguished name data for {original_mo_support_object} "
                            f"from host: {host_without_port}. Error: {str(e)}.")
                continue      

    def get_big_dataset_result(self, session, apic_class, apic_host, logger, session_key, index, sourcetype, ew, inp_name, acc_name, host=None, additional_filters=None):
        events_ingested_count = 0
        check_point_name = acc_name + "_" + inp_name + "_" + apic_class
        logger.info("Fetching checkpoint value.")
        checkpoint_collection = checkpointer.KVStoreCheckpointer(
            ACI_CHKPT_COLLECTION, session_key, 'cisco_dc_networking_app_for_splunk'
        )
        scaleStart = checkpoint_collection.get(check_point_name)
        if not scaleStart:
            old_chkpt_key = inp_name + "_" + apic_host.replace('.', '_') + "_" + apic_class + "_LastTransactionTime"
            scaleStart = checkpoint_collection.get(old_chkpt_key)

        try:
            pg_size = pagelimit
            if additional_filters and additional_filters.strip():
                additional_filters = additional_filters.strip(' ?&')
                additional_filters = '&' + additional_filters
                additional_filters = re.sub(r'([&?])page=[^&]*', '', additional_filters)
                params_breakdown = parse_qs(additional_filters)
                page_size = int(params_breakdown.get('page-size', [None])[0]) if 'page-size' in params_breakdown else None
                if page_size:
                    pg_size = page_size
                else:
                    pg_size = pagelimit
                additional_filters = re.sub(r'([&?])page-size=[^&]*', '', additional_filters)
                if not additional_filters.strip('&'):
                    additional_filters = ''
                else:
                    additional_filters = additional_filters.strip(' ?&')
            else:
                additional_filters = ''

            if scaleStart:
                pg_val = 0
                logger.info(f"Successfully fetched checkpoint value: {scaleStart}")
                if additional_filters:
                    additional_filters = '&' + additional_filters
                while True:
                    query_url = (
                        f'/api/node/class/{apic_class}.json?query-target-filter=gt'
                        f'({apic_class}.created,"{quote_plus(scaleStart, safe=":")}")'
                        f'&page={pg_val}&page-size={pg_size}{additional_filters}'
                    )
                    logger.debug(f"Target URL: {query_url}")
                    try:
                        ret = session.get(query_url, timeout=timeout_val)
                    except Exception as e:
                        logger.error(
                            f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}. "
                            f"Query URL: {query_url}. Error: {str(e)}"
                        )
                        return events_ingested_count
                    if ret.status_code != 200:
                        logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                        logger.error(f"ACI Error: Response Content:{ret.content}")
                        return events_ingested_count
                    else:
                        data = ret.json().get("imdata", [])
                        if not data:
                            break
                        pg_val += 1
                        if host:
                            events_ingested_count += self.ingest_properties_data_to_splunk(
                                data, apic_class, apic_host, index, sourcetype, ew, dest=str(host)
                            )
                        else:
                            events_ingested_count += self.ingest_properties_data_to_splunk(
                                data, apic_class, apic_host, index, sourcetype, ew
                            )

            else:
                # Storing current datetimestamp to a file
                # datetimestamp format: "created":"2016-01-07T10:06:32.622+00:00"
                logger.info("No checkpoint value found.")
                query_url = "/api/node/mo/info.json"
                try:
                    ret = session.get(query_url, timeout=timeout_val)
                except Exception as e:
                    logger.error(
                        f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}. "
                        f"Query URL: {query_url}. Error: {str(e)}"
                    )
                    return events_ingested_count
                if not ret.ok:
                    logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                    logger.error(f"ACI Error: Response Content:{ret.content}")
                    return events_ingested_count

                tdata = ret.json().get("imdata", [])
                for tobject_data in tdata:
                    for t in tobject_data:
                        attribute_data = tobject_data[t]["attributes"]

                datetime_stamp = attribute_data["currentTime"]

                checkpoint_collection = checkpointer.KVStoreCheckpointer(
                    ACI_CHKPT_COLLECTION, session_key, 'cisco_dc_networking_app_for_splunk'
                )
                logger.info(f"Saving the checkpoint value as: {datetime_stamp}")
                checkpoint_collection.update(check_point_name, datetime_stamp)
                logger.info("Successfully saved the checkpoint.")

                query_url = f"/api/node/class/{apic_class}.json?rsp-subtree-include=count"
                try:
                    ret = session.get(query_url, timeout=timeout_val)
                except Exception as e:
                    logger.error(
                        f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}. "
                        f"Query URL: {query_url}. Error: {str(e)}"
                    )
                    return events_ingested_count
                if ret.status_code != 200:
                    logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                    logger.error(f"ACI Error: Response Content:{ret.content}")
                    return events_ingested_count

                data = ret.json().get("imdata", [])
                for object_data in data:
                    for k in object_data:
                        attribute_data = object_data[k]["attributes"]

                totalObjCount = int(attribute_data["count"])

                if totalObjCount < 99000:
                    pg_val = 0
                    if additional_filters:
                        additional_filters = '&' + additional_filters
                    # Kept 99000 b'coz don't what to cut too close to 1 lakh objects
                    while True:
                        query_url = f"/api/node/class/{apic_class}.json?page={pg_val}&page-size={pg_size}{additional_filters}"
                        logger.debug(f"Target URL: {query_url}")
                        try:
                            ret = session.get(query_url, timeout=timeout_val)
                        except Exception as e:
                            logger.error(
                                f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}. "
                                f"Query URL: {query_url}. Error: {str(e)}"
                            )
                            return events_ingested_count
                        if ret.status_code != 200:
                            logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                            logger.error(f"ACI Error: Response Content:{ret.content}")
                            return events_ingested_count
                        else:
                            data = ret.json().get("imdata", [])
                            if not data:
                                break
                            pg_val += 1
                            if host:
                                events_ingested_count += self.ingest_properties_data_to_splunk(
                                    data, apic_class, apic_host, index, sourcetype, ew, dest=str(host)
                                )
                            else:
                                events_ingested_count += self.ingest_properties_data_to_splunk(
                                    data, apic_class, apic_host, index, sourcetype, ew
                                )

                else:
                    # Create datetimestamp i.e in format: "created":"2016-01-07T10:06:32.622+00:00"
                    # time = datetime.now().strftime('T%H:%M:%S.%f')[:-3]
                    onlytime = datetime_stamp.split("T")[1]

                    timestamp = "T" + onlytime

                    no_of_days = 1  # The interval period to get data is been kept as 1 day
                    loop = 60  # Max of last 60 days records will be fetched.
                    start = 0

                    present = datetime.now().strftime("%Y-%m-%d")
                    scaleEnd = present + timestamp

                    previous = date.today() - timedelta(days=no_of_days)
                    older = previous.strftime("%Y-%m-%d")
                    scaleStart = older + timestamp

                    if additional_filters:
                        additional_filters = '&' + additional_filters

                    while loop > start:
                        pg_val = 0
                        while True:
                            query_url = (
                                f'/api/node/class/{apic_class}.json?query-target-filter=and'
                                f'(gt({apic_class}.created,"{quote_plus(scaleStart, safe=":")}")'
                                f',lt({apic_class}.created,"{quote_plus(scaleEnd, safe=":")}"))'
                                f'&page={pg_val}&page-size={pg_size}{additional_filters}'
                            )
                            logger.debug(f"Target URL: {query_url}")
                            try:
                                ret = session.get(query_url, timeout=timeout_val)
                            except Exception as e:
                                logger.error(
                                    f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}."
                                    f"Query URL: {query_url}. Error: {str(e)}"
                                )
                                return events_ingested_count
                            if ret.status_code != 200:
                                logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                                logger.error(f"ACI Error: Response Content:{ret.content}")
                                return events_ingested_count
                            else:
                                data = ret.json().get("imdata", [])
                                if not data:
                                    break
                                pg_val += 1
                                if host:
                                    events_ingested_count += self.ingest_properties_data_to_splunk(
                                        data, apic_class, apic_host, index, sourcetype, ew, dest=str(host)
                                    )
                                else:
                                    events_ingested_count += self.ingest_properties_data_to_splunk(
                                        data, apic_class, apic_host, index, sourcetype, ew
                                    )

                        scaleEnd = scaleStart
                        no_of_days = no_of_days + 1  # +1 day limit
                        previous = date.today() - timedelta(days=no_of_days)
                        older = previous.strftime("%Y-%m-%d")
                        scaleStart = older + timestamp

                        start = start + 1

            # Storing current datetimestamp to a file
            query_url = "/api/node/mo/info.json"
            try:
                ret = session.get(query_url, timeout=timeout_val)
            except Exception as e:
                logger.error(
                    f"ACI Error: get_big_dataset_result Failed to fetch data from host: {apic_host}. "
                    f"Query URL: {query_url}. Error: {str(e)}"
                )
                return events_ingested_count
            if not ret.ok:
                logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                logger.error(f"ACI Error: Response Content:{ret.content}")
                return events_ingested_count

            tdata = ret.json().get("imdata", [])
            for tobject_data in tdata:
                for t in tobject_data:
                    attribute_data = tobject_data[t]["attributes"]

            datetime_stamp = attribute_data["currentTime"]
            checkpoint_collection = checkpointer.KVStoreCheckpointer(
                ACI_CHKPT_COLLECTION, session_key, 'cisco_dc_networking_app_for_splunk'
            )
            logger.info(f"Saving the checkpoint value as: {datetime_stamp}")
            checkpoint_collection.update(check_point_name, datetime_stamp)
            logger.info("Successfully saved the checkpoint.")
        except Exception as e:
            return events_ingested_count
        return events_ingested_count

    def ingest_properties_data_to_splunk(self, data, apic_class, apic_host, index, sourcetype, ew, **kwargs):
        global common_host
        events_ingested = 0
        for object_data in data:
            attribute_data = object_data[apic_class]["attributes"]
            resp = []
            currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
            resp.append(currentTime)
            resp.extend(self.format_kv_pair(k, v) for k, v in attribute_data.items() if v is not None)
            
            resp.append(self.format_kv_pair("apic_host", common_host))
            resp.append(self.format_kv_pair("actual_host", apic_host))
            resp.append(self.format_kv_pair("component", apic_class))
            
            if kwargs:
                resp.extend(self.format_kv_pair(k, v) for k, v in kwargs.items() if v is not None)
            
            event = "\t".join(resp)
            event = event.replace('\n', '').replace('\r', '')
            event = smi.Event(data=event, index=index, sourcetype=sourcetype, unbroken=True)
            ew.write_event(event)
            events_ingested += 1

        return events_ingested

    def get_authentication_data(self, session, classes, apic_host, ew, logger, session_key, index, inp_name, acc_name):
        classes = classes.strip()
        classes = classes.split(" ")
        for apic_class in classes:
            events_ingested_count = 0
            if apic_class == "aaaSessionLR":
                # this check is for aaaSessionLR class query may return more than 100k Objects
                try:
                    events_ingested_count += self.get_big_dataset_result(
                        session,
                        apic_class,
                        apic_host,
                        logger,
                        session_key,
                        index,
                        "cisco:dc:aci:authentication",
                        ew,
                        inp_name,
                        acc_name,
                        host=apic_host
                    )
                except Exception as e:
                    logger.error(
                        f"ACI Error: get_authentication_data Failed to fetch data from host: {apic_host} "
                        f"for class: {apic_class}. Error: {str(e)}. Skipping this class."
                    )
            else:
                page = 0
                counter = True
                while counter:
                    query_url = f"/api/node/class/{apic_class}.json?page={page}&page-size={pagelimit}"
                    try:
                        ret = session.get(query_url, timeout=timeout_val)
                    except Exception as e:
                        logger.error(
                            f"ACI Error: get_authentication_data Failed to fetch data from host: {apic_host} "
                            f"for class: {apic_class}. Error: {str(e)}. Skipping this class."
                        )
                        break
                    if ret.status_code != 200:
                        logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                        logger.error(f"ACI Error: Response Content:{ret.content}")
                        logger.error(f"Error while collecting data for class: {apic_class}. Skipping this class.")
                        break
                    else:
                        page += 1
                        data = ret.json().get("imdata", [])
                        if data == []:
                            counter = False
                        else:
                            events_ingested_count += self.ingest_properties_data_to_splunk(
                                data, apic_class, apic_host, index, "cisco:dc:aci:authentication", ew
                            )

            logger.info(f"Collected a total of {events_ingested_count} events for {apic_class} class.")

    def get_class_data(self, session, classes, apic_host, ew, logger, session_key, index, inp_name, acc_name, additional_filters=None):
        classes = classes.strip()
        classes = classes.split(" ")
        api_page_size = pagelimit
        for apic_class in classes:
            apic_class = apic_class.strip()
            events_ingested_count = 0
            if apic_class == "faultRecord" or apic_class == "aaaModLR" or apic_class == "eventRecord":
                try:
                    events_ingested_count += self.get_big_dataset_result(
                        session, apic_class, apic_host, logger, session_key, index, "cisco:dc:aci:class", ew, inp_name, acc_name, additional_filters=additional_filters
                    )
                except Exception as e:
                    logger.error(
                        f"ACI Error: get_class_data Failed to fetch data from host: {apic_host} "
                        f"for class: {apic_class}. Error: {str(e)}. Skipping this class."
                    )
            elif apic_class == "fvCEp":
                self.get_stats_data(session, apic_class, apic_host, ew, logger, index, component_type="_getClassInfo", additional_filters=additional_filters)
            else:
                page = 0
                counter = True
                if additional_filters and additional_filters.strip():
                    additional_filters = additional_filters.strip(' ?&')
                    additional_filters = '&' + additional_filters
                    additional_filters = re.sub(r'([&?])page=[^&]*', '', additional_filters)
                    params_breakdown = parse_qs(additional_filters)
                    page_size = int(params_breakdown.get('page-size', [None])[0]) if 'page-size' in params_breakdown else None
                    if page_size:
                        api_page_size = page_size
                    else:
                        api_page_size = pagelimit
                    additional_filters = re.sub(r'([&?])page-size=[^&]*', '', additional_filters)
                else:
                    additional_filters = ''
                while counter:
                    query_url = f"/api/node/class/{apic_class}.json?page={page}&page-size={api_page_size}{additional_filters}"
                    logger.debug(f"Target URL: {query_url}")
                    try:
                        ret = session.get(query_url, timeout=timeout_val)
                    except Exception as e:
                        logger.error(
                            f"ACI Error: get_class_data Failed to fetch data from host: {apic_host} "
                            f"for class: {apic_class}. Error: {str(e)}. Skipping this class."
                        )
                        break
                    if ret.status_code != 200:
                        logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                        logger.error(f"ACI Error: Response Content:{ret.content}")
                        logger.error(f"Error while collecting data for class: {apic_class}. Skipping this class.")
                        break
                    page += 1
                    data = ret.json().get("imdata", [])
                    if data == []:
                        counter = False
                    else:
                        events_ingested_count += self.ingest_properties_data_to_splunk(
                            data, apic_class, apic_host, index, "cisco:dc:aci:class", ew
                        )

            logger.info(f"Collected a total of {events_ingested_count} events for {apic_class} class.")

    def get_stats_data(self, session, classes, apic_host, ew, logger, index, component_type="_getStats", additional_filters=None):
        classes = classes.strip()
        classes = classes.split(" ")
        global common_host
        for apic_class in classes:
            events_ingested_count = 0
            page = 0
            counter = True
            if apic_class != "fvCEp":
                while counter:
                    query_url = f"/api/node/class/{apic_class}.json?page={page}&page-size={pagelimit}"
                    try:
                        ret = session.get(query_url, timeout=timeout_val)
                    except Exception as e:
                        logger.error(
                            f"ACI Error: get_stats_data Failed to fetch data from host: {apic_host} for "
                            f"class: {apic_class}. Error: {str(e)}. Skipping this class."
                        )
                        break
                    if ret.status_code != 200:
                        logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                        logger.error(f"ACI Error: Response Content:{ret.content}")
                        logger.error(f"Error while collecting data for class: {apic_class}. Skipping this class.")
                        break

                    data = ret.json().get("imdata", [])
                    page += 1
                    if data == []:
                        counter = False
                    else:
                        for object_data in data:
                            for obj in object_data:
                                attribute_data = object_data[obj]["attributes"]
                                dn = attribute_data["dn"]
                                pg_stats = 0
                                pg_size_stats = pagelimit
                                while True:
                                    moquery_url = (
                                        f"/api/mo/{dn}.json?rsp-subtree-include=stats,no-scoped"
                                        f"&page={pg_stats}&page-size={pg_size_stats}"
                                    )
                                    try:
                                        moret = session.get(moquery_url, timeout=timeout_val)
                                    except Exception as e:
                                        logger.error(
                                            f"ACI Error: get_stats_data Failed to fetch data from host: {apic_host} "
                                            f"for Query URL: {moquery_url}. Error: {str(e)}. Skipping this class."
                                        )
                                        break
                                    if moret.status_code != 200:
                                        logger.error(f"ACI Error: HTTP Query={moquery_url} ERROR={moret.reason}")
                                        logger.error(f"ACI Error: Response Content:{moret.content}")
                                        break
                                    else:
                                        modata = moret.json().get("imdata", [])
                                        if not modata:
                                            if pg_stats == 0:
                                                events_ingested_count += self.ingest_data_in_splunk(
                                                    modata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:stats", index
                                                )
                                            break
                                        pg_stats += 1
                                        events_ingested_count += self.ingest_data_in_splunk(
                                            modata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:stats", index
                                        )
            else:
                source_type = ''
                if component_type == "_getClassInfo":
                    api_page_size = pagelimit
                    if additional_filters and additional_filters.strip():
                        additional_filters = additional_filters.strip(' ?&')
                        additional_filters = '&' + additional_filters
                        additional_filters = re.sub(r'([&?])page=[^&]*', '', additional_filters)
                        params_breakdown = parse_qs(additional_filters)
                        page_size = int(params_breakdown.get('page-size', [None])[0]) if 'page-size' in params_breakdown else None
                        if page_size:
                            api_page_size = page_size
                        else:
                            api_page_size = pagelimit
                        additional_filters = re.sub(r'([&?])page-size=[^&]*', '', additional_filters)
                    else:
                        additional_filters = ''
                while counter:
                    if component_type == "_getStats":
                        source_type = "cisco:dc:aci:stats"
                        query_url = (
                            f"/api/node/class/{apic_class}.json?rsp-subtree=children&rsp-subtree-class=fvRsCEpToPathEp,fvIp"
                            f"&page={page}&page-size={pagelimit}"
                        )
                    else:
                        source_type = "cisco:dc:aci:class"
                        query_url = (
                            f"/api/node/class/{apic_class}.json?rsp-subtree=children&rsp-subtree-class=fvIp"
                            f"&page={page}&page-size={api_page_size}{additional_filters}"
                        )
                    try:
                        ret = session.get(query_url, timeout=timeout_val)
                    except Exception as e:
                        logger.error(
                            f"ACI Error: {component_type} Failed to fetch data from host: {apic_host} for class: {apic_class}. "
                            f"Error: {str(e)}. Skipping this class."
                        )
                        break
                    page += 1
                    if ret.status_code != 200:
                        logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                        logger.error(f"ACI Error: Response Content:{ret.content}")
                        logger.error(f"Error while collecting data for class: {apic_class}. Skipping this class.")
                        break

                    pdata = ret.json().get("imdata", [])
                    if pdata == []:
                        counter = False
                    else:
                        for pobject_data in pdata:
                            for pobj in pobject_data:
                                resp = []
                                currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
                                resp.append(currentTime)

                                attribute_data = pobject_data[pobj].get("attributes", {})
                                cdata = pobject_data[pobj].get("children", [])
                                resp.extend(self.format_kv_pair(k, v) for k, v in attribute_data.items() if v is not None)
                                
                                for cobject_data in cdata:
                                    for cobj in cobject_data:
                                        children_data = cobject_data[cobj]["attributes"]
                                        if cobj == "fvIp":
                                            resp.append(self.format_kv_pair("addr", children_data.get("addr", "")))
                                        else:
                                            resp.extend(self.format_kv_pair(k, v) for k, v in children_data.items() if v is not None)

                                resp.append(self.format_kv_pair("apic_host", common_host))
                                resp.append(self.format_kv_pair("actual_host", apic_host))
                                resp.append(self.format_kv_pair("component", apic_class))
                                event = "\t".join(resp)
                                event = event.replace('\n', '').replace('\r', '')
                                event = smi.Event(
                                    data=event, index=index, sourcetype=source_type, unbroken=True
                                )
                                ew.write_event(event)
                                events_ingested_count += 1

            logger.info(f"Collected a total of {events_ingested_count} events for {apic_class} class.")

    def get_health_data(self, session, classes, apic_host, ew, logger, index):
        classes = classes.strip()
        classes = classes.split(" ")
        for apic_class in classes:
            page = 0
            counter = True
            events_ingested_count = 0
            while counter:
                query_url = f"/api/node/class/{apic_class}.json?page={page}&page-size={pagelimit}"
                try:
                    ret = session.get(query_url, timeout=timeout_val)
                except Exception as e:
                    logger.error(
                        f"ACI Error: get_health_data Failed to fetch data from host: {apic_host} "
                        f"for class: {apic_class}. Error: {str(e)}. Skipping this class."
                    )
                    break
                page += 1
                if ret.status_code != 200:
                    logger.error(f"ACI Error: HTTP Query={query_url} ERROR={ret.reason}")
                    logger.error(f"ACI Error: Response Content: {ret.content}")
                    logger.error(f"Error while collecting data for class: {apic_class}. Skipping this class.")
                    break

                data = ret.json()["imdata"]
                if data == []:
                    counter = False
                    break
                for object_data in data:
                    for obj in object_data:
                        attribute_data = object_data[obj]["attributes"]
                        dn = attribute_data["dn"]

                        # Health Details
                        hpg = 0
                        hpgsz = pagelimit
                        while True:
                            if apic_class == "fabricNode":
                                hquery_url = f"/api/mo/{dn}/sys.json?rsp-subtree-include=health,no-scoped&page={hpg}&page-size={hpgsz}"
                            else:
                                hquery_url = f"/api/mo/{dn}.json?rsp-subtree-include=health,no-scoped&page={hpg}&page-size={hpgsz}"
                            logger.debug("Target URL: {}".format(hquery_url))
                            try:
                                healthret = session.get(hquery_url, timeout=timeout_val)
                                if healthret.status_code != 200:
                                    logger.error(f"ACI Error: HTTP Query={hquery_url} ERROR={healthret.reason}")
                                    logger.error(f"ACI Error: Response Content: {healthret.content}")
                                    break
                                else:
                                    healthdata = healthret.json().get("imdata", [])
                                    if not healthdata:
                                        if hpg == 0:
                                            events_ingested_count += self.ingest_data_in_splunk(
                                                healthdata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:health", index
                                            )
                                        break
                                    hpg += 1
                                    events_ingested_count += self.ingest_data_in_splunk(
                                        healthdata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:health", index
                                    )
                            except Exception as e:
                                logger.error(
                                    f"ACI Error: get_health_data Failed to fetch data from host: {apic_host} "
                                    f"Query URL: {hquery_url}. Error: {str(e)}"
                                )
                                break

                        fpg = 0
                        fpgsz = pagelimit
                        # fault details
                        while True:
                            if apic_class == "fabricNode":
                                fq_url = (
                                    f"/api/mo/{dn}/sys.json?rsp-subtree-include=faults,no-scoped&query-target=subtree&page={fpg}&page-size={fpgsz}"
                                )
                            else:
                                fq_url = f"/api/mo/{dn}.json?rsp-subtree-include=faults,no-scoped&query-target=subtree&page={fpg}&page-size={fpgsz}"
                            logger.debug("Target URL: {}".format(fq_url))
                            try:
                                faultret = session.get(fq_url, timeout=timeout_val)
                                if faultret.status_code != 200:
                                    logger.error(f"ACI Error: HTTP Query={fq_url} ERROR={faultret.reason}")
                                    logger.error(f"ACI Error: Response Content: {faultret.content}")
                                    break
                                else:
                                    faultdata = faultret.json().get("imdata", [])
                                    if not faultdata:
                                        if fpg == 0:
                                            events_ingested_count += self.ingest_data_in_splunk(
                                                faultdata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:health", index
                                            )
                                        break
                                    fpg += 1
                                    events_ingested_count += self.ingest_data_in_splunk(
                                        faultdata, attribute_data, apic_class, apic_host, ew, "cisco:dc:aci:health", index
                                    )
                            except Exception as e:
                                logger.error(
                                    f"ACI Error: get_health_data Failed to fetch data from host: {apic_host} "
                                    f"Query URL: {fq_url}. Error: {str(e)}"
                                )
                                break

            logger.info(f"Collected a total of {events_ingested_count} events for {apic_class} class.")

    def collect_aci_data(self, *args):
        argv = args[0]
        classes = args[1]
        host = args[2]
        session = args[3]
        username = args[4]
        ew = args[5]
        logger = args[6]
        session_key = args[7]
        index = args[8]
        inp_name = args[9]
        mo_support_object = args[10]
        additional_filters = args[11]
        acc_name = args[12]
        resp = []
        currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
        resp.append(currentTime)
        cloud = False
        global common_host
        common_host = host
        try:
            # Check for C-APIC
            c_apic = session.get(
                '/api/node/class/fabricNode.json?query-target-filter=eq(fabricNode.role,"controller")',
                timeout=timeout_val,
            )
            if c_apic.status_code == 200:
                if not c_apic.json()["imdata"]:
                    cloud = True
                elif str(c_apic.json()["imdata"][0]["fabricNode"]["attributes"]["nodeType"]) == "cloud":
                    cloud = True
                else:
                    cloud = False

        except requests.exceptions.ConnectionError:
            if "cert_based_auth" in args:
                return
        except Exception as e:
            logger.error(
                f"ACI Error: Could not verify APIC node type for cloud for host={str(host)}, Error={str(e)}"
            )
            pass

        host_without_port = host
        credential_info = [
            self.format_kv_pair("apic_host", common_host),
            self.format_kv_pair("actual_host", host_without_port),
            self.format_kv_pair("Username", username),
            self.format_kv_pair("component", "credentials"),
        ]
        if cloud:
            credential_info.append(self.format_kv_pair("type", "cloud"))
        
        resp.extend(credential_info)

        src_type = None
        if argv in ["health", "fex"]:
            src_type = "cisco:dc:aci:health"
            if cloud:
                classes = classes + " cloudApp cloudExtEPg cloudEPg fvCtx"
            self.get_health_data(session, classes, host_without_port, ew, logger, index)
        elif argv in ["authentication"]:
            src_type = "cisco:dc:aci:authentication"
            self.get_authentication_data(session, classes, host_without_port, ew, logger, session_key, index, inp_name, acc_name)
        elif argv in ["stats"]:
            src_type = "cisco:dc:aci:stats"
            if cloud:
                classes = classes + " fvCtx"
            self.get_stats_data(session, classes, host_without_port, ew, logger, index)
        elif argv in ["classInfo", "microsegment"]:
            src_type = "cisco:dc:aci:class"
            if cloud:
                classes = (
                    classes + 
                    " cloudZone cloudCtxProfile vzBrCP cloudRegion hcloudCsr hcloudEndPoint "
                    "hcloudInstance vnsAbsGraph cloudLB hcloudCtx"
                )
            self.get_class_data(session, classes, host_without_port, ew, logger, session_key, index, inp_name, acc_name, additional_filters)
        elif argv == "managed_objects":
            src_type = "cisco:dc:aci:managed_object"
            self.get_mo_data(session, additional_filters, mo_support_object, host_without_port, ew, logger, index)
        else:
            logger.error(
                "ACI Error: Please use one of the following input type: "
                "health, stats, authentication, classInfo, fex, microsegment, managed objects"
            )
            return
        if src_type:
            event = "\t".join(resp)
            event = smi.Event(data=event, index=index, sourcetype=src_type, unbroken=True)
            ew.write_event(event)
        session.close()

    def get_credentials(self, session_key, account_name, logger):
        """Provide credentials of the configured account.

        Args:
            session_key: current session session key
            logger: log object

        Returns:
            Dict: A Dictionary having account information.
        """
        try:
            cfm = conf_manager.ConfManager(
                session_key,
                import_declare_test.ta_name,
                realm=f"__REST_CREDENTIAL__#{import_declare_test.ta_name}"
                "#configs/conf-cisco_dc_networking_app_for_splunk_aci_account"
            )
            account_conf_file = cfm.get_conf("cisco_dc_networking_app_for_splunk_aci_account")
            aci_acc_creds = account_conf_file.get(account_name)
        except Exception:
            logger.error(f"Error in fetching account details. {traceback.format_exc()}")
            return None
        return aci_acc_creds

    def validate_input(self, definition: smi.ValidationDefinition):
        pass

    def fetch_aci_data(self, input_info, acc, session_key, smi, ew, logger, input_name_for_log):
        logger.info(f"Starting data collection for account {acc}.")
        thread_name = threading.current_thread().name
        logger.debug(
            f"ThreadPoolExecutor thread '{thread_name}' is associated with account: '{acc}'. "
            f"Check logs with thread name '{thread_name}' to debug issues related to '{acc}' account."
        )
        index = input_info['index']
        ac_creds = self.get_credentials(session_key, acc, logger)
        if not ac_creds:
            logger.error(f"Unable to fetch account named: {acc}. Exiting data collection.")
            return
        host_list = ac_creds.get('apic_hostname')
        apic_auth_type = ac_creds.get('apic_authentication_type')
        first_host = None
        if host_list:
            host_list = host_list.split(",")
            first_host = host_list[0]
            if first_host:
                first_host = first_host.strip()
        apicUrl = "https://" + first_host
        username = ac_creds.get('apic_username')
        proxy_data = proxy.get_proxies(ac_creds)
        if proxy_data:
            logger.info("Proxy is enabled.")
        else:
            logger.info("Proxy is disabled.")
        if apic_auth_type in ['password_authentication', 'remote_user_authentication']:
            if apic_auth_type == 'remote_user_authentication':
                logger.info("Collecting data using Remote Based Authentication.")
                username = "apic#" + ac_creds.get('apic_login_domain') + '\\\\' + ac_creds.get('apic_username')
            else:
                logger.info("Collecting data using Password Based Authentication.")
            password = ac_creds.get('apic_password')
            session = aci.Session(
                apicUrl,
                username,
                password,
                verify_ssl=get_sslconfig(session_key),
                proxies=proxy.get_proxies(ac_creds),
                logger=logger,
            )
            response = session.login(timeout=timeout_val)
            if not response.ok:
                logger.error(f"Could not login to APIC:{first_host}, Username:{username}")
                if len(host_list) > 1:
                    other_hosts = host_list[1:]
                    for each in other_hosts:
                        try:
                            each = each.strip()
                            apic_url = "https://" + each
                            session = aci.Session(
                                apic_url,
                                username,
                                password,
                                verify_ssl=get_sslconfig(session_key),
                                proxies=proxy.get_proxies(ac_creds),
                                logger=logger,
                            )
                            resp = session.login(timeout=timeout_val)
                            if resp.ok:
                                self.collect_aci_data(
                                    input_info.get('apic_input_type'),
                                    input_info.get('apic_arguments'),
                                    each,
                                    session,
                                    username,
                                    ew,
                                    logger,
                                    session_key,
                                    index,
                                    input_name_for_log,
                                    input_info.get('mo_support_object'),
                                    input_info.get('aci_additional_parameters'),
                                    acc
                                )
                                break
                        except Exception as err:
                            logger.error(f"An error occured in collecting data. Host: {each}. Error: {str(err)}")
                            continue
            else:
                self.collect_aci_data(input_info.get('apic_input_type'), input_info.get('apic_arguments'), first_host,
                                    session, username, ew, logger, session_key, index, input_name_for_log, input_info.get('mo_support_object'),
                                    input_info.get('aci_additional_parameters'), acc)
        else:
            logger.info("Collecting data using Certificate Based Authentication.")
            cert_name = ac_creds.get('apic_certificate_name')
            cert_private_key_path = ac_creds.get('apic_certificate_path')
            session = aci.Session(
                apicUrl,
                username,
                cert_name=cert_name,
                key=cert_private_key_path,
                verify_ssl=get_sslconfig(session_key),
                proxies=proxy.get_proxies(ac_creds),
                logger=logger,
            )
            response = session.login(timeout=timeout_val)
            if not response.ok:
                logger.error(f"Could not login to APIC:{first_host}, Username:{username}")
                if len(host_list) > 1:
                    other_hosts = host_list[1:]
                    for each in other_hosts:
                        try:
                            each = each.strip()
                            apic_url = "https://" + each
                            session = aci.Session(
                                apic_url,
                                username,
                                cert_name=cert_name,
                                key=cert_private_key_path,
                                verify_ssl=get_sslconfig(session_key),
                                proxies=proxy.get_proxies(ac_creds),
                                logger=logger,
                            )
                            resp = session.login(timeout=timeout_val)
                            if resp.ok:
                                self.collect_aci_data(
                                    input_info.get('apic_input_type'),
                                    input_info.get('apic_arguments'),
                                    each,
                                    session,
                                    username,
                                    ew,
                                    logger,
                                    session_key,
                                    index,
                                    input_name_for_log,
                                    input_info.get('mo_support_object'),
                                    input_info.get('aci_additional_parameters'),
                                    acc,
                                    "cert_based_auth"
                                )
                                break
                        except Exception as err:
                            logger.error(f"An error occured in collecting data. Host: {each}. Error: {str(err)}")
                            continue
            else:
                self.collect_aci_data(input_info.get('apic_input_type'), input_info.get('apic_arguments'),
                                        first_host, session, username, ew, logger, session_key, index,
                                        input_name_for_log, input_info.get('mo_support_object'),
                                        input_info.get('aci_additional_parameters'), acc, "cert_based_auth")

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter):
        input_items = [{'count': len(inputs.inputs)}]
        for input_name, input_item in inputs.inputs.items():
            input_item['name'] = input_name
            input_items.append(input_item)
        input_name = input_items[1]['name']
        input_name_for_log = input_name.split("//")[1]
        logger = log.get_logger(f"cisco_dc_aci_{input_name_for_log}")
        meta_configs = self._input_definition.metadata
        session_key = meta_configs['session_key']

        try:
            validation_success = aci_input_validator(input_items[1], logger)
            if not validation_success:
                return
            logger.info("Starting data collection.")
            aci_accounts = input_items[1]["apic_account"].split(",")
            with concurrent.futures.ThreadPoolExecutor(max_workers=consts.MAX_THREADS_MULTI_ACC) as executor:
                futures = []
                for account_name in aci_accounts:
                    future = executor.submit(self.fetch_aci_data, input_items[1], account_name, session_key, smi, ew, logger, input_name_for_log)
                    futures.append(future)
                for future in futures:
                    future.result()
            logger.info("Data collection ended.")
            
        except Exception as err:
            logger.error(f"An error occured while collecting data. Error: {str(err)}")
            return


if __name__ == '__main__':
    exit_code = CISCO_NEXUS_ACI().run(sys.argv)
    sys.exit(exit_code)
