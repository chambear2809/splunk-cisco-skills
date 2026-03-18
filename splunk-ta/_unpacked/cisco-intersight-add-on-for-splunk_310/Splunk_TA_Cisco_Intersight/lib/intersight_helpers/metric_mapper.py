"""This module provides helper functions specific for metric input."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
from intersight_helpers import metric_mapper_network
import logging


class MetricMapper:
    """Mapper function for Metrics Dimension collection."""

    def __init__(self, logger: logging.Logger) -> None:
        """
        Init function for class MetricHelper.

        Args:
            logger (logging.Logger): Logger instance used for logging messages.
        """
        self.logger = logger

    def create_mergeable_data(self, kwargs: dict) -> dict:
        """
        Format data in a predefined collection format based on the object type.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - object_type (str): The type of the object for which data needs to be formatted.
                - event (dict): The event data containing information to be processed.
                - account_name (str): The name of the account associated with the event.
                - id_chunk (list): A list of IDs used to help identify the domain.

        Returns:
            dict: A dictionary of formatted data if the object_type is supported, otherwise an empty dictionary.

        Raises:
            ValueError: If the object_type is not supported.
        """
        object_type = kwargs.get("object_type")
        event = kwargs.get("event")
        account_name = kwargs.get("account_name")
        id_chunk = kwargs.get("id_chunk")
        domain_ids = kwargs.get("domain_ids")

        # Define the mapping for metrics dimensions based on object type
        # Map of object types to their corresponding collection format using lambda functions
        # The lambda functions are used to extract and modify the values to our needed format
        # hence disabling pylint for that.
        metrics_dimension_map = {
            "domains": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "DomainName": lambda event: event.get('DeviceHostname', [None])[0],
                "account_name": lambda _: account_name
            },
            "fan": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "HostId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )(
                    (event.get('Ancestors', [{}])[-1] or {}).get('link', None)
                ),
                "HostType": lambda event: (event.get('Ancestors', [{}])[-1] or {}).get('ObjectType', None),
                "FanId": lambda event: event.get('FanId', None),
                "FanModuleId": lambda event: event.get('FanModuleId', None),
                "FanModuleMoid": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )(
                    (event.get('Parent') or {}).get('link', None)
                ),
                "Name": lambda event: event.get('Dn', None),
                "vendor": lambda event: event.get('Vendor', None),
                "FanState": lambda event: event.get('OperState', None),
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(domain_ids)), None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "fan"
            },
            "fanmodule": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "ParentId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )(
                    (event.get('Parent') or {}).get('link', None)
                ),
                "ParentType": lambda event: (event.get('Parent') or {}).get('ObjectType', None),
                "AncestorsId": lambda event: next(
                    (
                        (item or {}).get('Moid', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "AncestorsType": lambda event: next(
                    (
                        (item or {}).get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "account_name": lambda _: account_name,
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
            },
            "networkelements": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "HostId": lambda event: f"/api/v1/network/Elements/{event.get('Moid', None)}",
                "HostName": lambda event: event.get('Name', None),
                "HostTags": lambda event: event.get('Tags', None),
                "HostType": lambda event: event.get('SourceObjectType', None),
                "Model": lambda event: event.get('Model', None),
                "Name": lambda event: event.get('Name', None),
                "ParentId": lambda event: f"/api/v1/network/Elements/{event.get('Moid', None)}",
                "assetDrMoid": lambda event: (event.get('RegisteredDevice') or {}).get('Moid', None),
                "serial": lambda event: event.get('Serial', None),
                "vendor": lambda event: event.get('Vendor', None),
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "hwChassisNumber": lambda _: None,
                "account_name": lambda _: account_name,
                "ParentName": lambda event: event.get('Name', None),
            },
            "chassis": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "HostId": lambda event: f"/api/v1/equipment/Chasses/{event.get('Moid', None)}",
                "HostName": lambda event: event.get('Name', None),
                "HostTags": lambda event: event.get('Tags', None),
                "HostType": lambda _: "equipment.Chassis",
                "Model": lambda event: event.get('Model', None),
                "Name": lambda event: event.get('Name', None),
                "ParentId": lambda event: f"/api/v1/equipment/Chasses/{event.get('Moid', None)}",
                "assetDrMoid": lambda event: (event.get('RegisteredDevice') or {}).get('Moid', None),
                "serial": lambda event: event.get('Serial', None),
                "vendor": lambda event: event.get('Vendor', None),
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "hwChassisNumber": lambda event: event.get('ChassisId', None),
                "account_name": lambda _: account_name,
                "ParentName": lambda _: None,
            },
            "physicalsummary": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "HostId": lambda event: (
                    f"/api/v1/compute/{event.get('SourceObjectType').split('.')[-1]}s/{event.get('Moid')}"
                    if event.get('SourceObjectType') else ''
                ),
                "HostName": lambda event: event.get('Name', None),
                "HostTags": lambda event: event.get('Tags', None),
                "HostType": lambda event: event.get('SourceObjectType', None),
                "Model": lambda event: event.get('Model', None),
                "Name": lambda event: event.get('Name', None),
                "ParentId": lambda event: (
                    f"/api/v1/compute/{event.get('SourceObjectType').split('.')[-1]}s/{event.get('Moid')}"
                    if event.get('SourceObjectType') else ''
                ),
                "assetDrMoid": lambda event: (event.get('RegisteredDevice') or {}).get('Moid', None),
                "serial": lambda event: event.get('Serial', None),
                "vendor": lambda event: event.get('Vendor', None),
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "hwChassisNumber": lambda event: event.get('ChassisId', None),
                "account_name": lambda _: account_name,
                "ParentName": lambda _: None,
                "ChassisMoid": lambda event: (event.get('EquipmentChassis') or {}).get('Moid', None),
            },
            "memoryunit": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwtype": lambda _: "memory",
                "HostId": lambda event: next(
                    (
                        f"/api/v1/compute/{item['ObjectType'].split('.')[-1]}s/{item['Moid']}"
                        for item in (event.get('Ancestors', []) or [])
                        if (
                            item
                            and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                            and item.get('Moid')
                        )
                    ),
                    None
                ),
                "hwMemoryState": lambda event: event.get('OperState', None),
                "Name": lambda event: event.get('Location', None),
                "ParentId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "ParentType": lambda event: next(
                    (
                        item.get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if item and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "account_name": lambda _: account_name,
                "assetDrMoid": lambda event: (event.get('RegisteredDevice') or {}).get('Moid', None),
            },
            "computeboard": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "ParentId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "ParentType": lambda event: next(
                    (
                        item.get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if item and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "account_name": lambda _: account_name,
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "hwtype": lambda _: "temperature",
                "ParentName": lambda _: None,
                "assetDrMoid": lambda event: (event.get('RegisteredDevice') or {}).get('Moid', None),
            },
            "processorunit": {
                "_key": lambda event: f"{account_name}_{event['Moid']}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "ParentId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "ParentType": lambda event: next(
                    (
                        item.get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if item and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "account_name": lambda _: account_name,
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "hwtype": lambda _: "temperature",
                "ParentName": lambda _: None
            },
            "transceiver": {
                "_key": lambda event: f"{account_name}_{event['Moid']}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "ParentId": lambda event: (
                    '/api' + (event.get('Parent', {}).get('link', '').split('/api')[-1])
                ),
                "ParentType": lambda _: "network.Element",
                "account_name": lambda _: account_name,
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "HostId": lambda event: next(
                    (
                        f"/api/v1/network/Elements/{item['Moid']}"
                        for item in (event.get('Ancestors', []) or [])
                        if (
                            item
                            and item.get('ObjectType') in ['network.Element']
                            and item.get('Moid')
                        )
                    ),
                    None
                ),
                "hwtype": lambda _: "temperature",
                "ParentName": lambda _: None,
                "serial": lambda event: event.get("Serial", None),
                "Model": lambda event: event.get("Model", None),
                "vendor": lambda event: event.get('Vendor', None)
            },
            "graphicscard": {
                "_key": lambda event: f"{account_name}_{event['Moid']}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "ParentId": lambda event: (
                    '/api' + (event.get('Parent', {}).get('link', '').split('/api')[-1])
                ),
                "ParentType": lambda event: next(
                    (
                        item.get('ObjectType', None)
                        for item in (event.get('Ancestors', []) or [])
                        if (
                            item
                            and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                            and item.get('Moid')
                        )
                    ),
                    None
                ),
                "account_name": lambda _: account_name,
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "HostId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        for item in (event.get('Ancestors', []) or [])
                        if (
                            item
                            and item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                            and item.get('Moid')
                        )
                    ),
                    None
                ),
                "hwtype": lambda _: "temperature",
                "ParentName": lambda _: None,
                "serial": lambda event: event.get("Serial", None),
                "Model": lambda event: event.get("Model", None),
                "vendor": lambda event: event.get('Vendor', None)
            }
        }

        # Check if the type exists in the mapping
        if object_type in metrics_dimension_map:
            format_map = metrics_dimension_map[object_type]
            # Try generating the formatted data
            try:
                # Iterate over the mapping and apply the lambda function to the event
                # and create a new dictionary with the result
                if format_map:
                    result = {key: func(event) for key, func in format_map.items()}
                    return result
                else:
                    return {}
            except Exception as e:
                self.logger.error(f"message=metric_collection | Error while processing event with Moid "
                                  f"= '{event['Moid']}' of type '{object_type}': {e}.")
                return {}
        else:
            metric_mapper_network_obj = metric_mapper_network.MetricMapperNetwork(self.logger)
            return metric_mapper_network_obj.create_mergeable_data(
                object_type, event, account_name, id_chunk
            )
