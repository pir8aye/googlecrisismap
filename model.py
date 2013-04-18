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

"""Data model and related access permissions."""

__author__ = 'lschumacher@google.com (Lee Schumacher)'

import base64
import json
import os
import random

import cache

from google.appengine.api import users
from google.appengine.ext import db


class Struct(object):
  """A simple bag of attributes."""

  def __init__(self, **kwargs):
    self.__dict__.update(kwargs)

  def __iter__(self):
    return iter(self.__dict__)


# Access role constants.
# Role is capitalized like an enum class.  # pylint: disable=g-bad-name
Role = Struct(
    # Global roles
    ADMIN='ADMIN',  # can view, edit, or change permissions for anything

    # Domain-specific roles
    CATALOG_EDITOR='CATALOG_EDITOR',  # can edit the catalog for a domain
    MAP_CREATOR='MAP_CREATOR',  # can create new maps

    # Map-specific roles
    MAP_OWNER='MAP_OWNER',  # can change permissions for a map
    MAP_EDITOR='MAP_EDITOR',  # can save new versions of a map
    MAP_VIEWER='MAP_VIEWER',  # can view current version of a map
)


class Error(Exception):
  """Base class for map exceptions."""
  pass


class AuthorizationError(Error):
  """User not authorized to perform operation."""

  def __init__(self, user, role, target):
    Error.__init__(self, 'User %s lacks %s access to %r' % (user, role, target))
    self.user = user
    self.role = role
    self.target = target


def StructFromModel(model):
  """Copies the properties of the given db.Model into a Struct.

    Note that we use Property.get_value_for_datastore to prevent fetching
    of referenced objects into the struct.  The other effect of using
    get_value_for_datastore is that all date/time methods return
    datetime.datetime values.

  Args:
    model: A db.Model entity, or None.

  Returns:
    A Struct containing the properties of the given db.Model, with additional
    'key', 'name', and 'id' properties for the entity's key(), key().name(),
    and key().id().  Returns None if 'model' is None.
  """
  if model:
    return Struct(id=model.key().id(),
                  name=model.key().name(),
                  key=model.key(),
                  **dict((name, prop.get_value_for_datastore(model))
                         for (name, prop) in model.properties().iteritems()))


def ResultIterator(query):
  """Returns a generator that yields structs."""
  for result in query:
    yield StructFromModel(result)


class Config(db.Model):
  """A configuration setting for the application.

  Each configuration setting has a string key and a value that can be anything
  representable in JSON (string, number, boolean, None, or arbitrarily nested
  lists or dictionaries thereof).  The value is stored internally using JSON.
  """

  # The value of the configuration item, serialized to JSON.
  value_json = db.TextProperty()

  @staticmethod
  def Get(key, default=None):
    """Fetches the configuration value for a given key.

    Args:
      key: A string, the name of the configuration item to get.
      default: The default value to return if no such configuration item exists.

    Returns:
      The configuration value, or the given default value if not found, or
      None if no default value is supplied.
    """

    def Fetcher():
      config = Config.get_by_key_name(key)
      if config:
        return json.loads(config.value_json)
      return default
    return cache.Get([Config, key], Fetcher)

  @staticmethod
  def Set(key, value):
    """Sets a configuration value.

    Args:
      key: A string, the name of the configuration item to get.
      value: Any Python data structure that can be serialized to JSON.
    """
    config = Config(key_name=key, value_json=json.dumps(value))
    config.put()
    cache.Delete([Config, key])


def GetUserDomain(user):
  """Extracts the domain part of a User object's email address.

  Args:
    user: A google.appengine.api.users.User object.

  Returns:
    A string, the part after the '@' in the user's e-mail address, or None.
  """
  return user and '@' in user.email() and user.email().split('@')[-1]


def SetInitialDomainRole(domain, role):
  """Sets the domain_role to apply to newly created maps for a given domain.

  Args:
    domain: A domain name.
    role: A Role constant, or None.
  """
  Config.Set('initial_domain_role:' + domain, role)


def GetInitialDomainRole(domain):
  """Gets the domain_role to apply to newly created maps for a given domain.

  Args:
    domain: A domain name.

  Returns:
    A Role constant, or None.
  """
  return Config.Get('initial_domain_role:' + domain)


