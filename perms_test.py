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

"""Unit tests for perms.py."""

import domains
import model
import perms
import test_utils


def GetRolesForMap(map_object):
  """Gets the set of all roles that the current user has for a MapModel."""
  return {r for r in perms.MAP_ROLES if perms.CheckAccess(r, target=map_object)}


class PermsTests(test_utils.BaseTest):

  def testUserRoles(self):  # pylint: disable=too-many-statements
    """Verifies that access permissions restrict user actions correctly."""
    m = test_utils.CreateMap(
        owners=['owner'], editors=['editor'], reviewers=['reviewer'],
        viewers=['viewer'])

    with test_utils.RootLogin():
      # An admin should have all map roles.
      self.assertEquals(set(perms.MAP_ROLES), GetRolesForMap(m))

      # Verify an admin can perform all operations.
      model.Map.Get(m.id)
      version_id = m.PutNewVersion({})
      m.SetWorldReadable(False)
      m.GetVersions()
      m.GetVersion(version_id)

    with test_utils.Login('owner'):
      # An owner should have all roles.
      self.assertEquals(set(perms.MAP_ROLES), GetRolesForMap(m))

      # Verify the owner can perform expected operations.
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')
      model.Map.Get(m.id)
      version_id = m.PutNewVersion({})
      m.SetWorldReadable(False)
      m.GetVersions()
      m.GetVersion(version_id)

    with test_utils.Login('editor'):
      # Check editor roles.
      self.assertEquals({'MAP_EDITOR', 'MAP_REVIEWER', 'MAP_VIEWER'},
                        GetRolesForMap(m))

      # Verify the editor can perform expected operations.
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')
      model.Map.Get(m.id)
      version_id = m.PutNewVersion({})
      self.assertRaises(perms.AuthorizationError, m.SetWorldReadable, False)
      m.GetVersions()
      m.GetVersion(version_id)

    with test_utils.Login('reviewer'):
      # Check reviewer roles.
      self.assertEquals({'MAP_REVIEWER', 'MAP_VIEWER'}, GetRolesForMap(m))

      # Verify the reviewer can perform expected operations.
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')
      model.Map.Get(m.id)
      self.assertRaises(perms.AuthorizationError, m.PutNewVersion, {})
      self.assertRaises(perms.AuthorizationError, m.GetVersion, version_id)
      self.assertRaises(perms.AuthorizationError, m.GetVersions)

    with test_utils.Login('viewer'):
      # Check viewer roles.
      self.assertEquals({'MAP_VIEWER'}, GetRolesForMap(m))

      # Verify the viewer can perform expected operations.
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')
      model.Map.Get(m.id)
      self.assertRaises(perms.AuthorizationError, m.PutNewVersion, {})
      self.assertRaises(perms.AuthorizationError, m.GetVersion, version_id)
      self.assertRaises(perms.AuthorizationError, m.GetVersions)

    with test_utils.Login('outsider'):
      # Check roles for an unknown user.
      self.assertEquals(set(), GetRolesForMap(m))

      # Verify that all operations fail.
      self.assertRaises(perms.AuthorizationError, model.Map.Get, m.id)
      self.assertRaises(perms.AuthorizationError, m.PutNewVersion, {})
      self.assertRaises(perms.AuthorizationError, m.GetVersions)
      self.assertRaises(perms.AuthorizationError, m.GetVersion, version_id)

      # Check roles for an unknown user on a world-readable map.
      m.model.world_readable = True
      self.assertEquals({'MAP_VIEWER'}, GetRolesForMap(m))

      # Verify the user can perform only the expected operations.
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')
      self.assertRaises(perms.AuthorizationError, m.PutNewVersion, {})
      self.assertRaises(perms.AuthorizationError, m.SetWorldReadable, True)
      self.assertRaises(perms.AuthorizationError, m.GetVersion, version_id)
      self.assertRaises(perms.AuthorizationError, m.GetVersions)

  def testDomainRoles(self):
    """Verifies that domain access permissions restrict actions correctly."""
    with test_utils.RootLogin():
      domains.Domain.Put('foo.com', initial_domain_role=perms.Role.MAP_OWNER)
      m = model.Map.Create({}, 'foo.com')

    # Verify that a user in foo.com gets the domain role for foo.com.
    with test_utils.DomainLogin('insider', 'foo.com'):
      self.assertEquals(
          {'MAP_OWNER', 'MAP_EDITOR', 'MAP_REVIEWER', 'MAP_VIEWER'},
          GetRolesForMap(m))

      m.model.domain_role = perms.Role.MAP_EDITOR
      self.assertEquals({'MAP_EDITOR', 'MAP_REVIEWER', 'MAP_VIEWER'},
                        GetRolesForMap(m))

      m.model.domain_role = perms.Role.MAP_REVIEWER
      self.assertEquals({'MAP_REVIEWER', 'MAP_VIEWER'}, GetRolesForMap(m))

      m.model.domain_role = perms.Role.MAP_VIEWER
      self.assertEquals({'MAP_VIEWER'}, GetRolesForMap(m))

  def testMapCreatorDomains(self):
    """Verifies that the map_creator_domains setting is respected."""
    perms.Grant('foo.com', perms.Role.MAP_CREATOR, 'xyz.com')

    # All users at foo.com have the CREATOR role for xyz.com.
    with test_utils.DomainLogin('insider', 'foo.com'):
      self.assertTrue(perms.CheckAccess(perms.Role.MAP_CREATOR, 'xyz.com'))
      self.assertFalse(perms.CheckAccess(perms.Role.ADMIN))
      model.Map.Create({}, 'xyz.com')

    # Users in bar.com don't have the CREATOR role.
    with test_utils.DomainLogin('outsider', 'bar.com'):
      self.assertFalse(perms.CheckAccess(perms.Role.MAP_CREATOR, 'xyz.com'))
      self.assertRaises(
          perms.AuthorizationError, model.Map.Create, {}, 'xyz.com')

    # All users in gmail.test get MAP_CREATOR.
    perms.Grant('gmail.test', perms.Role.MAP_CREATOR, 'gmail.test')
    with test_utils.Login('gmail_user'):
      self.assertTrue(perms.CheckAccess(perms.Role.MAP_CREATOR, 'gmail.test'))

  def testDomainAdminRole(self):
    with test_utils.RootLogin():
      perms.Grant('xyz.com', perms.Role.DOMAIN_ADMIN, 'xyz.com')
      perms.Grant('outside_friend', perms.Role.DOMAIN_ADMIN, 'xyz.com')

    with test_utils.DomainLogin('insider', 'xyz.com'):
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_ADMIN, 'xyz.com'))
    with test_utils.DomainLogin('outside_friend', 'not-xyz.com'):
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_ADMIN, 'xyz.com'))
    with test_utils.Login('stranger'):
      self.assertFalse(perms.CheckAccess(perms.Role.DOMAIN_ADMIN, 'xyz.com'))
    with test_utils.DomainLogin('stranger_with_ga_domain', 'not-xyz.com'):
      self.assertFalse(perms.CheckAccess(perms.Role.DOMAIN_ADMIN, 'xyz.com'))
    with test_utils.RootLogin():
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_ADMIN, 'xyz.com'))

  def testDomainReviewerRole(self):
    with test_utils.RootLogin():
      perms.Grant('xyz.com', perms.Role.DOMAIN_REVIEWER, 'xyz.com')
      perms.Grant('outside_friend', perms.Role.DOMAIN_REVIEWER, 'xyz.com')

    with test_utils.DomainLogin('insider', 'xyz.com'):
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_REVIEWER, 'xyz.com'))
    with test_utils.DomainLogin('outside_friend', 'not-xyz.com'):
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_REVIEWER, 'xyz.com'))
    with test_utils.Login('stranger'):
      self.assertFalse(perms.CheckAccess(perms.Role.DOMAIN_REVIEWER, 'xyz.com'))
    with test_utils.DomainLogin('stranger_with_ga_domain', 'not-xyz.com'):
      self.assertFalse(perms.CheckAccess(perms.Role.DOMAIN_REVIEWER, 'xyz.com'))
    with test_utils.RootLogin():
      self.assertTrue(perms.CheckAccess(perms.Role.DOMAIN_REVIEWER, 'xyz.com'))

  def testCheckAccessRaisesOnBadTarget(self):
    m = test_utils.CreateMap()

    # Roles that require a domain as the target
    for role in (perms.Role.CATALOG_EDITOR, perms.Role.MAP_CREATOR):
      # Test both no target and a target of the wrong class
      self.assertRaises(TypeError, perms.CheckAccess, role)
      self.assertRaises(TypeError, perms.CheckAccess, role, target=m)

    # Roles that require a map as a target
    for role in (perms.Role.MAP_OWNER, perms.Role.MAP_EDITOR,
                 perms.Role.MAP_REVIEWER, perms.Role.MAP_VIEWER):
      # Test both no target and a target of the wrong class
      self.assertRaises(TypeError, perms.CheckAccess, role)
      self.assertRaises(TypeError, perms.CheckAccess, role, target='xyz.com')

  def testCheckAssertRaisesOnUnknownRole(self):
    self.assertFalse('NotARole' in perms.Role)
    self.assertRaises(ValueError, perms.CheckAccess, 'NotARole')

  def testNotSignedIn(self):
    m = test_utils.CreateMap()
    self.assertFalse(perms.CheckAccess(perms.Role.MAP_EDITOR, target=m))

  def testRevoke(self):
    subject, role, target = 'subject', perms.Role.CATALOG_EDITOR, 'xyz.com'
    perms.Grant(subject, role, target)
    with test_utils.Login('subject'):
      self.assertTrue(perms.CheckAccess(role, target))
      perms.Revoke(subject, role, target)
      self.assertFalse(perms.CheckAccess(role, target))

  def testIsUserId(self):
    self.assertTrue(perms.IsUserId('12345'))
    self.assertFalse(perms.IsUserId('flintstone.com'))
    self.assertFalse(perms.IsUserId(None))

  def testGetAccessibleDomains(self):
    privileged = test_utils.SetupUser(test_utils.Login('privileged'))
    outsider = test_utils.SetupUser(test_utils.Login('outsider'))
    with test_utils.RootLogin():
      perms.Grant('privileged', perms.Role.DOMAIN_REVIEWER, 'domain-rev.com')
      perms.Grant('privileged', perms.Role.MAP_CREATOR, 'map-creator.com')
      perms.Grant('privileged', perms.Role.CATALOG_EDITOR, 'catalog-editor.com')
      perms.Grant('privileged', perms.Role.DOMAIN_ADMIN, 'domain-admin.com')
      self.assertRaises(ValueError, perms.GetAccessibleDomains,
                        outsider, 'not-a-domain-role')
      self.assertEquals(
          {'domain-admin.com'},
          perms.GetAccessibleDomains(privileged, perms.Role.DOMAIN_ADMIN))
      self.assertEquals(
          {'domain-admin.com', 'catalog-editor.com'},
          perms.GetAccessibleDomains(privileged, perms.Role.CATALOG_EDITOR))
      self.assertEquals(
          {'domain-admin.com', 'catalog-editor.com', 'map-creator.com'},
          perms.GetAccessibleDomains(privileged, perms.Role.MAP_CREATOR))
      self.assertEquals(
          {'domain-admin.com', 'catalog-editor.com', 'map-creator.com',
           'domain-rev.com'},
          perms.GetAccessibleDomains(privileged, perms.Role.DOMAIN_REVIEWER))


if __name__ == '__main__':
  test_utils.main()
