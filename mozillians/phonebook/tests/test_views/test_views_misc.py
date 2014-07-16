import os.path
from datetime import datetime

from django.contrib.auth.models import User
from django.contrib.auth.views import logout as logout_view
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings

from mock import patch
from nose.tools import eq_, ok_
from waffle import Flag

from mozillians.common.tests import TestCase, requires_login, requires_vouch
from mozillians.phonebook.models import Invite
from mozillians.phonebook.tests import InviteFactory, _get_privacy_fields
from mozillians.users.managers import MOZILLIANS, PRIVILEGED, PUBLIC
from mozillians.users.models import UserProfilePrivacyModel
from mozillians.users.tests import UserFactory


class SearchTests(TestCase):
    def test_search_plugin_anonymous(self):
        client = Client()
        response = client.get(reverse('phonebook:search_plugin'), follow=True)
        eq_(response.status_code, 200)
        eq_(response.get('content-type'),
            'application/opensearchdescription+xml')

    def test_search_plugin_unvouched(self):
        user = UserFactory.create(vouched=False)
        with self.login(user) as client:
            response = client.get(reverse('phonebook:search_plugin'),
                                  follow=True)
        eq_(response.status_code, 200)
        eq_(response.get('content-type'),
            'application/opensearchdescription+xml')

    def test_search_plugin_vouched(self):
        user = UserFactory.create()
        with self.login(user) as client:
            response = client.get(reverse('phonebook:search_plugin'),
                                  follow=True)
        eq_(response.status_code, 200)
        eq_(response.get('content-type'),
            'application/opensearchdescription+xml')


class InviteTests(TestCase):
    @requires_login()
    def test_invite_anonymous(self):
        client = Client()
        client.get(reverse('phonebook:invite'), follow=True)

    @requires_vouch()
    def test_invite_unvouched(self):
        user = UserFactory.create(vouched=False)
        with self.login(user) as client:
            client.get(reverse('phonebook:invite'), follow=True)

    def test_invite_get_vouched(self):
        user = UserFactory.create()
        with self.login(user) as client:
            response = client.get(reverse('phonebook:invite'), follow=True)
        self.assertTemplateUsed(response, 'phonebook/invite.html')

    @override_settings(CAN_VOUCH_THRESHOLD=1)
    @patch('mozillians.phonebook.views.messages.success')
    def test_invite_post_vouched(self, success_mock):
        user = UserFactory.create()
        url = reverse('phonebook:invite', prefix='/en-US/')
        data = {
            'message': 'Join us foo!',
            'recipient': 'foo@example.com',
            'description': 'A test reason'
        }
        with self.login(user) as client:
            response = client.post(url, data, follow=True)
        self.assertTemplateUsed(response, 'phonebook/invite.html')
        ok_(Invite.objects
            .filter(recipient='foo@example.com', inviter=user.userprofile)
            .exists())
        ok_(success_mock.called)

    @override_settings(CAN_VOUCH_THRESHOLD=1)
    def test_invite_already_vouched(self):
        vouched_user = UserFactory.create()
        user = UserFactory.create()
        url = reverse('phonebook:invite', prefix='/en-US/')
        data = {'recipient': vouched_user.email}
        with self.login(user) as client:
            response = client.post(url, data, follow=True)
        self.assertTemplateUsed(response, 'phonebook/invite.html')
        ok_('recipient' in response.context['invite_form'].errors)
        eq_(Invite.objects.all().count(), 0)

    def test_invite_delete(self):
        user = UserFactory.create(userprofile={'is_vouched': True})
        invite = InviteFactory.create(inviter=user.userprofile)
        url = reverse('phonebook:delete_invite', prefix='/en-US/', kwargs={'invite_pk': invite.pk})
        with self.login(user) as client:
            response = client.post(url, follow=True)

        eq_(Invite.objects.all().count(), 0)
        eq_(response.status_code, 200)

    def test_invite_delete_invalid_requester(self):
        user = UserFactory.create(userprofile={'is_vouched': True})
        invite = InviteFactory.create(inviter=user.userprofile)
        url = reverse('phonebook:delete_invite', prefix='/en-US/', kwargs={'invite_pk': invite.pk})
        invalid_requester = UserFactory.create(userprofile={'is_vouched': True})
        with self.login(invalid_requester) as client:
            response = client.post(url)

        eq_(Invite.objects.all().count(), 1)
        eq_(response.status_code, 404)

    def test_invite_delete_redeemed(self):
        user = UserFactory.create(userprofile={'is_vouched': True})
        invite = InviteFactory.create(inviter=user.userprofile, redeemed=datetime.now())
        url = reverse('phonebook:delete_invite', prefix='/en-US/', kwargs={'invite_pk': invite.pk})
        with self.login(user) as client:
            response = client.post(url)

        eq_(Invite.objects.all().count(), 1)
        eq_(response.status_code, 404)

    def test_invite_delete_invalid_invite(self):
        user = UserFactory.create(userprofile={'is_vouched': True})
        url = reverse('phonebook:delete_invite', prefix='/en-US/', kwargs={'invite_pk': '1'})
        with self.login(user) as client:
            response = client.post(url)

        eq_(response.status_code, 404)


