from django.core.urlresolvers import reverse

from nose.tools import eq_, ok_

from mozillians.common.tests import TestCase
from mozillians.groups.tests import GroupFactory
from mozillians.users.tests import UserFactory


class TestGroupRemoveMember(TestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.member = UserFactory(userprofile={'is_vouched': True})
        self.group.add_member(self.member.userprofile)
        self.url = reverse('groups:remove_member', prefix='/en-US/',
                           kwargs={'group_pk': self.group.pk,
                                   'user_pk': self.member.userprofile.pk})

    def test_as_superuser(self):
        # superuser can remove another from a group they're not curator of
        user = UserFactory(is_superuser=True, userprofile={'is_vouched': True})
        with self.login(user) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(not self.group.has_member(self.member))

    def test_as_superuser_from_unleavable_group(self):
        # superuser can remove people even from unleavable groups
        user = UserFactory(is_superuser=True, userprofile={'is_vouched': True})
        with self.login(user) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(not self.group.has_member(self.member))

    def test_as_superuser_removing_curator(self):
        # but even superuser cannot remove a curator
        user = UserFactory(is_superuser=True, userprofile={'is_vouched': True})
        self.group.curator = self.member.userprofile
        self.group.save()
        with self.login(user) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(self.group.has_member(self.member))

    def test_as_simple_user_removing_self(self):
        # user can remove themselves
        with self.login(self.member) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(not self.group.has_member(self.member))

    def test_as_simple_user_removing_self_from_unleavable_group(self):
        # user cannot leave an unleavable group
        self.group.members_can_leave = False
        self.group.save()
        with self.login(self.member) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(self.group.has_member(self.member))

    def test_as_simple_user_removing_another(self):
        # user cannot remove anyone else
        user = UserFactory(userprofile={'is_vouched': True})
        with self.login(user) as client:
            response = client.post(self.url, follow=False)
        eq_(404, response.status_code)

    def test_as_curator(self):
        # curator can remove another
        curator = UserFactory(userprofile={'is_vouched': True})
        self.group.curator = curator.userprofile
        self.group.save()
        with self.login(curator) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(not self.group.has_member(self.member))

    def test_as_curator_from_unleavable(self):
        # curator can remove another even from an unleavable group
        self.group.members_can_leave = False
        self.group.save()
        curator = UserFactory(userprofile={'is_vouched': True})
        self.group.curator = curator.userprofile
        self.group.save()
        with self.login(curator) as client:
            response = client.post(self.url, follow=False)
        eq_(302, response.status_code)
        ok_(not self.group.has_member(self.member))
