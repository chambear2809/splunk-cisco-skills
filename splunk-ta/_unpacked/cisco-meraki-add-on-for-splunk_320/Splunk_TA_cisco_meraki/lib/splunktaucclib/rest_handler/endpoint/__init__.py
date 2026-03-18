#
# Copyright 2025 Splunk Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from typing import List, Optional

from .field import RestField
from ..error import RestError
from ..util import get_base_app_name

__all__ = [
    "RestModel",
    "RestEndpoint",
    "SingleModel",
    "MultipleModel",
    "DataInputModel",
]


class RestModel:
    def __init__(
        self, fields, name=None, special_fields: Optional[List[RestField]] = None
    ):
        """
        REST Model.
        :param name:
        :param fields:
        :param special_fields:
        """
        self.name = name
        self.fields = fields
        self.special_fields = special_fields if special_fields else []


class RestEndpoint:
    """
    REST Endpoint.
    """

    def __init__(self, user="nobody", app=None, need_reload=False, *args, **kwargs):
        """
        :param user:
        :param app: if None, it will be base app name
        :param need_reload: if reload is needed while GET request
        :param args:
        :param kwargs:
        """
        self.user = user
        self.app = app or get_base_app_name()
        self.args = args
        self.kwargs = kwargs

        self.need_reload = need_reload

    @property
    def internal_endpoint(self):
        """
        Endpoint of Splunk internal service.

        :return:
        """
        raise NotImplementedError()

    def model(self, name):
        """
        Real model for given name.

        :param name:
        :return:
        """
        raise NotImplementedError()

    def _loop_fields(self, meth, name, data, *args, **kwargs):
        model = self.model(name)
        return [getattr(f, meth)(data, *args, **kwargs) for f in model.fields]

    def validate(self, name, data, existing=None):
        self._loop_fields("validate", name, data, existing=existing)

    def _loop_field_special(self, meth, name, data, *args, **kwargs):
        model = self.model(name)
        return [getattr(f, meth)(data, *args, **kwargs) for f in model.special_fields]

    def validate_special(self, name, data):
        self._loop_field_special("validate", name, data, validate_name=name)

    def encode(self, name, data):
        self._loop_fields("encode", name, data)

    def decode(self, name, data):
        self._loop_fields("decode", name, data)


class SingleModel(RestEndpoint):
    """
    REST Model with Single Mode. It will store stanzas
    with same format  into one conf file.
    """

    def __init__(
        self,
        conf_name,
        model,
        user="nobody",
        app=None,
        need_reload=False,
        *args,
        **kwargs,
    ):
        """
        :param conf_name: conf file name
        :param model: REST model
        :type model: RestModel
        :param need_reload: if reload is needed while GET request
        :param args:
        :param kwargs:
        """
        super().__init__(user=user, app=app, need_reload=need_reload, *args, **kwargs)

        self._model = model
        self.conf_name = conf_name
        self.config_name = kwargs.get("config_name")

    @property
    def internal_endpoint(self):
        return f"configs/conf-{self.conf_name}"

    def model(self, name):
        return self._model


class MultipleModel(RestEndpoint):
    """
    REST Model with Multiple Modes. It will store
     stanzas with different formats into one conf file.
    """

    def __init__(
        self,
        conf_name,
        models,
        user="nobody",
        app=None,
        need_reload=False,
        *args,
        **kwargs,
    ):
        """
        :param conf_name:
        :type conf_name: str
        :param models: list of RestModel
        :type models: list
        :param need_reload: if reload is needed while GET request
        :param args:
        :param kwargs:
        """
        super().__init__(user=user, app=app, need_reload=need_reload, *args, **kwargs)

        self.conf_name = conf_name
        self.models = {model.name: model for model in models}

    @property
    def internal_endpoint(self):
        return f"configs/conf-{self.conf_name}"

    def model(self, name):
        try:
            return self.models[name]
        except KeyError:
            raise RestError(404, "name=%s" % name)


class DataInputModel(RestEndpoint):
    """
    REST Model for Data Input.
    """

    def __init__(
        self,
        input_type,
        model,
        user="nobody",
        app=None,
        need_reload=False,
        *args,
        **kwargs,
    ):
        """
        :param input_type:
        :param model:
        :param user:
        :param app: if None, it will be base app name
        :param need_reload: if reload is needed while GET request
        :param args:
        :param kwargs:
        """
        super().__init__(user=user, app=app, need_reload=need_reload, *args, **kwargs)

        self.input_type = input_type
        self._model = model

    @property
    def internal_endpoint(self):
        return f"data/inputs/{self.input_type}"

    def model(self, name):
        return self._model
