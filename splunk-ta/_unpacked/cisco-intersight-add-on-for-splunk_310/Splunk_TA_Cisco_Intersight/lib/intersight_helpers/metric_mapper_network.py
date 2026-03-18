# pylint: disable=too-many-lines
"""This module provides helper functions specific for metric input."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
import logging
import typing  # noqa: F401  # pylint: disable=unused-import # needed for type hints


class MetricMapperNetwork:
    """Mapper function for Metrics Dimension collection."""

    def __init__(self, logger: logging.Logger) -> None:
        """
        Init function for class MetricHelper.

        Args:
            logger (logging.Logger): Logger instance used for logging messages.
        """
        self.logger = logger

    def create_mergeable_data(
        self, object_type: str, event: dict, account_name: str, id_chunk: list
    ) -> dict:
        """
        Format data in a predefined collection format based on the object type.

        Args:
            object_type (str): The type of the object for which data needs to be formatted.
            event (dict): The event data containing information to be processed.
            account_name (str): The name of the account associated with the event.
            id_chunk (list): A list of IDs used to help identify the domain.

        Returns:
            dict: A dictionary of formatted data if the object_type is supported, otherwise an empty dictionary.

        Raises:
            ValueError: If the object_type is not supported.
        """
        # Define the mapping for metrics dimensions based on object type
        # Map of object types to their corresponding collection format using lambda functions
        # The lambda functions are used to extract and modify the values to our needed format
        # hence disabling pylint for that.
        metrics_dimension_map = {
            "etherhostports": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: (
                    f"/api/v1/{event.get('Parent', {}).get('ClassId', '').split('.')[0]}/"
                    f"{event.get('Parent', {}).get('ClassId', '').split('.')[1]}s/"
                    f"{event.get('Parent', {}).get('Moid', '')}"
                    if event.get('Parent', {}).get('ClassId') else None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda event: event.get('Role', None),
                "hwNetworkPortType": lambda _: "backplane_port",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: (
                    f"{event.get('PortType', None)}"
                    f"{event.get('ModuleId', None)}/"
                    f"{event.get('SlotId', None)}/"
                    f"{event.get('PortId', None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "HostType": lambda _: "network.Element"
            },
            "ethernetworkports": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: (
                    f"/api/v1/{event.get('Parent', {}).get('ClassId', '').split('.')[0]}/"
                    f"{event.get('Parent', {}).get('ClassId', '').split('.')[1]}s/"
                    f"{event.get('Parent', {}).get('Moid', '')}"
                    if event.get('Parent', {}).get('ClassId') else None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda _: "iom_uplink",
                "hwNetworkPortType": lambda _: "ethernet",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: (
                    f"Nif"
                    f"{(event.get('Parent') or {}).get('ModuleId', None)}/"
                    f"{event.get('SlotId', None)}/"
                    f"{event.get('PortId', None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                ),
                "HostType": lambda _: "network.Element"
            },
            "etherphysicalports": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda event: event.get('Role', None),
                "hwNetworkPortType": lambda _: "ethernet",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: f"Ethernet{event.get('SlotId', None)}/{event.get('PortId', None)}",
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "etherportchannels": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda event: event.get('Role', None),
                "hwNetworkPortType": lambda _: "ethernet_port_channel",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: f"port-channel{event.get('PortChannelId', None)}",
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "adapterhostethinterfaces": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        f"/api/v1/equipment/Chasses/{item['Moid']}"
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next(
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "HostId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "HostName": lambda event: ((event.get('Ancestors', [{}])[-1]) or {}).get('Name', None),
                "HostType": lambda event: next(
                    (
                        (item or {}).get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "Name": lambda event: event.get('Name', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: (
                    f"/api/v1/{event.get('Parent', {}).get('ClassId', '').split('.')[0]}/"
                    f"{event.get('Parent', {}).get('ClassId', '').split('.')[1]}s/"
                    f"{event.get('Parent', {}).get('Moid', '')}"
                    if event.get('Parent', {}).get('ClassId') else None
                ),
                "AncestorsId": lambda event: next(
                    (
                        (item or {}).get('Moid', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "ParentType": lambda event: next(
                    (
                        (item or {}).get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('VifId', None),
                "hwNetworkPortRole": lambda _: "vnic",
                "hwNetworkPortType": lambda _: "virtual_network_interface_card",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "adapterextethinterfaces": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda _: None,
                "hwChassis": lambda event: next(
                    (
                        f"/api/v1/equipment/Chasses/{item['Moid']}"
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next(
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwtype": lambda _: "network",
                "HostId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "HostName": lambda event: ((event.get('Ancestors', [{}])[-1]) or {}).get('Name', None),
                "HostType": lambda event: next(
                    (
                        (item or {}).get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "Name": lambda event: event.get('ExtEthInterfaceId', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState', '').lower() == 'up'
                    else ('failed' if event.get('OperState', '').lower() == 'down' else None)
                ),
                "ParentId": lambda event: (
                    f"/api/v1/{(event.get('Parent') or {}).get('ObjectType', '').split('.')[0]}/"
                    f"{(event.get('Parent') or {}).get('ObjectType', '').split('.')[1]}s/"
                    f"{event.get('Parent', {}).get('Moid', '')}"
                    if (event.get('Parent') or {}).get('ObjectType')
                    and '.' in (event.get('Parent') or {}).get('ObjectType', '')
                    else None
                ),
                "AncestorsId": lambda event: next(
                    (
                        (item or {}).get('Moid', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "ParentType": lambda event: next(
                    (
                        (item or {}).get('ObjectType', None)
                        for item in event.get('Ancestors', [])
                        if (item or {}).get('ObjectType') in [
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda _: None,
                "hwNetworkPortNumber": lambda event: event.get('ExtEthInterfaceId', None),
                "hwNetworkPortRole": lambda _: "unconfigured",
                "hwNetworkPortType": lambda _: "ethernet",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "account_name": lambda _: account_name
            },
            "adapterhostfcinterfaces": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        f"/api/v1/equipment/Chasses/{item['Moid']}"
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next(
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hostId": lambda event: ((event.get('Ancestors', [{}])[-1]) or {}).get('link', None),
                "HostName": lambda event: ((event.get('Ancestors', [{}])[-1]) or {}).get('Name', None),
                "HostType": lambda event: ((event.get('Ancestors', [{}])[-1]) or {}).get('ObjectType', None),
                "Name": lambda event: event.get('Name', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: (
                    f"/api/v1/{event.get('Parent', {}).get('ClassId', '').split('.')[0]}/"
                    f"{event.get('Parent', {}).get('ClassId', '').split('.')[1]}s/"
                    f"{event.get('Parent', {}).get('Moid', '')}"
                    if event.get('Parent', {}).get('ClassId') else None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('VifId', None),
                "hwNetworkPortRole": lambda _: "vhba",
                "hwNetworkPortType": lambda _: "virtual_host_bus_adapter",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "fcportchannels": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next(
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda _: "fc_uplink_pc",
                "hwNetworkPortType": lambda _: "fibre_port_channel",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: f"san-port-channel{event.get('PortChannelId', None)}",
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "fcphysicalports": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next
                (
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (  # pylint: disable=unnecessary-direct-lambda-call
                    lambda link: '/api' + link.split('/api')[-1] if link is not None else None
                )((event.get('AcknowledgedPeerInterface') or {}).get('link', None)),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "Name": lambda event: f"fc{event.get('SlotId', None)}/{event.get('PortId', None)}",
                "hwNetworkPortNumber": lambda event: event.get('PortId', None),
                "hwNetworkPortRole": lambda _: "fc_uplink",
                "hwNetworkPortType": lambda _: "fibre_channel",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ClassId'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ClassId') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "networkvethernets": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next
                (
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (
                    f"/api/v1/{event.get('AdapterHostEthInterface', {}).get('ObjectType', '').split('.')[0]}/"
                    f"{event.get('AdapterHostEthInterface', {}).get('ObjectType', '').split('.')[1]}s/"
                    f"{event.get('AdapterHostEthInterface', {}).get('Moid', '')}"
                    if event.get('AdapterHostEthInterface') is not None else None
                ),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('VethId', None),
                "hwNetworkPortRole": lambda _: "vethernet",
                "hwNetworkPortType": lambda _: "virtual_ethernet",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: f"VEthernet{event.get('VethId', None)}",
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in (event.get('AdapterHostEthInterface') or {}).get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
            },
            "networkvfcs": {
                "_key": lambda event: f"{account_name}_{event.get('Moid', None)}",
                "AccountMoid": lambda event: event.get('AccountMoid', None),
                "hwNetworkPortAggregate_port": lambda event: event.get('AggregatePortId', None),
                "hwChassis": lambda event: next(
                    (
                        '/api' + (item.get('link', '').split('/api')[-1])
                        if item.get('link') else None
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "hwChassisNumber": lambda event: next(
                    (
                        (item or {}).get('ChassisId', None)
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in ['equipment.Chassis']
                    ),
                    None
                ),
                "Model": lambda event: (event.get('Parent') or {}).get('Model', None),
                "hwNetworkState": lambda event: (
                    'ok' if event.get('OperState') == 'up'
                    else ('failed' if event.get('OperState') == 'down' else None)
                ),
                "ParentId": lambda event: next(
                    (
                        f"/api/v1/{item.get('ObjectType', '').split('.')[0]}"
                        f"/{item.get('ObjectType', '').split('.')[1]}s/"
                        f"{item.get('Moid', '')}"
                        for item in event.get('Ancestors', [])
                        if item.get('ObjectType') in [
                            'network.Element',
                            'equipment.Chassis',
                            'compute.PhysicalSummary',
                            'compute.RackUnit',
                            'compute.Blade'
                        ]
                    ),
                    None
                ),
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
                "ParentType": lambda event: next(
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
                "hwNetworkPeerId": lambda event: (
                    f"/api/v1/{event.get('AdapterHostFcInterface', {}).get('ObjectType', '').split('.')[0]}/"
                    f"{event.get('AdapterHostFcInterface', {}).get('ObjectType', '').split('.')[1]}s/"
                    f"{event.get('AdapterHostFcInterface', {}).get('Moid', '')}"
                    if event.get('AdapterHostFcInterface') is not None else None
                ),
                "physical_address": lambda event: event.get('MacAddress', None),
                "hwNetworkPortPort_channel": lambda event: event.get('PortChannelId', None),
                "hwNetworkPortNumber": lambda event: event.get('VfcId', None),
                "hwNetworkPortRole": lambda _: "vfc",
                "hwNetworkPortType": lambda _: "virtual_fibre_channel",
                "DomainId": lambda event: (
                    f"/api/v1/asset/DeviceRegistrations/"
                    f"{next(iter(set(event.get('Owners', [])) & set(id_chunk)), None)}"
                ),
                "Name": lambda event: f"vfc{event.get('VfcId', None)}",
                "account_name": lambda _: account_name,
                "hwtype": lambda _: "network",
                "hwNetworkPortSlot": lambda event: event.get('SlotId', None),
                "hwServerId": lambda event: next(
                    (
                        '/api/v1/compute/' + (item['ObjectType'].split('.')[-1]) + "s/" + (item['Moid'])
                        if item.get('Moid') else None
                        for item in (event.get('AdapterHostFcInterface') or {}).get('Ancestors', [])
                        if item.get('ObjectType') in ['compute.Blade', 'compute.RackUnit']
                    ),
                    None
                )
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
                self.logger.error(
                    f"message=metric_collection | Error while processing event with Moid "
                    f"= '{event['Moid']}' of type '{object_type}': {e}."
                )
                return {}
        else:
            raise ValueError(f"Unsupported type: {object_type}")
