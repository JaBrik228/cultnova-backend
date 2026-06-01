from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reviews.admin import HomeReviewAdminForm
from reviews.models import HomeReview


class HomeReviewSeedDataTests(TestCase):
    def test_seed_reviews_are_available_after_migrations(self):
        reviews = list(HomeReview.objects.order_by("sort_order", "created_at", "pk"))

        self.assertEqual(len(reviews), 4)
        self.assertEqual(
            [review.name for review in reviews],
            [
                "Виталий Нагалин",
                "Каменская Наталия Николаевна",
                "Екатерина Попович",
                "Каширцева Надежда Александровна",
            ],
        )
        self.assertTrue(all(review.is_published for review in reviews))
        self.assertTrue(
            all(review.image_url.startswith("https://cultnova.ru/images/reviews/") for review in reviews)
        )


class HomeReviewModelTests(TestCase):
    def setUp(self):
        HomeReview.objects.all().delete()

    def test_full_clean_rejects_missing_and_invalid_public_fields(self):
        review = HomeReview(
            name="",
            position="",
            text="",
            image_url="ftp://example.com/review.jpg",
            image_alt="",
            is_published=True,
        )

        with self.assertRaises(ValidationError) as exc:
            review.full_clean()

        self.assertIn("name", exc.exception.message_dict)
        self.assertIn("position", exc.exception.message_dict)
        self.assertIn("text", exc.exception.message_dict)
        self.assertIn("image_url", exc.exception.message_dict)
        self.assertIn("image_alt", exc.exception.message_dict)


class HomeReviewAdminFormTests(TestCase):
    def setUp(self):
        HomeReview.objects.all().delete()

    def test_form_trims_fields_and_accepts_manual_image_url(self):
        form = HomeReviewAdminForm(
            data={
                "name": "  Jane Doe  ",
                "position": "  Museum Director  ",
                "text": "  Excellent work.  ",
                "image_url": " https://example.com/review.jpg ",
                "image_alt": "  Jane portrait  ",
                "sort_order": "4",
                "is_published": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        review = form.save()

        self.assertEqual(review.name, "Jane Doe")
        self.assertEqual(review.position, "Museum Director")
        self.assertEqual(review.text, "Excellent work.")
        self.assertEqual(review.image_url, "https://example.com/review.jpg")
        self.assertEqual(review.image_alt, "Jane portrait")
        self.assertEqual(review.sort_order, 4)
        self.assertTrue(review.is_published)

    @patch("reviews.admin.upload_media_to_vk_cloud", return_value="https://example.com/uploaded-review.jpg")
    def test_form_uploads_image_and_sets_url(self, mocked_upload):
        image_file = SimpleUploadedFile("review.jpg", b"fake-image-bytes", content_type="image/jpeg")
        form = HomeReviewAdminForm(
            data={
                "name": "Upload Review",
                "position": "Curator",
                "text": "Uploaded image review",
                "image_url": "",
                "image_alt": "Uploaded portrait",
                "sort_order": "1",
                "is_published": "on",
            },
            files={"upload_image": image_file},
        )

        self.assertTrue(form.is_valid(), form.errors)
        review = form.save()

        mocked_upload.assert_called_once()
        self.assertEqual(review.image_url, "https://example.com/uploaded-review.jpg")

    def test_form_rejects_missing_image_source(self):
        form = HomeReviewAdminForm(
            data={
                "name": "No image",
                "position": "Curator",
                "text": "Review text",
                "image_url": "",
                "image_alt": "",
                "sort_order": "1",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image_url", form.errors)


class HomeReviewsApiTests(TestCase):
    def setUp(self):
        HomeReview.objects.all().delete()
        self.first = HomeReview.objects.create(
            name="Alpha",
            position="First",
            text="Alpha review",
            image_url="https://example.com/alpha.jpg",
            image_alt="Alpha alt",
            sort_order=1,
            is_published=True,
        )
        self.second = HomeReview.objects.create(
            name="Beta",
            position="Second",
            text="Beta review",
            image_url="https://example.com/beta.jpg",
            image_alt="Beta alt",
            sort_order=1,
            is_published=True,
        )
        self.hidden = HomeReview.objects.create(
            name="Hidden",
            position="Hidden",
            text="Hidden review",
            image_url="https://example.com/hidden.jpg",
            image_alt="Hidden alt",
            sort_order=0,
            is_published=False,
        )

        now = timezone.now()
        HomeReview.objects.filter(pk=self.first.pk).update(created_at=now - timedelta(minutes=2))
        HomeReview.objects.filter(pk=self.second.pk).update(created_at=now - timedelta(minutes=1))

    def test_feed_returns_only_published_reviews_in_order(self):
        response = self.client.get(reverse("reviews:home_feed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "data": [
                    {
                        "id": self.first.pk,
                        "name": "Alpha",
                        "position": "First",
                        "text": "Alpha review",
                        "image_url": "https://example.com/alpha.jpg",
                        "image_alt": "Alpha alt",
                    },
                    {
                        "id": self.second.pk,
                        "name": "Beta",
                        "position": "Second",
                        "text": "Beta review",
                        "image_url": "https://example.com/beta.jpg",
                        "image_alt": "Beta alt",
                    },
                ]
            },
        )

    def test_feed_returns_empty_list_when_nothing_is_published(self):
        HomeReview.objects.all().update(is_published=False)

        response = self.client.get(reverse("reviews:home_feed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"data": []})


class HomeReviewAdminTests(TestCase):
    def setUp(self):
        HomeReview.objects.all().delete()
        self.user = get_user_model().objects.create_superuser(
            username="review-admin",
            email="review-admin@example.com",
            password="password123",
        )
        self.add_url = reverse("admin:reviews_homereview_add")

    def test_admin_can_create_edit_publish_and_sort_review(self):
        self.client.force_login(self.user)

        create_response = self.client.post(
            self.add_url,
            data={
                "name": "  Admin review  ",
                "position": "  Director  ",
                "text": "  Great result.  ",
                "image_url": " https://example.com/admin-review.jpg ",
                "image_alt": "  Admin alt  ",
                "sort_order": "10",
                "_save": "Save",
            },
        )

        self.assertEqual(create_response.status_code, 302)

        review = HomeReview.objects.get()
        self.assertEqual(review.name, "Admin review")
        self.assertEqual(review.position, "Director")
        self.assertEqual(review.text, "Great result.")
        self.assertEqual(review.image_url, "https://example.com/admin-review.jpg")
        self.assertEqual(review.image_alt, "Admin alt")
        self.assertEqual(review.sort_order, 10)
        self.assertFalse(review.is_published)

        change_url = reverse("admin:reviews_homereview_change", args=[review.pk])
        change_response = self.client.post(
            change_url,
            data={
                "name": "Admin review updated",
                "position": "Head curator",
                "text": "Updated review",
                "image_url": "https://example.com/admin-review-2.jpg",
                "image_alt": "Updated alt",
                "sort_order": "1",
                "is_published": "on",
                "_save": "Save",
            },
        )

        self.assertEqual(change_response.status_code, 302)

        review.refresh_from_db()
        self.assertEqual(review.name, "Admin review updated")
        self.assertEqual(review.position, "Head curator")
        self.assertEqual(review.text, "Updated review")
        self.assertEqual(review.image_url, "https://example.com/admin-review-2.jpg")
        self.assertEqual(review.image_alt, "Updated alt")
        self.assertEqual(review.sort_order, 1)
        self.assertTrue(review.is_published)

