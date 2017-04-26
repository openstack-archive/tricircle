# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from sqlalchemy import MetaData, Table
from sqlalchemy import Index


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    resource_routings = Table('resource_routings', meta, autoload=True)
    index = Index('resource_routings0bottom_id',
                  resource_routings.c.bottom_id)
    index.create()