class VouchFormTests(TestCase):

    def test_vouch_not_vouched(self):
        user = UserFactory.create(vouched=False, userprofile={'privacy_full_name': PUBLIC})
        voucher = UserFactory.create(vouched=False)
        url = reverse('phonebook:profile_view', args=[user.username], prefix='/en-US/')
        data = {'vouchee': user.userprofile.id,
                'description': 'a reason'}
        with self.login(voucher) as client:
            client.post(url, data)
        unvouched_user = User.objects.get(id=user.id)
        ok_(not unvouched_user.userprofile.is_vouched)

    def test_vouch_no_description(self):
        user = UserFactory.create(vouched=False)
        voucher = UserFactory.create()
        url = reverse('phonebook:profile_view', args=[user.username], prefix='/en-US/')
        data = {'vouchee': user.userprofile.id,
                'description': ''}
        with self.login(voucher) as client:
            client.post(url, data)
        unvouched_user = User.objects.get(id=user.id)
        ok_(not unvouched_user.userprofile.is_vouched)

    @override_settings(CAN_VOUCH_THRESHOLD=1)
    @patch('mozillians.phonebook.views.messages.info')
    def test_vouch_unvouched(self, info_mock):
        user = UserFactory.create(vouched=False)
        user.userprofile.vouch(None)
        unvouched_user = UserFactory.create(vouched=False)
        url = reverse('phonebook:profile_view', args=[unvouched_user.username], prefix='/en-US/')
        data = {'vouchee': unvouched_user.userprofile.id,
                'description': 'a reason'}
        with self.login(user) as client:
            response = client.post(url, data, follow=True)
        unvouched_user = User.objects.get(id=unvouched_user.id)
        self.assertTemplateUsed(response, 'phonebook/profile.html')
        eq_(response.context['profile'], unvouched_user.userprofile)
        ok_(unvouched_user.userprofile.is_vouched)
        ok_(info_mock.called)
        self.assertRedirects(response, url)


class LogoutTests(TestCase):
    @requires_login()
    def test_logout_anonymous(self):
        client = Client()
        client.get(reverse('phonebook:logout'), follow=True)

    @patch('mozillians.phonebook.views.auth_logout', wraps=logout_view)
    def test_logout_unvouched(self, logout_mock):
        user = UserFactory.create(vouched=False)
        with self.login(user) as client:
            response = client.get(reverse('phonebook:logout'), follow=True)
        eq_(response.status_code, 200)
        self.assertTemplateUsed(response, 'phonebook/home.html')
        ok_(logout_mock.called)

    @patch('mozillians.phonebook.views.auth_logout', wraps=logout_view)
    def test_logout_vouched(self, logout_mock):
        user = UserFactory.create()
        with self.login(user) as client:
            response = client.get(reverse('phonebook:logout'), follow=True)
        eq_(response.status_code, 200)
        self.assertTemplateUsed(response, 'phonebook/home.html')
        ok_(logout_mock.called)


