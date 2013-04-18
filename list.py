#!/usr/bin/python
# Copyright 2012 Google Inc.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy
# of the License at: http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distrib-
# uted under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied.  See the License for
# specific language governing permissions and limitations under the License.

"""Handler for the user's list of maps."""

__author__ = 'kpy@google.com (Ka-Ping Yee)'

import webapp2

import base_handler
import model


class List(base_handler.BaseHandler):
  """Handler for the user's list of maps."""

  def get(self):  # pylint: disable=g-bad-name
    # Attach to each Map a 'catalog_entries' attribute containing the
    # CatalogEntry entities that link to it.
    entries = model.CatalogEntry.GetAll()
    maps = list(model.Map.GetViewable())
    published = {}
    for entry in entries:
      published.setdefault(entry.map_id, []).append(entry)
    for map_ in maps:
      map_.catalog_entries = published.get(map_.id, [])

    self.response.out.write(self.RenderTemplate('list.html', {
        'maps': maps,
        'creator_domains': model.GetDomainsWithRole(model.Role.MAP_CREATOR),
        'catalog_domains': model.GetDomainsWithRole(model.Role.CATALOG_EDITOR)
    }))


app = webapp2.WSGIApplication([(r'.*', List)])