def SetGlobalRoles(email_or_domain, roles):
  """Sets the access roles for a given user or domain that apply to all maps.

  Args:
    email_or_domain: A string, either an e-mail address or a domain name.
    roles: A list of roles (see Role) that the user or domain should have.
        The CATALOG_EDITOR access role for a particular domain should be
        specified as a two-item list: [Role.CATALOG_EDITOR, domain].
  """
  Config.Set('global_roles:' + email_or_domain, roles)


def GetGlobalRoles(email_or_domain):
  """Gets the access roles for a given user or domain that apply to all maps.

  Args:
    email_or_domain: An e-mail address or a domain name.

  Returns:
    The list of global roles (see Role) that the user or domain has.
    The CATALOG_EDITOR access role for a particular domain is specified as
    a two-item list: [Role.CATALOG_EDITOR, domain].
  """
  return Config.Get('global_roles:' + email_or_domain, [])


def GetDomainsWithRole(role, user=None):
  """Gets the domains for which the given user has the given type of access.

  Args:
    role: A Role constant.
    user: A google.appengine.api.users.User object, or None.

  Returns:
    A list of strings (domain names).  Note that users with ADMIN access will
    actually have access for all domains, but the result will only include the
    domains that are specifically granted to the user or the user's domain.
  """
  user = user or users.get_current_user()
  email, domain = user.email(), GetUserDomain(user)
  domains = set()
  for item in GetGlobalRoles(email) + GetGlobalRoles(domain):
    if isinstance(item, list) and item[0] == role:
      domains.add(item[1])
  return sorted(domains)


class AccessPolicy(object):
  """Wraps up authorization for user actions."""

  def HasRoleAdmin(self, user):
    """Returns True if a user should get ADMIN access."""
    # Users get admin access if they have global admin access or if they
    # have App Engine administrator permission for this app.
    return user and (self.HasGlobalRole(user, Role.ADMIN) or
                     (user == users.get_current_user() and
                      users.is_current_user_admin()))

  def HasRoleCatalogEditor(self, user, domain):
    """Returns True if a user should get CATALOG_EDITOR access for a domain."""
    # Users get catalog editor access if they have catalog editor access to the
    # specified domain, if they have catalog editor access to all domains, or
    # if they have admin access.
    return user and (self.HasGlobalRole(user, [Role.CATALOG_EDITOR, domain]) or
                     self.HasGlobalRole(user, Role.CATALOG_EDITOR) or
                     self.HasRoleAdmin(user))

  def HasRoleMapCreator(self, user, domain):
    """Returns True if a user should get MAP_CREATOR access."""
    # Users get creator access if they have global map creator access or if
    # they have admin access.
    return user and (self.HasGlobalRole(user, [Role.MAP_CREATOR, domain]) or
                     self.HasRoleAdmin(user))

  def HasRoleMapOwner(self, user, map_object):
    """Returns True if a user should get MAP_OWNER access to a given map."""
    # Users get owner access if they are in the owners list for the map, if
    # their domain is an owner of the map, if they have global owner access
    # to all maps, or if they have admin access.
    return user and (user.email() in map_object.owners or
                     self.HasDomainRole(user, Role.MAP_OWNER, map_object) or
                     self.HasGlobalRole(user, Role.MAP_OWNER) or
                     self.HasRoleAdmin(user))

  def HasRoleMapEditor(self, user, map_object):
    """Returns True if a user should get MAP_EDITOR access to a given map."""
    # Users get editor access if they are in the editors list for the map, if
    # their domain is an editor of the map, if they have global editor access
    # to all maps, or if they have owner access.
    return user and (user.email() in map_object.editors or
                     self.HasDomainRole(user, Role.MAP_EDITOR, map_object) or
                     self.HasGlobalRole(user, Role.MAP_EDITOR) or
                     self.HasRoleMapOwner(user, map_object))

  def HasRoleMapViewer(self, user, map_object):
    """Returns True if the user has MAP_VIEWER access to a given map."""
    # Users get viewer access if the map is world-readable, if they are in the
    # viewers list for the map, if their domain is a viewer of the map, if they
    # have global viewer access to all maps, or if they have editor access.
    return (map_object.world_readable or
            user and (user.email() in map_object.viewers or
                      self.HasDomainRole(user, Role.MAP_VIEWER, map_object) or
                      self.HasGlobalRole(user, Role.MAP_VIEWER) or
                      self.HasRoleMapEditor(user, map_object)))

  def HasDomainRole(self, user, role, map_object):
    """Returns True if the user's domain has the given access to the map."""
    return user and (GetUserDomain(user) in map_object.domains and
                     role == map_object.domain_role)

  def HasGlobalRole(self, user, role):
    """Returns True if the user or user's domain has the given role globally."""
    return user and (role in GetGlobalRoles(user.email()) or
                     role in GetGlobalRoles(GetUserDomain(user)))


