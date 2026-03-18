"""
The KVStoreManager class abstracts KVStore Collection related transactions.

The KVStoreManager class provides methods to query, upsert and delete data from
KVStore collections. The KVStoreManager class is used by the ModularInput
class to store and retrieve data from KVStore collections.

The KVStoreManager class is a singleton class. The instance of the
KVStoreManager class is created when the ModularInput class is initialized.

The KVStoreManager class provides the following methods:

- query(collection_name, **kwargs): Queries the KVStore collection and
  returns the results.
- upsert(items, collection_name): Updates or inserts items into the
  KVStore collection.
- delete_batch(query, collection_name): Deletes the events based on the
  query from the KVStore collection.

The KVStoreManager class also provides the following properties:

- kvstore_write_limit: The maximum number of documents that can be written
  to the KVStore collection in a single batch.
"""
import json
import http
import time
import splunklib
from splunklib import client
from import_declare_test import ta_name
from splunk import rest
from intersight_helpers import logger_manager, constants
from typing import TypeVar, Callable, Any, List, Dict, Optional
from intersight_helpers import conf_helper

Func = TypeVar('Func', bound=Callable[..., Any])

logger = logger_manager.setup_logging("ta_intersight_kvstore")


KVSTORE_CALL_DELAY_SEC = 0.1
DEFAULT_MAX_RETRY = 3
DEFAULT_BACKOFF_FACTOR = 5
DEFAULT_KVSTORE_WRITE_LIMIT = 1000
RETRY_STATUS_CODES = set(range(500, 599))

# - Max allowed length of accelerated fields is 999 and ideally all fields used in kvstore query should be accelerated.
# - When putting field with 4 character name (e.g. "_key") into query,
#   it is verified that in worst case (all fields are of 999 char long),
#   max supported values into single call is with 498 (with removal of whitespaces in query's json dump) values,
#   exceeding it, throws the error "HTTP 413 Request Entity Too Large".
# - Following is the optimum value for allowing few more characters for other URI components
KVSTORE_URL_CHUNKSIZE = 490


def chunk(iterable, chunk_size: int):
    """
    Split iterable into chunks of given size.

    This function yields chunks of the given size from the iterable. It is
    useful when you need to process a large iterable but do not want to
    load it into memory completely.

    Args:
        iterable (iterable): The iterable to split into chunks.
        chunk_size (int): The size of the chunks.

    Yields:
        A chunk of the given size from the iterable.
    """
    for i in range(0, len(iterable), chunk_size):
        yield iterable[i: i + chunk_size]


class KVStoreUnavailbleError(Exception):
    """KVStore is not available (503 status code)."""

    pass


class CollectionNotFoundError(Exception):
    """Expected collection not found in KVStore."""

    def __init__(self, collection: str) -> None:
        """
        Initialize an exception for the missing collection case.

        Args:
            collection (str): The name of the missing collection.
        """
        message = f'Could not find collection named "{collection}"'
        super().__init__(message)


