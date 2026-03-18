#!/usr/bin/python

#
# Copyright 2024 Splunk Inc.
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

import threading
import time

import splunktaucclib.common.log as stulog

from . import ta_consts as c


class TADataCollector:
    def __init__(
        self,
        tconfig,
        meta_config,
        task_config,
        checkpoint_manager_cls,
        data_client_cls,
        data_loader,
    ):
        self._lock = threading.Lock()
        self._ta_config = tconfig
        self._meta_config = meta_config
        self._task_config = task_config
        self._stopped = True
        self._p = self._get_logger_prefix()
        self._checkpoint_manager = checkpoint_manager_cls(meta_config, task_config)
        self.data_client_cls = data_client_cls
        self._data_loader = data_loader
        self._client = None

    def get_meta_configs(self):
        return self._meta_config

    def get_task_config(self):
        return self._task_config

    def get_interval(self):
        return self._task_config[c.interval]

    def _get_logger_prefix(self):
        pairs = [f'{c.stanza_name}="{self._task_config[c.stanza_name]}"']
        for key in self._task_config[c.divide_key]:
            pairs.append(f'{key}="{self._task_config[key]}"')
        return "[{}]".format(" ".join(pairs))

    def stop(self):
        self._stopped = True
        if self._client:
            self._client.stop()

    def __call__(self):
        self.index_data()

    def _get_ckpt(self):
        return self._checkpoint_manager.get_ckpt()

    def _get_ckpt_key(self):
        return self._checkpoint_manager.get_ckpt_key()

    def _update_ckpt(self, ckpt):
        return self._checkpoint_manager.update_ckpt(ckpt)

    def _create_data_client(self):
        ckpt = self._get_ckpt()
        data_client = self.data_client_cls(
            self._ta_config.get_all_conf_contents(),
            self._meta_config,
            self._task_config,
            ckpt,
            self._checkpoint_manager,
        )

        stulog.logger.debug(f"{self._p} Set {c.ckpt_dict}={ckpt} ")
        return data_client

    def index_data(self):
        if self._lock.locked():
            stulog.logger.debug(
                "Last round of stanza={} is not done yet".format(
                    self._task_config[c.stanza_name]
                )
            )
            return
        with self._lock:
            self._stopped = False
            checkpoint_key = self._get_ckpt_key()
            stulog.logger.info(
                "{} Start indexing data for checkpoint_key={"
                "}".format(self._p, checkpoint_key)
            )
            try:

                self._do_safe_index()
            except Exception:
                stulog.logger.exception(f"{self._p} Failed to index data")
            stulog.logger.info(
                "{} End of indexing data for checkpoint_key={}".format(
                    self._p, checkpoint_key
                )
            )

    def _write_events(self, ckpt, events):
        if events:
            self._data_loader.write_events(events)
        if ckpt is None:
            return True
        for i in range(3):
            try:
                self._update_ckpt(ckpt)
            except Exception:
                stulog.logger.exception(
                    "{} Failed to update ckpt {} to {}".format(
                        self._p, self._get_ckpt_key(), ckpt
                    )
                )
                time.sleep(2)
                continue
            else:
                return True
        # write checkpoint fail
        self.stop()
        return False

    def _do_safe_index(self):
        self._client = self._create_data_client()
        while not self._stopped:
            try:
                events, ckpt = self._client.get()
                if not events and not ckpt:
                    continue
                else:
                    if not self._write_events(ckpt, events):
                        break
            except StopIteration:
                stulog.logger.debug(f"{self._p} Finished this round")
                break
            except Exception:
                stulog.logger.exception(f"{self._p} Failed to get msg")
                break
        self.stop()
        try:
            self._client.get()
        except StopIteration:
            stulog.logger.debug(f"{self._p} Invoke client.get() after stop ")