def CheckAccess(role, target=None, user=None, policy=None):
  """Checks whether the given user has the specified access role.

  Args:
    role: A Role constant identifying the desired access role.
    target: The object to which access is desired.  If 'role' is MAP_OWNER,
        MAP_EDITOR, or MAP_VIEWER, this should be a Map object.  If 'role' is
        CATALOG_EDITOR, this must be a domain name (a string).  For other
        roles, this argument is not used.
    user: (optional) A google.appengine.api.users.User object.  If not
        specified, access permissions are checked for the current user.
    policy: The access policy to apply.

  Returns:
    True if the user has the specified access permission.

  Raises:
    ValueError: The specified role is not a valid member of Role.
  """

  def RequireTargetClass(required_cls, cls_desc):
    if not isinstance(target, required_cls):
      raise ValueError('For role %r, target must be a %s' % (role, cls_desc))

  policy = policy or AccessPolicy()
  user = user or users.get_current_user()

  # Roles that are unrelated to a target.
  if role == Role.ADMIN:
    return policy.HasRoleAdmin(user)

  # Roles with a domain as the target.
  if role == Role.CATALOG_EDITOR:
    RequireTargetClass(basestring, 'string')
    return policy.HasRoleCatalogEditor(user, target)
  if role == Role.MAP_CREATOR:
    RequireTargetClass(basestring, 'string')
    return policy.HasRoleMapCreator(user, target)

  # Roles with a Map as the target
  RequireTargetClass(Map, 'Map')
  if role == Role.MAP_OWNER:
    return policy.HasRoleMapOwner(user, target)
  if role == Role.MAP_EDITOR:
    return policy.HasRoleMapEditor(user, target)
  if role == Role.MAP_VIEWER:
    return policy.HasRoleMapViewer(user, target)

  raise ValueError('Invalid role %r' % role)


def AssertAccess(role, target=None, user=None, policy=None):
  """Requires that the given user has the specified access role.

  Args:
    role: A Role constant identifying the desired access role.
    target: The object to which access is desired.  If 'role' is MAP_OWNER,
        MAP_EDITOR, or MAP_VIEWER, this should be a Map object.  If 'role' is
        CATALOG_EDITOR or MAP_CREATOR, this must be a domain name (a string).
        For other roles, this argument is not used.
    user: (optional) A google.appengine.api.users.User object.  If not
        specified, access permissions are checked for the current user.
    policy: The access policy to apply.

  Raises:
    AuthorizationError: If the user lacks the given access permission.
  """
  user = user or users.get_current_user()  # ensure user is set in error message
  if not CheckAccess(role, target, user, policy):
    raise AuthorizationError(user, role, target)


def DoAsAdmin(function, *args, **kwargs):
  """Executes a function with admin privileges for the duration of the call."""
  original_info = {
      'USER_IS_ADMIN': os.environ.get('USER_IS_ADMIN', '0'),
      'USER_EMAIL': os.environ.get('USER_EMAIL', ''),
      'USER_ID': os.environ.get('USER_ID', '')
  }
  try:
    os.environ.update({
        'USER_IS_ADMIN': '1',
        'USER_EMAIL': 'root@google.com',
        'USER_ID': '0'
    })
    return function(*args, **kwargs)
  finally:
    os.environ.update(original_info)


class MapVersionModel(db.Model):
  """A particular version of the JSON content of a Map.

  NOTE: This class is private to this module; outside code should use the Map
  class to create or access versions.

  If this entity is constructed properly, its parent entity will be a MapModel.
  """

  # The JSON string representing the map content, in MapRoot format.
  maproot_json = db.TextProperty()

  # Fields below are metadata for those with edit access, not for public
  # display.  No last_updated field is needed; these objects are immutable.
  creator = db.UserProperty(auto_current_user_add=True)
  created = db.DateTimeProperty(auto_now_add=True)