class EmailChangeTests(TestCase):
    @patch('mozillians.phonebook.views.forms.ProfileForm')
    def test_email_change_verification_redirection(self, profile_form_mock):
        profile_form_mock().is_valid.return_value = True
        user = UserFactory.create(email='old@example.com')
        data = {'full_name': 'foobar',
                'email': 'new@example.com',
                'username': user.username,
                'externalaccount_set-MAX_NUM_FORMS': '1000',
                'externalaccount_set-INITIAL_FORMS': '0',
                'externalaccount_set-TOTAL_FORMS': '0',
                'language_set-MAX_NUM_FORMS': '1000',
                'language_set-INITIAL_FORMS': '0',
                'language_set-TOTAL_FORMS': '0',
            }
        url = reverse('phonebook:profile_edit', prefix='/en-US/')
        with self.login(user) as client:
            response = client.post(url, data=data, follow=True)
        self.assertTemplateUsed(response, 'phonebook/verify_email.html')
        eq_(user.email, 'old@example.com')


class ImageTests(TestCase):
    def _upload_photo(self, user, file_path):
        """Helper for the next methods."""
        data = {'full_name': user.userprofile.full_name,
                'email': user.email,
                'username': user.username,
                'lat': 40.005814,
                'lng': -3.42071,
                'photo': open(file_path, 'rb'),
                'externalaccount_set-MAX_NUM_FORMS': '1000',
                'externalaccount_set-INITIAL_FORMS': '0',
                'externalaccount_set-TOTAL_FORMS': '0',
                'language_set-MAX_NUM_FORMS': '1000',
                'language_set-INITIAL_FORMS': '0',
                'language_set-TOTAL_FORMS': '0',
            }
        data.update(_get_privacy_fields(MOZILLIANS))
        url = reverse('phonebook:profile_edit', prefix='/en-US/')
        with self.login(user) as client:
            response = client.post(url, data=data, follow=True)
        eq_(response.status_code, 200)

    def test_exif_broken(self):
        """Test image with broken EXIF data."""
        user = UserFactory.create()
        file_path = os.path.join(os.path.dirname(__file__), 'broken_exif.jpg')
        self._upload_photo(user, file_path)

    def test_no_rgb_colorspace(self):
        """Test with image not in RGB colorspace.

        Related bug 928959.
        """
        user = UserFactory.create()
        file_path = os.path.join(os.path.dirname(__file__),
                                 'broken_colorspace.gif')
        self._upload_photo(user, file_path)

    def test_converted_larger_image(self):
        """Test image which gets cleaned in forms.py.

        Bug 921243 was caused of a valid image, without EXIF
        data. That caused image._get_exif() in
        phonebook.forms.ProfileForm.clean_photo to raise an
        AttributeError and clean the image.

        Cleaning the image (by re-saving) did not set the new file
        size in the `photo` variable. If the cleaned image was larger
        than the original image, this behavior resulted in corrupted
        images being fed into PIL, which raises IOErrors.

        This test reproduces that behavior and should fail if we don't
        update the size of `photo` with the new cleaned image size.
        """
        user = UserFactory.create()
        file_path = os.path.join(os.path.dirname(__file__), 'broken_marshal.jpg')
        self._upload_photo(user, file_path)

    def test_save_profile_with_existing_photo(self):
        """Test profiles saves when keep the existing photo.

        Related bug 925256.
        """
        # Set a user with a photo
        user = UserFactory.create()
        file_path = os.path.join(os.path.dirname(__file__), 'normal_photo.jpg')
        self._upload_photo(user, file_path)

        # Re-save profile without uploading a new photo.
        data = {'full_name': user.userprofile.full_name,
                'email': user.email,
                'username': user.username,
                'lat': 40.005814,
                'lng': -3.42071,
                'externalaccount_set-MAX_NUM_FORMS': '1000',
                'externalaccount_set-INITIAL_FORMS': '0',
                'externalaccount_set-TOTAL_FORMS': '0',
                'language_set-MAX_NUM_FORMS': '1000',
                'language_set-INITIAL_FORMS': '0',
                'language_set-TOTAL_FORMS': '0',
            }

        for field in UserProfilePrivacyModel._meta._fields():
            data[field.name] = MOZILLIANS
        data['privacy_tshirt'] = PRIVILEGED

        url = reverse('phonebook:profile_edit', prefix='/en-US/')
        with self.login(user) as client:
            response = client.post(url, data=data, follow=True)
        eq_(response.status_code, 200)


