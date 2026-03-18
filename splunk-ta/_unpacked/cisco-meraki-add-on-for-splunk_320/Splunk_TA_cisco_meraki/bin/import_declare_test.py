#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import os
import sys

ta_name = "Splunk_TA_cisco_meraki"

sys.path.insert(
    0,
    os.path.sep.join(
        [os.path.dirname(os.path.realpath(os.path.dirname(__file__))), "lib"]
    ),
)
sys.path.insert(
    1, os.path.sep.join([os.path.dirname(os.path.realpath(os.path.dirname(__file__)))])
)