class MapModel(db.Model):
  """A single map object and its associated metadata; parent of its versions.

  NOTE: This class is private to this module; outside code should use the Map
  class to create or access maps.

  The key_name is a unique map name chosen by the creator.  The latest version
  of the map is what's shown to viewers.
  """

  # Title for the current version.  Cached from the current version for display.
  # Plain text.
  title = db.StringProperty()

  # HTML description of the map.  Cached from current version for display.
  description = db.TextProperty()

  # Metadata for auditing and debugging purposes.
  created = db.DateTimeProperty(auto_now_add=True)
  creator = db.UserProperty(auto_current_user_add=True)
  last_updated = db.DateTimeProperty(auto_now=True)
  last_updater = db.UserProperty(auto_current_user=True)

  # List of users who can set the flags and permission lists on this object.
  owners = db.StringListProperty()

  # List of individual users who can edit this map.
  editors = db.StringListProperty()

  # List of individual users who can view the current version of this map.
  viewers = db.StringListProperty()

  # List of domains that this map belongs to.
  # CAUTION: for not google domains this is potentially problematic,
  # since there may not be a google apps domain that corresponds to the
  # gaia ids (and hence no management).
  domains = db.StringListProperty()

  # Default role for users in one of the domains listed in the domains property.
  # domain_role can be set to admin, but we won't honor it.
  domain_role = db.StringProperty(choices=list(Role))

  # World-readable maps can be viewed by anyone.
  world_readable = db.BooleanProperty(default=False)

  # Cache of the most recent MapVersion.
  current_version = db.ReferenceProperty(reference_class=MapVersionModel)

  # Whether the map is deleted. This is lazy deletion, so MapModel or
  # MapVersionModel entities related to this map are not actually deleted. If
  # this flag is set, then the map is unreachable by users. If this value is
  # set to true, it can only be reversed within the Datastore.
  is_deleted = db.BooleanProperty(default=False)


class CatalogEntryModel(db.Model):
  """A mapping from a (publisher domain, publication label) pair to a map.

  NOTE: This class is private to this module; outside code should use the
  CatalogEntry class to create or access catalog entries.

  The existence of a CatalogEntryModel with key_name "<domain>:<label>" causes
  the map to be available at the URL .../crisismap/a/<domain>/<label>.
  The catalog entry is like a snapshot; it points at a single MapVersionModel,
  so changes to the Map (i.e. new versions of the Map content) don't appear at
  .../crisismap/foo until the catalog entry is repointed at the new version.

  Each domain has a menu of maps (an instance of cm.MapPicker) that is shown
  on all the published map pages for that domain.  The menu shows a subset of
  the catalog entries in that domain, as selected by the is_listed flag.
  """

  # The domain and label (these are redundant with the key_name of the entity,
  # but broken out as separate properties so queries can filter on them).
  domain = db.StringProperty()
  label = db.StringProperty()

  # Metadata about the catalog entry itself.
  creator = db.UserProperty(auto_current_user_add=True)
  created = db.DateTimeProperty(auto_now_add=True)
  last_updated = db.DateTimeProperty(auto_now=True)
  last_updater = db.UserProperty(auto_current_user=True)

  # The displayed title (in the crisis picker).  Set from the map_object.
  title = db.StringProperty()

  # The key_name of the map_version's parent MapModel (this is redundant with
  # map_version, but broken out as a property so queries can filter on it).
  map_id = db.StringProperty()

  # Reference to the map version published by this catalog entry.
  map_version = db.ReferenceProperty(MapVersionModel)

  # If true, this entry is shown in its domain's cm.MapPicker menu.
  is_listed = db.BooleanProperty(default=False)

  @staticmethod
  def Get(domain, label):
    return CatalogEntryModel.get_by_key_name(domain + ':' + label)

  @staticmethod
  def All():
    """Yields all CatalogEntryModels in reverse update order."""
    return CatalogEntryModel.all().order('-last_updated')

  @staticmethod
  def AllListed():
    """Yields all listed CatalogEntryModels in reverse update order."""
    return CatalogEntryModel.All().filter('is_listed =', True)

  @staticmethod
  def AllInDomain(domain):
    """Yields CatalogEntryModels in a domain in reverse update order."""
    return CatalogEntryModel.All().filter('domain =', domain)

  @staticmethod
  def AllListedInDomain(domain):
    """Yields listed CatalogEntryModels in a domain in reverse update order."""
    return CatalogEntryModel.AllListed().filter('domain =', domain)

  @staticmethod
  def Create(domain, label, map_object, is_listed=False):
    """Stores a CatalogEntryModel pointing at the map's current version."""
    entity = CatalogEntryModel(key_name=domain + ':' + label, domain=domain,
                               label=label, title=map_object.title,
                               map_id=map_object.id,
                               map_version=map_object.GetCurrent().key,
                               is_listed=is_listed)
    entity.put()
    return entity


