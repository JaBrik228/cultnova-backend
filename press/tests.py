from datetime import timedelta

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from press.admin import PressItemAdminForm
from press.models import PressItem


class PressItemModelTests(TestCase):
    def test_full_clean_rejects_invalid_and_missing_public_fields(self):
        item = PressItem(
            title="",
            description="",
            url="ftp://example.com/article",
            sort_order=0,
            is_published=True,
        )

        with self.assertRaises(ValidationError) as exc:
            item.full_clean()

        self.assertIn("title", exc.exception.message_dict)
        self.assertIn("description", exc.exception.message_dict)
        self.assertIn("url", exc.exception.message_dict)


class PressItemAdminFormTests(TestCase):
    def test_form_trims_fields_and_accepts_http_urls(self):
        form = PressItemAdminForm(
            data={
                "title": "  СМИ о проекте  ",
                "description": "  Короткое описание публикации  ",
                "url": " https://example.com/article ",
                "sort_order": "3",
                "is_published": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()

        self.assertEqual(item.title, "СМИ о проекте")
        self.assertEqual(item.description, "Короткое описание публикации")
        self.assertEqual(item.url, "https://example.com/article")
        self.assertEqual(item.sort_order, 3)
        self.assertTrue(item.is_published)

    def test_form_rejects_non_http_urls(self):
        form = PressItemAdminForm(
            data={
                "title": "СМИ о проекте",
                "description": "Короткое описание публикации",
                "url": "ftp://example.com/article",
                "sort_order": "3",
                "is_published": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)


class PressFeedApiTests(TestCase):
    def setUp(self):
        self.first = PressItem.objects.create(
            title="Alpha",
            description="Alpha description",
            url="https://example.com/alpha",
            sort_order=1,
            is_published=True,
        )
        self.second = PressItem.objects.create(
            title="Beta",
            description="Beta description",
            url="https://example.com/beta",
            sort_order=1,
            is_published=True,
        )
        self.third = PressItem.objects.create(
            title="Gamma",
            description="Gamma description",
            url="https://example.com/gamma",
            sort_order=0,
            is_published=True,
        )
        self.hidden = PressItem.objects.create(
            title="Hidden",
            description="Hidden description",
            url="https://example.com/hidden",
            sort_order=2,
            is_published=False,
        )

        now = timezone.now()
        PressItem.objects.filter(pk=self.first.pk).update(created_at=now - timedelta(minutes=2))
        PressItem.objects.filter(pk=self.second.pk).update(created_at=now - timedelta(minutes=1))
        PressItem.objects.filter(pk=self.third.pk).update(created_at=now - timedelta(minutes=3))

    def test_feed_returns_only_published_items_in_order(self):
        response = self.client.get(reverse("press:feed"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["data"],
            [
                {
                    "title": "Gamma",
                    "description": "Gamma description",
                    "url": "https://example.com/gamma",
                },
                {
                    "title": "Alpha",
                    "description": "Alpha description",
                    "url": "https://example.com/alpha",
                },
                {
                    "title": "Beta",
                    "description": "Beta description",
                    "url": "https://example.com/beta",
                },
            ],
        )
        self.assertNotIn(self.hidden.title, str(payload["data"]))

    def test_feed_returns_empty_list_when_nothing_is_published(self):
        PressItem.objects.all().update(is_published=False)

        response = self.client.get(reverse("press:feed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"data": []})


class PressAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="press-admin",
            email="press-admin@example.com",
            password="password123",
        )
        self.add_url = reverse("admin:press_pressitem_add")

    def test_admin_can_create_edit_publish_and_sort_item(self):
        self.client.force_login(self.user)

        create_response = self.client.post(
            self.add_url,
            data={
                "title": "  СМИ о Cultnova  ",
                "description": "  Публикация о проекте  ",
                "url": " https://example.com/media-story ",
                "sort_order": "10",
                "_save": "Save",
            },
        )

        self.assertEqual(create_response.status_code, 302)

        item = PressItem.objects.get()
        self.assertEqual(item.title, "СМИ о Cultnova")
        self.assertEqual(item.description, "Публикация о проекте")
        self.assertEqual(item.url, "https://example.com/media-story")
        self.assertEqual(item.sort_order, 10)
        self.assertFalse(item.is_published)

        change_url = reverse("admin:press_pressitem_change", args=[item.pk])
        change_response = self.client.post(
            change_url,
            data={
                "title": "СМИ о Cultnova updated",
                "description": "Обновленное описание",
                "url": "https://example.com/updated-story",
                "sort_order": "1",
                "is_published": "on",
                "_save": "Save",
            },
        )

        self.assertEqual(change_response.status_code, 302)

        item.refresh_from_db()
        self.assertEqual(item.title, "СМИ о Cultnova updated")
        self.assertEqual(item.description, "Обновленное описание")
        self.assertEqual(item.url, "https://example.com/updated-story")
        self.assertEqual(item.sort_order, 1)
        self.assertTrue(item.is_published)