class KVStoreManager:
    """Abstract the KVStore Collection related transactions."""

    def _connect_splunk_service(self) -> None:
        """
        Connect to the Splunk service using the provided KV Store stanza configuration.

        This function is used to establish a connection to the Splunk
        service using the configuration provided in the KV Store stanza.
        It is called when the KVStoreManager object is initialized.
        """
        # Get the KV Store stanza configuration
        kv_conf_stanza = conf_helper.get_conf_file(
            file="splunk_ta_cisco_intersight_settings",
            stanza="splunk_rest_host",
            session_key=self.session_key,
        )
        # Create the KV Store stanza configuration to be used for the
        # connection
        kvstore_stanza = {
            "host": kv_conf_stanza.get("splunk_rest_host_url"),
            "port": kv_conf_stanza.get("splunk_rest_port"),
            "session_key": self.session_key,
            "owner": "nobody",
            "app": ta_name,
            "username": kv_conf_stanza.get("splunk_username", None),
            "password": kv_conf_stanza.get("splunk_password", None),
            "verify": constants.VERIFY_SSL,
        }
        # Set the verify flag to False if the host is localhost or 127.0.0.1
        if kvstore_stanza["host"] in ("127.0.0.1", "localhost"):
            kvstore_stanza["verify"] = False
        # Log a debug message if the host is not localhost or 127.0.0.1
        if (
            kvstore_stanza.get("host") not in ("localhost", "127.0.0.1")
            or kvstore_stanza.get("username")
            or kvstore_stanza.get("password")
        ):
            logger.debug(
                "message=connect_splunk_service | Logging in to the RemoteSplunk: {}".format(
                    kvstore_stanza.get("host")
                )
            )
            self.service = client.connect(
                host=kvstore_stanza.get("host"),
                port=kvstore_stanza.get("port"),
                verify=kvstore_stanza.get("verify"),
                username=kvstore_stanza.get("username"),
                password=kvstore_stanza.get("password"),
                owner=kvstore_stanza.get("owner"),
                app=kvstore_stanza.get("app"),
            )
            logger.debug(
                "message=connect_splunk_service_success |"
                " Successfully logged into RemoteSplunk: {}".format(
                    kvstore_stanza.get("host")
                )
            )
        else:
            self.service = client.connect(
                host=kvstore_stanza.get("host"),
                port=kvstore_stanza.get("port"),
                verify=kvstore_stanza.get("verify"),
                token=kvstore_stanza.get("session_key"),
                owner=kvstore_stanza.get("owner"),
                app=kvstore_stanza.get("app"),
            )
        self.splunk_host = kvstore_stanza.get("host")

    def __init__(
        self,
        max_retry: int = DEFAULT_MAX_RETRY,
        backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
        service: Optional[object] = None,
        session_key: Optional[str] = None,
    ) -> None:
        """
        Initialize the object.

        Args:
            max_retry (int): The maximum number of times to retry the operation.
            backoff_factor (int): The backoff factor to use for the retry.
            service (object): The service to use for the connection.
            session_key (str): The session key to use for the connection.

        """
        self.max_retry = max_retry
        self.backoff_factor = backoff_factor
        self.session_key = session_key
        if not service:
            # Connect to the Splunk service using the provided session key
            self._connect_splunk_service()
        else:
            self.service = service
        # Store the kvstore write limit in an instance variable
        self._kvstore_write_limit = None

    def collection(self, collection_name: str) -> object:
        """
        Retrieve a KVStore collection object by its name.

        Args:
            collection_name (str): The name of the collection to retrieve.

        Returns:
            KVStoreCollection: The collection object associated with the given name.

        Raises:
            CollectionNotFoundError: If the specified collection does not exist.
        """
        # Check if the collection exists in the KVStore
        if collection_name not in self.service.kvstore:
            logger.info(
                "collection_name not found in KVStore service: {}".format(collection_name)
            )
            raise CollectionNotFoundError(collection_name)

        # Retrieve and return the collection object
        collection_obj = self.service.kvstore[collection_name]
        return collection_obj

    @property
    def kvstore_write_limit(self) -> int:
        """
        Return kvstore write limit defined in limits.conf file.

        If the value is not set, use the default value defined in DEFAULT_KVSTORE_WRITE_LIMIT.

        :return: The kvstore write limit as an integer.
        """
        if self._kvstore_write_limit is None:
            try:
                # Get the value of kvstore:max_documents_per_batch_save from limits.conf
                _, content = rest.simpleRequest(
                    "/services/properties/limits/kvstore/max_documents_per_batch_save",
                    method="GET",
                    sessionKey=self.session_key,
                    getargs={"output_mode": "json"},
                    raiseAllErrors=True,
                )
                # Convert the value to an integer
                self._kvstore_write_limit = int(content)
            except Exception:
                # If there is an error, use the default value
                self._kvstore_write_limit = DEFAULT_KVSTORE_WRITE_LIMIT
        return self._kvstore_write_limit

    # Decorator
    @staticmethod
    def normalize_exc(method: Func) -> Func:
        """
        Normalize low level exception to abstract application level exceptions.

        This decorator catches HTTPError exceptions and raises an appropriate
        application level exception instead.

        :param method: The method to be decorated.
        :return: The decorated method.
        """
        def wrapper(self, *args, **kwargs):
            # pylint: disable=broad-except # needed args and kwargs
            try:
                res = method(self, *args, **kwargs)
                return res
            except splunklib.binding.HTTPError as ex:
                # Check if the exception is related to the KVStore being unavailable
                if ex.status == http.HTTPStatus.SERVICE_UNAVAILABLE:
                    # Raise a KVStoreUnavailbleError exception
                    raise KVStoreUnavailbleError(str(ex))
                # Raise the original exception
                raise

        return wrapper

    # Decorator
    @staticmethod
    def retry(method: Func) -> Func:
        """
        Implement a retry mechanism for handling temporary errors.

        Retries the execution of the method upon encountering specific HTTP errors,
        using exponential backoff for delays between retries.

        :param method: The method to be decorated with retry logic.
        :return: The decorated method with retry logic.
        """

        def wrapper(self, *args, **kwargs):
            retry_count = 0
            response = None

            while True:
                try:
                    # Attempt to execute the method
                    response = method(self, *args, **kwargs)
                    break
                except splunklib.binding.HTTPError as ex:
                    # Check if the exception status code allows for a retry
                    if (ex.status not in RETRY_STATUS_CODES) or (
                        retry_count >= self.max_retry
                    ):
                        logger.error(
                            'message=kvstore_error | Error from KVStore: '
                            'method="{}" error="{}"'.format(method.__name__, ex)
                        )
                        # Raise the exception if it should not be retried
                        raise

                    retry_count += 1

                    # Log a warning on the first retry attempt
                    if retry_count == 1:
                        logger.warning(
                            "message=kvstore_retry | Retrying:"
                            " method='{}' error='{}'".format(method.__name__, ex)
                        )

                    # Calculate delay using exponential backoff
                    delay = (self.backoff_factor) * (2 ** (retry_count - 2))
                    time.sleep(delay)

                    # Log retry count and delay information
                    logger.info(
                        "message=kvstore_retry_counter | retry_count={} retry_after_seconds={}".format(
                            retry_count, delay
                        )
                    )

            return response

        return wrapper

    @normalize_exc.__func__
    @retry.__func__
    def query(self, collection_name: str, **kwargs) -> List[Dict]:
        """
        Query indicators from KVStore.

        :param collection_name: The name of the KVStore collection.
        :param kwargs: Additional keyword arguments that are passed to the
            :meth:`KVStoreCollectionData.query` method.
        :return: A list of dictionaries that represent the results of the query.
        """
        # Retrieve the collection object
        collection_obj = self.collection(collection_name)
        # Query the collection and return the result
        res = collection_obj.data.query(**kwargs)
        return res

    @normalize_exc.__func__
    def get(self, collection_name: str, fields: list = None, query: dict = None) -> List[Dict]:
        """
        Retrieve all items from a KVStore collection using pagination.

        :param collection_name: The name of the KVStore collection to query.
        :param fields: A list of fields to include in the result set.
        :param query: A dictionary representing the query to filter the results.
        :return: A list of dictionaries containing the items from the collection.
        """
        # Default fields if none are provided
        if fields is None:
            fields = ["_user:0"]
        # Default query if none is provided
        if query is None:
            query = {}

        data = []  # List to hold the retrieved data
        skip = 0  # Variable to track pagination position
        kwargs = {}  # Dictionary to hold query parameters

        # Add query to kwargs if provided
        if query:
            # Note: KVStore doesn't support $in operator that MongoDB has
            kwargs.update({"query": json.dumps(query, separators=(",", ":"))})
        # Add fields to kwargs if provided
        if fields:
            kwargs.update({"fields": ",".join(fields)})

        # Loop to fetch data in batches
        while True:
            kwargs["skip"] = skip  # Set skip parameter for pagination
            items = self.query(collection_name, **kwargs)  # Query the collection

            # Break if no more items are found
            if len(items) == 0:
                break

            # Log the number of items fetched
            logger.debug(
                "message=kvstore_query_call | Fetched the data from kvstore: count={}".format(
                    len(items)
                )
            )

            data += items  # Add fetched items to the data list
            skip += len(items)  # Increment skip by the number of fetched items
            # Delay between KVStore calls to avoid hitting API rate limits
            time.sleep(KVSTORE_CALL_DELAY_SEC)

        return data  # Return the accumulated data

    def query_by_id(self, id: int, collection_name: str) -> dict:
        """Return items which are requested.

        :param id: The ID of the item to query.
        :param collection_name: The name of the KVStore collection.
        :return: The item with the requested ID if found, None otherwise.
        """
        try:
            collection_obj = self.collection(collection_name)
            return collection_obj.data.query_by_id(id)
        except splunklib.binding.HTTPError as ex:
            # If the item is not found, return None
            if ex.status == 404:
                return None
            else:
                raise ex

    @normalize_exc.__func__
    def upsert(self, items: list, collection_name: str) -> None:
        """Update/Insert (Upsert) items into collection.

        :param items: The list of items to upsert in the collection.
        :param collection_name: The name of the KVStore collection.
        """
        # Split the items into chunks of self.kvstore_write_limit size
        # to avoid hitting the KVStore data size limit
        for chunked_items in chunk(items, self.kvstore_write_limit):
            collection_obj = self.collection(collection_name)
            collection_obj.data.batch_save(*chunked_items)
            # Log the number of items upserted and the collection name
            logger.debug(
                "message=kvstore_upsert_call | Upserted the data to"
                " kvstore: collection={} count={}".format(
                    collection_name, len(chunked_items)
                )
            )
            # Delay between KVStore calls to avoid hitting API rate limits
            time.sleep(KVSTORE_CALL_DELAY_SEC)

    @normalize_exc.__func__
    def delete_batch(self, query: list, collection_name: str) -> None:
        """
        Delete the events based on the provided query from the specified KVStore collection.

        :param query: The query to select documents for deletion.
        :param collection_name: The name of the KVStore collection to delete from.
        """
        # Log the delete batch call with the collection name
        logger.debug(
            "message=kvstore_delete_batch_call | Delete batch call to kvstore: collection={}".format(collection_name)
        )

        # Convert the query to a JSON string
        query = json.dumps(query)

        # Retrieve the collection object
        collection_obj = self.collection(collection_name)

        # Perform the delete operation using the query
        collection_obj.data.delete(query)