class CatalogEntry(object):
  """An access control wrapper around the CatalogEntryModel entity.

  All access from outside this module should go through CatalogEntry (never
  CatalogEntryModel).  Entries should always be created via CatalogEntry.Create.

  The MapRoot JSON content of a CatalogEntry is always considered publicly
  readable, independent of the permission settings on the Map object.
  """

  def __init__(self, catalog_entry_model):
    """Constructor not to be called directly.  Use Create instead."""
    self.model = catalog_entry_model

  @staticmethod
  def Get(domain, label):
    """Returns the CatalogEntry for a domain and label if it exists, or None."""
    # We reserve the label 'empty' in all domains for a catalog entry pointing
    # at the empty map.  Handy for development.
    if label == 'empty':
      return EmptyCatalogEntry(domain)

    # No access control; all catalog entries are publicly visible.
    model = CatalogEntryModel.Get(domain, label)
    return model and CatalogEntry(model)

  @staticmethod
  def GetAll():
    """Gets all entries in all domains, in reverse update order."""
    # No access control; all catalog entries are publicly visible.
    # We use '*' in the cache key for the list that includes all domains.
    return cache.Get([CatalogEntry, '*', 'all'],
                     lambda: map(CatalogEntry, CatalogEntryModel.All()))

  @staticmethod
  def GetListed():
    """Gets all the listed entries in all domains, in reverse update order."""
    # No access control; all catalog entries are publicly visible.
    # We use '*' in the cache key for the list that includes all domains.
    return cache.Get([CatalogEntry, '*', 'listed'],
                     lambda: map(CatalogEntry, CatalogEntryModel.AllListed()))

  @staticmethod
  def GetByMapId(map_id):
    """Returns all entries that belong to a particular map."""
    return map(CatalogEntry, CatalogEntryModel.All().filter('map_id =', map_id))

  @staticmethod
  def GetAllInDomain(domain):
    """Gets all the entries in a domain, in reverse update order."""
    # No access control; all catalog entries are publicly visible.
    return cache.Get(
        [CatalogEntry, domain, 'all'],
        lambda: map(CatalogEntry, CatalogEntryModel.AllInDomain(domain)))

  @staticmethod
  def GetListedInDomain(domain):
    """Gets all the listed entries in a domain, in reverse update order."""
    # No access control; all catalog entries are publicly visible.
    return cache.Get(
        [CatalogEntry, domain, 'listed'],
        lambda: map(CatalogEntry, CatalogEntryModel.AllListedInDomain(domain)))

  @staticmethod
  def Create(domain, label, map_object, is_listed=False):
    """Stores a new CatalogEntry with version set to the map's current version.

    This method will overwrite an existing entry with the same name.

    Args:
      domain: The domain in which to create the CatalogEntry.
      label: The publication label to use for this map.
      map_object: The Map object whose current version to use.
      is_listed: If True, show this entry in the map picker menu.
    Returns:
      The new CatalogEntry object.
    Raises:
      ValueError: If the domain string is invalid.
    """
    domain = str(domain)  # accommodate Unicode strings
    if ':' in domain:
      raise ValueError('Invalid domain %r' % domain)
    AssertAccess(Role.CATALOG_EDITOR, domain)
    model = CatalogEntryModel.Create(domain, label, map_object, is_listed)

    # We use '*' in the cache key for the list that includes all domains.
    cache.Delete([CatalogEntry, '*', 'all'])
    cache.Delete([CatalogEntry, '*', 'listed'])
    cache.Delete([CatalogEntry, domain, 'all'])
    cache.Delete([CatalogEntry, domain, 'listed'])
    return CatalogEntry(model)

  @staticmethod
  def Delete(domain, label):
    """Deletes an existing CatalogEntry.

    Args:
      domain: The domain to which the CatalogEntry belongs.
      label: The publication label.

    Raises:
      ValueError: if there's no CatalogEntry with the given domain and label.
    """
    domain = str(domain)  # accommodate Unicode strings
    AssertAccess(Role.CATALOG_EDITOR, domain)
    entry = CatalogEntryModel.Get(domain, label)
    if not entry:
      raise ValueError('No CatalogEntry %r in domain %r' % (label, domain))
    entry.delete()
    # We use '*' in the cache key for the list that includes all domains.
    cache.Delete([CatalogEntry, '*', 'all'])
    cache.Delete([CatalogEntry, '*', 'listed'])
    cache.Delete([CatalogEntry, domain, 'all'])
    cache.Delete([CatalogEntry, domain, 'listed'])

  is_listed = property(
      lambda self: self.model.is_listed,
      lambda self, value: setattr(self.model, 'is_listed', value))

  # The datastore key of this catalog entry's MapVersionModel.
  def GetMapVersionKey(self):
    return CatalogEntryModel.map_version.get_value_for_datastore(self.model)
  map_version_key = property(GetMapVersionKey)

  # maproot_json gets the (possibly cached) MapRoot JSON for this entry.
  def GetMaprootJson(self):
    return cache.Get([CatalogEntry, self.domain, self.label, 'json'],
                     lambda: self.model.map_version.maproot_json)
  maproot_json = property(GetMaprootJson)

  # Make the other properties of the CatalogEntryModel visible on CatalogEntry.
  for x in ['domain', 'label', 'map_id', 'title', 'creator', 'created',
            'last_updated', 'last_updater']:
    locals()[x] = property(lambda self, x=x: getattr(self.model, x))

  def SetMapVersion(self, map_object):
    """Points this entry at the specified MapVersionModel."""
    self.model.map_id = map_object.id
    self.model.map_version = map_object.GetCurrent().key
    self.model.title = map_object.title

  def Put(self):
    """Saves any modifications to the datastore."""
    domain = str(self.domain)  # accommodate Unicode strings
    AssertAccess(Role.CATALOG_EDITOR, domain)
    self.model.put()
    # We use '*' in the cache key for the list that includes all domains.
    cache.Delete([CatalogEntry, '*', 'all'])
    cache.Delete([CatalogEntry, '*', 'listed'])
    cache.Delete([CatalogEntry, domain, 'all'])
    cache.Delete([CatalogEntry, domain, 'listed'])
    cache.Delete([CatalogEntry, domain, self.label, 'json'])