class DateValidationTests(TestCase):
    def test_date_mozillian_validates_in_different_locales(self):
        """Tests if date_mozillian validates when profile language is e.g. 'es'.

        Related bug 914448.
        """
        user = UserFactory.create(email='es@example.com')
        data = {'full_name': user.userprofile.full_name,
                'email': user.email,
                'username': user.username,
                'lat': 40.005814,
                'lng': -3.42071,
                'date_mozillian_year': '2013',
                'date_mozillian_month': '1',
                'externalaccount_set-MAX_NUM_FORMS': '1000',
                'externalaccount_set-INITIAL_FORMS': '0',
                'externalaccount_set-TOTAL_FORMS': '0',
                'language_set-MAX_NUM_FORMS': '1000',
                'language_set-INITIAL_FORMS': '0',
                'language_set-TOTAL_FORMS': '0',
            }
        data.update(_get_privacy_fields(MOZILLIANS))

        url = reverse('phonebook:profile_edit', prefix='/es/')
        with self.login(user) as client:
            response = client.post(url, data=data, follow=True)
        eq_(response.status_code, 200)


class AboutTests(TestCase):
    def test_base(self):
        url = reverse('phonebook:about')
        client = Client()
        response = client.get(url, follow=True)
        eq_(response.status_code, 200)
        self.assertTemplateUsed('phonebook/about.html')


class AboutDinoMcVouchTests(TestCase):
    def test_base(self):
        url = reverse('phonebook:about-dinomcvouch')
        client = Client()
        response = client.get(url, follow=True)
        eq_(response.status_code, 200)
        self.assertTemplateUsed('phonebook/about-dinomcvouch.html')


class VouchTests(TestCase):
    def test_vouch_disabled(self):
        # Test that 'vouched' view is not active by default.
        user = UserFactory.create(vouched=False)
        url = reverse('phonebook:profile_vouch', args=[user.username])
        with self.login(user) as client:
            response = client.get(url, follow=True)
        eq_(response.status_code, 404)
        user = User.objects.get(id=user.id)
        ok_(not user.userprofile.is_vouched)

    def test_unvouch_disabled(self):
        # Test that 'unvouched' view is not active by default.
        user = UserFactory.create(vouched=False)
        url = reverse('phonebook:profile_unvouch', args=[user.username])
        with self.login(user) as client:
            response = client.get(url, follow=True)
        eq_(response.status_code, 404)
        user = User.objects.get(id=user.id)
        ok_(not user.userprofile.is_vouched)

    def test_vouch(self):
        Flag.objects.create(name='testing-autovouch-views', everyone=True)
        user = UserFactory.create(vouched=False)
        ok_(not user.userprofile.is_vouched)
        url = reverse('phonebook:profile_vouch', args=[user.username])
        with self.login(user) as client:
            client.get(url, follow=True)
        user = User.objects.get(id=user.id)
        eq_(user.userprofile.vouches_received.all().count(), 1)
        eq_(user.userprofile.vouches_received.all()[0].autovouch, True)

    def test_unvouch(self):
        Flag.objects.create(name='testing-autovouch-views', everyone=True)
        user = UserFactory.create()
        ok_(user.userprofile.is_vouched)
        url = reverse('phonebook:profile_unvouch', args=[user.username])
        with self.login(user) as client:
            client.get(url, follow=True)
        user = User.objects.get(id=user.id)
        ok_(not user.userprofile.vouches_received.all().exists())