class Map(object):
  """An access control wrapper around the MapModel entity.

  All access from outside this module should go through Map (never MapModel).
  Maps should always be created with Map.Create, which ensures that every map
  has at least one version.
  """

  # NOTE(kpy): Every public method should call self.AssertAccess(...) first!

  NAMESPACE = 'Map'  # cache namespace

  def __init__(self, map_model):
    """Constructor not to be called directly."""
    self.model = map_model

  def __eq__(self, other):
    return isinstance(other, Map) and self.model.key() == other.model.key()

  def __hash__(self):
    return hash(self.model)

  # The datastore key for this map's MapModel entity.
  key = property(lambda self: self.model.key())

  # The datastore key for this map's latest MapVersionModel.
  current_version_key = property(
      lambda self: MapModel.current_version.get_value_for_datastore(self.model))

  # Map IDs are in base64, so they are safely convertible from Unicode to ASCII.
  id = property(lambda self: str(self.model.key().name()))

  # Make the other properties of the underlying MapModel readable on the Map.
  for x in ['creator', 'created', 'last_updated', 'last_updater',
            'title', 'description', 'current_version', 'world_readable',
            'owners', 'editors', 'viewers', 'domains', 'domain_role']:
    locals()[x] = property(lambda self, x=x: getattr(self.model, x))

  @staticmethod
  def get(key):  # lowercase to match db.Model.get  # pylint: disable=g-bad-name
    return Map(MapModel.get(key))

  @staticmethod
  def _GetAll():
    """Yields all non-deleted maps in reverse update order.  NO ACCESS CHECK."""
    for model in MapModel.all().order('-last_updated').filter(
        'is_deleted = ', False):
      yield Map(model)

  @staticmethod
  def GetAll():
    """Yields all maps in reverse update order."""
    AssertAccess(Role.ADMIN)
    return Map._GetAll()

  @staticmethod
  def GetViewable():
    """Yields all maps visible to the user in the same order as GetAll."""
    # TODO(lschumacher): This probably won't scale to a large number of maps.
    # Also, we should only project the fields we want.
    user = users.get_current_user()
    # Share the AccessPolicy object to avoid fetching access lists repeatedly.
    policy = AccessPolicy()
    for m in Map._GetAll():
      if m.CheckAccess(Role.MAP_VIEWER, user, policy=policy):
        yield m

  @staticmethod
  def Get(key_name):
    """Gets a Map by its map ID (key_name), or returns None if none exists."""
    # We reserve the special ID '0' for an empty map.  Handy for development.
    if key_name == '0':
      return EmptyMap()
    model = MapModel.get_by_key_name(key_name)
    if not model or model.is_deleted:
      return None
    map_object = Map(model)
    map_object.AssertAccess(Role.MAP_VIEWER)
    return map_object

  @staticmethod
  def Create(maproot_json, domain, owners=None, editors=None, viewers=None,
             domain_role=None, world_readable=False):
    """Stores a new map with the given properties and MapRoot JSON content."""
    # maproot_json must be syntactically valid JSON, but otherwise any JSON
    # object is allowed; we don't check for MapRoot validity here.
    AssertAccess(Role.MAP_CREATOR, domain)
    if owners is None:
      owners = [users.get_current_user().email()]
    if editors is None:
      editors = []
    if viewers is None:
      viewers = []
    # urlsafe_b64encode encodes 12 random bytes as exactly 16 characters,
    # which can include digits, letters, hyphens, and underscores.  Because
    # the length is a multiple of 4, it won't have trailing "=" signs.
    map_object = Map(MapModel(
        key_name=base64.urlsafe_b64encode(
            ''.join(chr(random.randrange(256)) for i in xrange(12))),
        owners=owners, editors=editors, viewers=viewers, domains=[domain],
        domain_role=domain_role, world_readable=world_readable))
    map_object.PutNewVersion(maproot_json)  # also puts the MapModel
    return map_object

  @staticmethod
  def _GetVersionByKey(key):
    """Returns a map version by its datastore entity key.  NO ACCESS CHECK."""
    return StructFromModel(MapVersionModel.get(key))

  def PutNewVersion(self, maproot_json):
    """Stores a new MapVersionModel object for this Map and returns its ID."""
    self.AssertAccess(Role.MAP_EDITOR)
    maproot = json.loads(maproot_json)  # validate the JSON first

    new_version = MapVersionModel(parent=self.model, maproot_json=maproot_json)
    # Update the MapModel from fields in the MapRoot JSON.
    self.model.title = maproot.get('title', '')
    self.model.description = maproot.get('description', '')

    def PutModels():
      self.model.current_version = new_version.put()
      self.model.put()
    db.run_in_transaction(PutModels)
    cache.Delete([Map, self.id, 'json'])
    return new_version.key().id()

  def GetCurrent(self):
    """Gets this map's latest version.

    Returns:
      A Struct with the properties of this map's current version, along with
      a property 'id' containing the version's ID; or None if the current
      version has not been set.  (Version IDs are not necessarily in creation
      order, and are unique within a particular Map but not across all Maps.)
    """
    self.AssertAccess(Role.MAP_VIEWER)
    return self.current_version and StructFromModel(self.current_version)

  def Delete(self):
    """Deletes the map.

    Sets a flag on the entity without actually removing it from the datastore.
    """
    self.AssertAccess(Role.MAP_OWNER)
    self.model.is_deleted = True
    self.model.put()
    cache.Delete([Map, self.id, 'json'])

  def GetCurrentJson(self):
    """Gets the current JSON for public viewing only."""
    self.AssertAccess(Role.MAP_VIEWER)
    return cache.Get([Map, self.id, 'json'],
                     lambda: getattr(self.GetCurrent(), 'maproot_json', None))

  def GetVersions(self):
    """Yields all versions of this map in order from newest to oldest."""
    self.AssertAccess(Role.MAP_EDITOR)
    query = MapVersionModel.all().ancestor(self.model).order('-created')
    return ResultIterator(query)

  def GetVersion(self, version_id):
    """Returns a specific version of this map."""
    self.AssertAccess(Role.MAP_EDITOR)
    version = MapVersionModel.get_by_id(version_id, parent=self.model.key())
    return StructFromModel(version)

  def SetWorldReadable(self, world_readable):
    """Sets whether the map is world-readable."""
    self.AssertAccess(Role.MAP_OWNER)
    self.model.world_readable = world_readable
    self.model.put()

  def RevokePermission(self, role, user):
    """Revokes user permissions for the map."""
    self.AssertAccess(Role.MAP_OWNER)
    email = str(user.email())  # The lists need basic strings.
    # Does nothing if the user does not have the role to begin with or if
    # the role is not editor, viewer, or owner.
    if role == Role.MAP_VIEWER and email in self.model.viewers:
      self.model.viewers.remove(email)
    elif role == Role.MAP_EDITOR and email in self.model.editors:
      self.model.editors.remove(email)
    elif role == Role.MAP_OWNER and email in self.model.owners:
      self.model.owners.remove(email)
    self.model.put()

  def ChangePermissionLevel(self, role, user):
    """Changes the user's level of permission."""
    # When a user's permission is changed to viewer, editor, or owner,
    # their former permission level is revoked.
    # Does nothing if role is not in permissions.
    self.AssertAccess(Role.MAP_OWNER)
    email = str(user.email())  # The lists need basic strings.
    permissions = [Role.MAP_VIEWER, Role.MAP_EDITOR, Role.MAP_OWNER]
    if role not in permissions:
      return
    elif role == Role.MAP_VIEWER and email not in self.model.viewers:
      self.model.viewers.append(email)
    elif role == Role.MAP_EDITOR and email not in self.model.editors:
      self.model.editors.append(email)
    elif role == Role.MAP_OWNER and email not in self.model.owners:
      self.model.owners.append(email)

    # Take away the other permissions
    for permission in permissions:
      if permission != role:
        self.RevokePermission(permission, user)
    self.model.put()

  def CheckAccess(self, role, user=None, policy=None):
    """Checks whether a user has the specified access role for this map."""
    return CheckAccess(role, self, user, policy=policy)

  def AssertAccess(self, role, user=None, policy=None):
    """Requires a user to have the specified access role for this map."""
    AssertAccess(role, self, user, policy=policy)


class EmptyMap(Map):
  """An empty stand-in for a Map object (handy for development)."""

  # To ensure that the app has something to display, we return this special
  # empty map object as the map with ID '0'.
  TITLE = 'Empty map'
  DESCRIPTION = 'This is an empty map for testing.'
  JSON = '{"title": "%s", "description": "%s"}' % (TITLE, DESCRIPTION)

  def __init__(self):
    Map.__init__(self, MapModel(
        key_name='0', owners=[], editors=[], viewers=[], domains=[],
        world_readable=True, title=self.TITLE, description=self.DESCRIPTION))

  def GetCurrent(self):
    key = db.Key.from_path('MapModel', '0', 'MapVersionModel', 1)
    return Struct(id=1, key=key, maproot_json=self.JSON)

  def GetVersions(self):
    return [self.GetCurrent()]

  def GetVersion(self, version_id):
    if version_id == 1:
      return self.GetCurrent()

  def ReadOnlyError(self, *unused_args, **unused_kwargs):
    raise TypeError('EmptyMap is read-only')

  SetWorldReadable = ReadOnlyError
  PutNewVersion = ReadOnlyError
  Delete = ReadOnlyError
  RevokePermission = ReadOnlyError
  ChangePermissionLevel = ReadOnlyError


class EmptyCatalogEntry(CatalogEntry):
  """An empty stand-in for a CatalogEntry object (handy for development)."""

  # To ensure that the app has something to display, we return this special
  # catalog entry as the entry with label 'empty' in all domains.
  def __init__(self, domain):
    CatalogEntry.__init__(self, CatalogEntryModel(
        domain=domain, label='empty', title=EmptyMap.TITLE, map_id='0'))

  maproot_json = property(lambda self: EmptyMap.JSON)

  def ReadOnlyError(self, *unused_args, **unused_kwargs):
    raise TypeError('EmptyCatalogEntry is read-only')

  SetMapVersion = ReadOnlyError
  Put = ReadOnlyError
