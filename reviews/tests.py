from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import Resolver404, resolve, reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Restaurant, Review
from .views import list_all_reviews, list_my_reviews, submit_review


class ReviewURLTests(SimpleTestCase):
    def test_review_urls_reverse_to_exact_paths(self):
        cases = (
            ('my-reviews', {}, '/api/me/reviews/'),
            (
                'list-all-reviews', {'restaurant_id': 42},
                '/api/restaurants/42/reviews/all/',
            ),
            (
                'submit-review', {'restaurant_id': 42},
                '/api/restaurants/42/submit-review/',
            ),
        )
        for name, kwargs, expected_path in cases:
            with self.subTest(name=name):
                self.assertEqual(reverse(name, kwargs=kwargs), expected_path)

    def test_review_urls_resolve_to_expected_callbacks(self):
        cases = (
            ('/api/me/reviews/', 'my-reviews', list_my_reviews, {}),
            (
                '/api/restaurants/42/reviews/all/', 'list-all-reviews',
                list_all_reviews, {'restaurant_id': 42},
            ),
            (
                '/api/restaurants/42/submit-review/', 'submit-review',
                submit_review, {'restaurant_id': 42},
            ),
        )
        for path, name, callback, kwargs in cases:
            with self.subTest(path=path):
                match = resolve(path)
                self.assertIs(match.func, callback)
                self.assertEqual(match.url_name, name)
                self.assertEqual(match.kwargs, kwargs)
                self.assertEqual(match.func.__module__, 'reviews.views')

    def test_legacy_review_urls_do_not_resolve(self):
        legacy = 'rat' + 'ing'
        paths = (
            f'/api/me/{legacy}s/',
            f'/api/restaurants/42/{legacy}s/all/',
            f'/api/restaurants/42/submit-{legacy}/',
        )
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)


class ReviewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='tester',
            password='test-only-password',
        )
        for restaurant_id in (42, 43, 99):
            Restaurant.objects.create(
                id=restaurant_id, name=f'Place {restaurant_id}',
                country='United Kingdom', city='London',
            )

    def setUp(self):
        self.assertTrue(
            self.client.login(username='tester', password='test-only-password')
        )
        self.url = reverse('submit-review', kwargs={'restaurant_id': 42})
        self.scores = {
            'food': 18,
            'drink': 15,
            'service': 17,
            'vibes': 19,
            'value': 16,
        }

    def test_login_defaults_to_my_reviews(self):
        self.client.logout()

        response = self.client.post(
            reverse('rest_framework:login'),
            {'username': 'tester', 'password': 'test-only-password'},
        )

        self.assertRedirects(response, reverse('my-reviews'))

    def test_login_preserves_explicit_next_destination(self):
        self.client.logout()

        response = self.client.post(
            reverse('rest_framework:login'),
            {
                'username': 'tester',
                'password': 'test-only-password',
                'next': self.url,
            },
        )

        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_total_is_sum_out_of_100(self):
        response = self.client.post(self.url, self.scores, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['restaurant_id'], 42)
        self.assertEqual(response.data['scores'], self.scores)
        self.assertEqual(response.data['your_total'], 85)
        review = Review.objects.get(user=self.user, restaurant_id=42)
        for category, score in self.scores.items():
            self.assertEqual(getattr(review, category), score)

    def test_reposting_updates_existing_review(self):
        self.client.post(self.url, self.scores, format='json')
        original_review = Review.objects.get()
        scores = {**self.scores, 'food': 20}

        response = self.client.post(self.url, scores, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['your_total'], 87)
        self.assertEqual(Review.objects.count(), 1)
        original_review.refresh_from_db()
        self.assertEqual(original_review.food, 20)
        self.assertEqual(original_review.drink, self.scores['drink'])
        listed = self.client.get(reverse('my-reviews'))
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(
            listed.data,
            [{'restaurant_id': 42, 'scores': scores, 'your_total': 87}],
        )

    def test_list_returns_all_and_only_current_users_reviews(self):
        other_user = get_user_model().objects.create_user(username='other')
        Review.objects.create(user=other_user, restaurant_id=99, **self.scores)
        Review.objects.create(user=self.user, restaurant_id=43, **self.scores)
        scores = {**self.scores, 'food': 20}
        Review.objects.create(user=self.user, restaurant_id=42, **scores)

        response = self.client.get(
            reverse('my-reviews'), {'user_id': other_user.pk}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            [
                {'restaurant_id': 42, 'scores': scores, 'your_total': 87},
                {'restaurant_id': 43, 'scores': self.scores, 'your_total': 85},
            ],
        )

    def test_list_returns_empty_array_when_user_has_no_reviews(self):
        other_user = get_user_model().objects.create_user(username='other')
        Review.objects.create(user=other_user, restaurant_id=42, **self.scores)

        response = self.client.get(reverse('my-reviews'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_anonymous_users_cannot_list_reviews(self):
        Review.objects.create(user=self.user, restaurant_id=42, **self.scores)
        self.client.logout()

        response = self.client.get(reverse('my-reviews'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn('scores', response.data)

    def test_different_users_have_separate_reviews(self):
        self.client.post(self.url, self.scores, format='json')
        other_user = get_user_model().objects.create_user(username='other')
        self.client.force_authenticate(user=other_user)

        response = self.client.post(
            self.url,
            {**self.scores, 'food': 10, 'user_id': self.user.pk},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Review.objects.count(), 2)
        self.assertEqual(
            Review.objects.get(user=self.user, restaurant_id=42).food, 18
        )
        self.assertEqual(
            Review.objects.get(user=other_user, restaurant_id=42).food, 10
        )

    def test_different_restaurants_have_separate_reviews(self):
        self.client.post(self.url, self.scores, format='json')
        other_url = reverse('submit-review', kwargs={'restaurant_id': 43})

        response = self.client.post(other_url, self.scores, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(
                Review.objects.filter(user=self.user).values_list(
                    'restaurant_id', flat=True
                )
            ),
            {42, 43},
        )

    def test_invalid_update_preserves_existing_review(self):
        self.client.post(self.url, self.scores, format='json')

        response = self.client.post(
            self.url, {**self.scores, 'food': 21}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().food, 18)

    def test_database_enforces_unique_user_restaurant_review(self):
        Review.objects.create(user=self.user, restaurant_id=42, **self.scores)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(user=self.user, restaurant_id=42, **self.scores)

    def test_database_enforces_category_bounds(self):
        for category in self.scores:
            for score in (0, 21):
                with self.subTest(category=category, score=score):
                    scores = {**self.scores, category: score}
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        Review.objects.create(
                            user=self.user, restaurant_id=42, **scores
                        )

    def test_category_endpoints_are_accepted(self):
        for score, expected_total in ((1, 5), (20, 100)):
            with self.subTest(score=score):
                scores = dict.fromkeys(self.scores, score)
                response = self.client.post(self.url, scores, format='json')

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data['your_total'], expected_total)

    def test_invalid_category_scores_are_rejected(self):
        for category in self.scores:
            for score in (0, 21, 1.5, 'invalid', None):
                with self.subTest(category=category, score=score):
                    scores = {**self.scores, category: score}
                    response = self.client.post(self.url, scores, format='json')

                    self.assertEqual(
                        response.status_code, status.HTTP_400_BAD_REQUEST
                    )
                    self.assertIn(category, response.data)
                    self.assertFalse(Review.objects.exists())

    def test_all_categories_are_required(self):
        for category in self.scores:
            with self.subTest(category=category):
                scores = self.scores.copy()
                del scores[category]
                response = self.client.post(self.url, scores, format='json')

                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )
                self.assertIn(category, response.data)
                self.assertFalse(Review.objects.exists())

    def test_anonymous_requests_are_rejected(self):
        self.client.logout()
        response = self.client.post(self.url, self.scores, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Review.objects.exists())

    def test_get_is_not_supported(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_unknown_restaurant_ids_reject_saves_and_lookups_without_changes(self):
        self.client.post(self.url, self.scores, format='json')
        for restaurant_id in (0, 123456, 2**63 - 1, 2**63, 10**100):
            with self.subTest(restaurant_id=restaurant_id):
                url = reverse('submit-review', kwargs={'restaurant_id': restaurant_id})
                response = self.client.post(url, self.scores, format='json')
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data, {'detail': 'Restaurant not found.'})
                self.assertEqual(Review.objects.count(), 1)
                self.assertEqual(Review.objects.get().food, 18)
                self.assertEqual(Restaurant.objects.count(), 3)
                lookup = self.client.get(reverse(
                    'list-all-reviews', kwargs={'restaurant_id': restaurant_id},
                ))
                self.assertEqual(lookup.status_code, 404)
                self.assertEqual(lookup.data, {'detail': 'Restaurant not found.'})

    def test_restaurant_existence_is_checked_before_score_validation(self):
        response = self.client.post(
            reverse('submit-review', kwargs={'restaurant_id': 123456}),
            {}, format='json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Review.objects.exists())

    def test_existing_restaurant_without_reviews_returns_empty_array(self):
        response = self.client.get(reverse(
            'list-all-reviews', kwargs={'restaurant_id': 42},
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_database_rejects_review_for_missing_restaurant(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(user=self.user, restaurant_id=123456, **self.scores)
            # SQLite foreign keys are deferred until commit; enforce them here.
            connection.check_constraints(table_names=[Review._meta.db_table])
        self.assertFalse(Review.objects.exists())

    def test_restaurant_with_reviews_is_protected_from_deletion(self):
        review = Review.objects.create(user=self.user, restaurant_id=42, **self.scores)
        with self.assertRaises(ProtectedError):
            review.restaurant.delete()
        self.assertTrue(Restaurant.objects.filter(pk=42).exists())
        self.assertEqual(Review.objects.count(), 1)


class RestaurantTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='restaurant-tester', password='test-only-password',
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)
        self.url = reverse('add-restaurant')
        self.details = {'name': 'Cafe', 'country': 'United Kingdom', 'city': 'London'}

    def test_regular_user_can_create_restaurant_with_trimmed_name(self):
        self.assertFalse(self.user.is_staff)
        response = self.client.post(self.url, {
            'name': '  The Green Table  ', 'country': '  United Kingdom  ',
            'city': '  London  ',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        restaurant = Restaurant.objects.get()
        self.assertEqual(response.data, {
            'id': restaurant.pk, 'name': 'The Green Table',
            'country': 'United Kingdom', 'city': 'London',
        })
        self.assertEqual(restaurant.name, 'The Green Table')
        self.assertEqual(restaurant.country, 'United Kingdom')
        self.assertEqual(restaurant.city, 'London')
        self.assertEqual(str(restaurant), 'The Green Table')
        self.assertGreater(restaurant.pk, 0)
        self.assertFalse(Review.objects.exists())

    def test_ids_are_generated_and_duplicate_names_are_allowed(self):
        first = self.client.post(self.url, {**self.details, 'id': 123456}, format='json')
        second = self.client.post(self.url, self.details, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data['id'], 123456)
        self.assertNotEqual(first.data['id'], second.data['id'])
        self.assertEqual(Restaurant.objects.filter(name='Cafe').count(), 2)

    def test_invalid_names_do_not_create_restaurants(self):
        for payload in ({}, {'name': ''}, {'name': ' \t\n '}, {'name': None},
                        {'name': 'x' * 201}, {'name': []}, {'name': {}}, {'name': True}):
            with self.subTest(payload=payload):
                response = self.client.post(self.url, {
                    'country': 'United Kingdom', 'city': 'London', **payload,
                }, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('name', response.data)
                self.assertFalse(Restaurant.objects.exists())

    def test_maximum_length_name_is_accepted(self):
        response = self.client.post(self.url, {**self.details, 'name': 'x' * 200}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(Restaurant.objects.get().name), 200)

    def test_anonymous_creation_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, self.details, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Restaurant.objects.exists())

    def test_only_post_is_supported(self):
        for method in ('get', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url)
                self.assertEqual(response.status_code, 405)
                self.assertFalse(Restaurant.objects.exists())

    def test_created_restaurant_can_be_reviewed_and_updated(self):
        created = self.client.post(self.url, self.details, format='json')
        url = reverse('submit-review', kwargs={'restaurant_id': created.data['id']})
        scores = dict.fromkeys(('food', 'drink', 'service', 'vibes', 'value'), 15)
        first = self.client.post(url, scores, format='json')
        self.assertEqual(first.status_code, 200)
        updated = self.client.post(url, {**scores, 'food': 20}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data['your_total'], 80)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().restaurant_id, created.data['id'])

    def test_country_and_city_are_required(self):
        for field in ('country', 'city'):
            with self.subTest(field=field):
                payload = self.details.copy()
                del payload[field]
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
                self.assertFalse(Restaurant.objects.exists())

    def test_invalid_locations_do_not_create_restaurants(self):
        for field in ('country', 'city'):
            for value in ('', ' \t\n ', None, 'x' * 101, [], {}, True):
                with self.subTest(field=field, value=value):
                    response = self.client.post(
                        self.url, {**self.details, field: value}, format='json',
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
                    self.assertFalse(Restaurant.objects.exists())

    def test_maximum_length_and_unicode_locations_are_accepted(self):
        for country, city in (('x' * 100, 'y' * 100), ('日本', '東京')):
            with self.subTest(country=country, city=city):
                response = self.client.post(
                    self.url, {**self.details, 'country': country, 'city': city},
                    format='json',
                )
                self.assertEqual(response.status_code, 201)
                restaurant = Restaurant.objects.get(pk=response.data['id'])
                self.assertEqual(restaurant.country, country)
                self.assertEqual(restaurant.city, city)


class GetRestaurantsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='explorer-tester')
        other = get_user_model().objects.create_user(username='community-reviewer')
        cls.reviewed = Restaurant.objects.create(
            name='The Green Table', country='United Kingdom', city='London',
        )
        cls.unreviewed = Restaurant.objects.create(
            name='An Untried Place', country='United Kingdom', city='York',
        )
        cls.overseas = Restaurant.objects.create(
            name='Another Table', country='Canada', city='London',
        )
        categories = ('food', 'drink', 'service', 'vibes', 'value')
        Review.objects.create(
            user=cls.user, restaurant=cls.reviewed, **dict.fromkeys(categories, 18),
        )
        Review.objects.create(
            user=other, restaurant=cls.reviewed, **dict.fromkeys(categories, 16),
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)
        self.url = reverse('get-restaurants')

    def test_returns_restaurant_details_and_community_averages(self):
        response = self.client.get(self.url)

        self.assertEqual(self.url, '/api/restaurants/get/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)
        reviewed = next(row for row in response.data if row['id'] == self.reviewed.pk)
        self.assertEqual(reviewed, {
            'id': self.reviewed.pk,
            'name': 'The Green Table',
            'city': 'London',
            'country': 'United Kingdom',
            'total_reviews': 2,
            'average_score': {
                'food_avg': 17.0, 'drink_avg': 17.0, 'service_avg': 17.0,
                'vibes_avg': 17.0, 'value_avg': 17.0,
            },
            'total_average': 85.0,
            'koalas': 2,
        })

    def test_restaurants_without_reviews_have_null_category_averages(self):
        response = self.client.get(self.url, {'city': 'York'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        restaurant = response.data[0]
        self.assertEqual(restaurant['id'], self.unreviewed.pk)
        self.assertEqual(restaurant['total_reviews'], 0)
        self.assertEqual(restaurant['total_average'], 0)
        self.assertEqual(restaurant['koalas'], 0)
        self.assertEqual(restaurant['average_score'], {
            'food_avg': None, 'drink_avg': None, 'service_avg': None,
            'vibes_avg': None, 'value_avg': None,
        })

    def test_location_filters_apply_individually_and_together(self):
        cases = (
            ({'city': 'London'}, {self.reviewed.pk, self.overseas.pk}),
            ({'country': 'United Kingdom'}, {self.reviewed.pk, self.unreviewed.pk}),
            ({'city': 'London', 'country': 'Canada'}, {self.overseas.pk}),
            ({'city': 'York', 'country': 'Canada'}, set()),
        )
        for filters, expected_ids in cases:
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual({row['id'] for row in response.data}, expected_ids)

    def test_count_limits_filtered_results_and_accepts_zero(self):
        for count in (0, 1, 10):
            with self.subTest(count=count):
                response = self.client.get(self.url, {
                    'country': 'United Kingdom', 'count': count,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.data), min(count, 2))
                self.assertTrue(all(row['country'] == 'United Kingdom' for row in response.data))

    def test_anonymous_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_post_is_not_supported_and_does_not_change_data(self):
        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Restaurant.objects.count(), 3)
        self.assertEqual(Review.objects.count(), 2)


class FrontendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='frontend-tester',
            password='test-only-password',
        )
        for restaurant_id in (42, 99):
            Restaurant.objects.create(
                id=restaurant_id, name=f'Place {restaurant_id}',
                country='United Kingdom', city='London',
            )
        cls.scores = {
            'food': 18,
            'drink': 15,
            'service': 17,
            'vibes': 19,
            'value': 16,
        }

    def test_home_is_public_and_renders_frontend_assets(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reviews/home.html')
        self.assertContains(response, '/static/reviews/app.css')
        self.assertContains(response, '/static/reviews/app.js')
        self.assertContains(response, 'data-authenticated="false"')
        self.assertContains(response, 'Sign in to see the places')
        self.assertContains(response, '<fieldset disabled>', count=3)
        self.assertContains(response, 'id="add-restaurant-form"')

    def test_home_wires_existing_api_endpoints_and_all_categories(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'data-authenticated="true"')
        self.assertContains(response, f'data-my-reviews-url="{reverse("my-reviews")}"')
        self.assertContains(response, f'data-add-restaurant-url="{reverse("add-restaurant")}"')
        self.assertContains(response, 'id="restaurant-name"')
        self.assertContains(response, 'id="restaurant-country"')
        self.assertContains(response, 'id="restaurant-city"')
        self.assertContains(
            response,
            'data-restaurant-reviews-url="'
            f'{reverse("list-all-reviews", kwargs={"restaurant_id": 0})}"',
        )
        self.assertContains(
            response,
            'data-submit-review-url="'
            f'{reverse("submit-review", kwargs={"restaurant_id": 0})}"',
        )
        for category in self.scores:
            self.assertContains(response, f'id="score-{category}"')
        self.assertNotContains(response, '<fieldset disabled>')

    def test_home_uses_review_namespace_without_legacy_wording(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                if authenticated:
                    self.client.force_login(self.user)
                else:
                    self.client.logout()
                response = self.client.get(reverse('home'))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'reviews/home.html')
                self.assertTemplateUsed(response, 'reviews/base.html')
                self.assertContains(response, 'id="reviews-app"', count=1)
                self.assertContains(
                    response, f'data-my-reviews-url="{reverse("my-reviews")}"',
                )
                self.assertContains(
                    response,
                    'data-restaurant-reviews-url="'
                    f'{reverse("list-all-reviews", kwargs={"restaurant_id": 0})}"',
                )
                self.assertContains(
                    response,
                    'data-submit-review-url="'
                    f'{reverse("submit-review", kwargs={"restaurant_id": 0})}"',
                )
                self.assertContains(
                    response, '<link rel="stylesheet" href="/static/reviews/app.css">',
                )
                self.assertContains(
                    response, '<script src="/static/reviews/app.js" defer></script>',
                )
                for element_id in (
                    'review-title', 'review-form', 'review-restaurant-id',
                    'review-total', 'save-review', 'my-reviews-title',
                    'refresh-reviews', 'my-reviews', 'restaurant-reviews',
                ):
                    self.assertContains(response, f'id="{element_id}"', count=1)
                self.assertContains(response, 'class="panel review-panel"')
                self.assertContains(response, 'class="reviews-list"')
                markup = response.content.decode(response.charset).lower()
                self.assertNotIn('rat' + 'ing', markup)
                self.assertNotRegex(markup, r'\brate(?:d|s)?\b')

    def test_login_page_is_public_and_renders_custom_form(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reviews/login.html')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertIn('csrftoken', response.cookies)

    def test_restaurant_explorer_is_public_and_does_not_query_restaurants(self):
        with self.assertNumQueries(0):
            response = self.client.get(reverse('restaurants'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(reverse('restaurants'), '/restaurants/')
        self.assertTemplateUsed(response, 'reviews/restaurants.html')
        self.assertTemplateUsed(response, 'reviews/base.html')
        self.assertContains(response, '/static/reviews/app.css')
        self.assertContains(response, '/static/reviews/restaurants.js')
        self.assertNotContains(response, '/static/reviews/app.js')
        self.assertContains(response, 'data-authenticated="false"')
        self.assertContains(response, '<fieldset disabled>', count=1)
        self.assertContains(response, 'Sign in to explore')
        self.assertContains(response, f'{reverse("login")}?next={reverse("restaurants")}')
        self.assertNotContains(response, 'Place 42')

    def test_authenticated_restaurant_explorer_wires_filters_and_response(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('restaurants'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-authenticated="true"')
        self.assertContains(response, f'data-restaurants-url="{reverse("get-restaurants")}"')
        self.assertNotContains(response, '<fieldset disabled>')
        self.assertNotContains(response, 'Sign in to explore')
        for element_id in (
            'restaurants-form', 'filter-city', 'filter-country', 'filter-count',
            'restaurants-request-url', 'restaurants-results',
            'restaurants-response-meta', 'restaurants-response-body',
        ):
            self.assertContains(response, f'id="{element_id}"', count=1)
        self.assertContains(response, 'No request sent yet.')

    def test_frontend_navigation_links_both_pages_and_marks_current_page(self):
        for page in ('home', 'restaurants', 'login'):
            with self.subTest(page=page):
                response = self.client.get(reverse(page))
                self.assertContains(response, f'href="{reverse("home")}"')
                self.assertContains(response, f'href="{reverse("restaurants")}"')
                if page != 'login':
                    self.assertContains(response, f'href="{reverse(page)}" aria-current="page"', count=1)

    def test_frontend_login_can_return_to_restaurant_explorer(self):
        response = self.client.post(reverse('login'), {
            'username': self.user.username,
            'password': 'test-only-password',
            'next': reverse('restaurants'),
        })

        self.assertRedirects(response, reverse('restaurants'))

    def test_explorer_session_can_read_api_without_csrf_or_data_changes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get(reverse('restaurants'))

        response = client.get(reverse('get-restaurants'), {'city': 'London', 'count': 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['city'], 'London')
        self.assertEqual(Restaurant.objects.count(), 2)
        self.assertFalse(Review.objects.exists())

    def test_frontend_login_defaults_to_home(self):
        response = self.client.post(
            reverse('login'),
            {'username': self.user.username, 'password': 'test-only-password'},
        )

        self.assertRedirects(response, reverse('home'))

    def test_frontend_login_preserves_local_next_destination(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': self.user.username,
                'password': 'test-only-password',
                'next': reverse('my-reviews'),
            },
        )

        self.assertRedirects(response, reverse('my-reviews'))

    def test_frontend_login_rejects_external_next_destination(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': self.user.username,
                'password': 'test-only-password',
                'next': 'https://example.com/',
            },
        )

        self.assertRedirects(response, reverse('home'))

    def test_invalid_login_displays_error_without_echoing_password(self):
        response = self.client.post(
            reverse('login'),
            {'username': self.user.username, 'password': 'incorrect-password'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign-in failed.')
        self.assertNotContains(response, 'incorrect-password')

    def test_frontend_login_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            reverse('login'),
            {'username': self.user.username, 'password': 'test-only-password'},
        )

        self.assertEqual(response.status_code, 403)

    def test_home_token_allows_session_authenticated_api_save(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        home_response = client.get(reverse('home'))
        token = home_response.cookies['csrftoken'].value
        url = reverse('submit-review', kwargs={'restaurant_id': 42})

        rejected = client.post(url, self.scores, content_type='application/json')
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(Review.objects.exists())

        response = client.post(
            url,
            self.scores,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['your_total'], 85)
        self.assertEqual(Review.objects.get().user, self.user)

    def test_logout_requires_post_and_csrf_and_returns_home(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        home_response = client.get(reverse('home'))
        token = home_response.cookies['csrftoken'].value

        self.assertEqual(client.get(reverse('logout')).status_code, 405)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
        response = client.post(reverse('logout'), {'csrfmiddlewaretoken': token})

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(client.get(reverse('my-reviews')).status_code, 403)

    def test_restaurant_lookup_includes_other_users_but_not_other_places(self):
        self.client.force_login(self.user)
        other = get_user_model().objects.create_user(username='other-reviewer')
        Review.objects.create(user=self.user, restaurant_id=42, **self.scores)
        Review.objects.create(user=other, restaurant_id=42, **self.scores)
        Review.objects.create(user=other, restaurant_id=99, **self.scores)

        response = self.client.get(
            reverse('list-all-reviews', kwargs={'restaurant_id': 42})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for review in response.json():
            self.assertEqual(review['restaurant_id'], 42)
            self.assertEqual(review['total'], 85)
            self.assertNotIn('user', review)

    def test_anonymous_users_cannot_lookup_restaurant_reviews(self):
        response = self.client.get(
            reverse('list-all-reviews', kwargs={'restaurant_id': 42})
        )

        self.assertEqual(response.status_code, 403)

    def test_session_creation_requires_csrf_and_returned_id_can_be_reviewed(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = client.get(reverse('home')).cookies['csrftoken'].value
        url = reverse('add-restaurant')
        details = {'name': 'New place', 'country': 'United Kingdom', 'city': 'London'}
        rejected = client.post(url, details, content_type='application/json')
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(Restaurant.objects.count(), 2)
        created = client.post(
            url, details, content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['country'], 'United Kingdom')
        self.assertEqual(created.json()['city'], 'London')
        self.assertFalse(Review.objects.exists())
        saved = client.post(
            reverse('submit-review', kwargs={'restaurant_id': created.json()['id']}),
            self.scores, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['your_total'], 85)


class RestaurantMigrationTests(TransactionTestCase):
    migrate_from = [('reviews', '0001_initial')]
    migrate_to = [('reviews', '0002_restaurant')]

    def setUp(self):
        # MigrationExecutor always operates on Django's temporary test database.
        self.addCleanup(self.restore_latest_schema)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        user = old_apps.get_model('auth', 'User').objects.create(username='migration-user')
        self.user_pk = user.pk
        old_review_model = old_apps.get_model('reviews', 'Rating')
        for restaurant_id in (42, 99):
            old_review_model.objects.create(
                user_id=user.pk, restaurant_id=restaurant_id,
                food=18, drink=15, service=17, vibes=19, value=16,
            )
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    @staticmethod
    def restore_latest_schema():
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_upgrade_discards_only_prototype_reviews_and_keeps_constraints(self):
        review_model = self.apps.get_model('reviews', 'Rating')
        restaurant_model = self.apps.get_model('reviews', 'Restaurant')
        self.assertEqual(review_model._meta.db_table, 'reviews_rating')
        self.assertEqual(restaurant_model._meta.db_table, 'reviews_restaurant')
        self.assertFalse(review_model.objects.exists())
        self.assertFalse(restaurant_model.objects.exists())
        self.assertTrue(self.apps.get_model('auth', 'User').objects.filter(pk=self.user_pk).exists())
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, review_model._meta.db_table)
        self.assertTrue(constraints['unique_user_restaurant_rating']['unique'])
        self.assertEqual(set(constraints['unique_user_restaurant_rating']['columns']), {'user_id', 'restaurant_id'})
        self.assertTrue(any(
            constraint['foreign_key'] == ('reviews_restaurant', 'id')
            for constraint in constraints.values()
        ))
        for category in ('food', 'drink', 'service', 'vibes', 'value'):
            self.assertTrue(constraints[f'rating_{category}_between_1_and_20']['check'])
        restaurant = restaurant_model.objects.create(name='Real place')
        review = review_model.objects.create(
            user_id=self.user_pk, restaurant=restaurant,
            food=18, drink=15, service=17, vibes=19, value=16,
        )
        self.assertEqual(review.restaurant_id, restaurant.pk)
        connection.check_constraints()


class RestaurantLocationMigrationTests(TransactionTestCase):
    def test_location_upgrade_preserves_restaurants_reviews_and_accounts(self):
        self.addCleanup(RestaurantMigrationTests.restore_latest_schema)
        old_target = [('reviews', '0002_restaurant')]
        new_target = [('reviews', '0003_restaurant_location')]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        user = old_apps.get_model('auth', 'User').objects.create(username='location-user')
        restaurant = old_apps.get_model('reviews', 'Restaurant').objects.create(name='Existing place')
        review = old_apps.get_model('reviews', 'Rating').objects.create(
            user_id=user.pk, restaurant_id=restaurant.pk,
            food=18, drink=15, service=17, vibes=19, value=16,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        apps = executor.loader.project_state(new_target).apps
        migrated = apps.get_model('reviews', 'Restaurant').objects.get(pk=restaurant.pk)
        self.assertEqual(migrated.name, 'Existing place')
        self.assertEqual(migrated.country, '')
        self.assertEqual(migrated.city, '')
        preserved_review = apps.get_model('reviews', 'Rating').objects.get(pk=review.pk)
        self.assertEqual(preserved_review.restaurant_id, restaurant.pk)
        self.assertEqual(preserved_review.user_id, user.pk)
        for category in ('food', 'drink', 'service', 'vibes', 'value'):
            self.assertEqual(getattr(preserved_review, category), getattr(review, category))
        self.assertTrue(apps.get_model('auth', 'User').objects.filter(pk=user.pk).exists())
        connection.check_constraints()


class ReviewMigrationTests(TransactionTestCase):
    migrate_from = [('reviews', '0003_restaurant_location')]
    migrate_to = [('reviews', '0004_review')]
    categories = ('food', 'drink', 'service', 'vibes', 'value')

    def setUp(self):
        # Only Django's temporary test database is migrated, even on failure.
        self.addCleanup(RestaurantMigrationTests.restore_latest_schema)
        old_apps = self._migrate(self.migrate_from)
        user_model = old_apps.get_model('auth', 'User')
        user = user_model.objects.create(
            username='review-migration-user',
            password='!preserved-unusable-password',
            email='reviewer@example.com',
            first_name='Existing', last_name='Reviewer',
            is_active=True, is_staff=True,
        )
        self.account_values = user_model.objects.values().get(pk=user.pk)
        restaurant_model = old_apps.get_model('reviews', 'Restaurant')
        restaurant = restaurant_model.objects.create(
            name='Existing cafe', country='日本', city='東京',
        )
        self.restaurant_values = restaurant_model.objects.values().get(pk=restaurant.pk)
        old_review_model = old_apps.get_model('reviews', 'Rating')
        old_review = old_review_model.objects.create(
            user_id=user.pk, restaurant_id=restaurant.pk,
            food=18, drink=15, service=17, vibes=19, value=16,
        )
        # QuerySet.update bypasses auto_now/auto_now_add so timestamps are distinct
        # and exact preservation is checked rather than just non-null values.
        old_review_model.objects.filter(pk=old_review.pk).update(
            created_at=datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc),
            updated_at=datetime(2025, 6, 7, 8, 9, 10, 654321, tzinfo=timezone.utc),
        )
        self.review_values = old_review_model.objects.values().get(pk=old_review.pk)

    @staticmethod
    def _migrate(target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def _assert_preserved_data(self, apps, model_name):
        review_model = apps.get_model('reviews', model_name)
        restaurant_model = apps.get_model('reviews', 'Restaurant')
        user_model = apps.get_model('auth', 'User')
        self.assertEqual(review_model.objects.count(), 1)
        self.assertEqual(
            review_model.objects.values().get(pk=self.review_values['id']),
            self.review_values,
        )
        self.assertEqual(
            restaurant_model.objects.values().get(pk=self.restaurant_values['id']),
            self.restaurant_values,
        )
        self.assertEqual(
            user_model.objects.values().get(pk=self.account_values['id']),
            self.account_values,
        )

    def _assert_schema(self, apps, model_name, prefix, absent_model_name):
        review_model = apps.get_model('reviews', model_name)
        restaurant_model = apps.get_model('reviews', 'Restaurant')
        user_model = apps.get_model('auth', 'User')
        self.assertEqual(review_model._meta.model_name, prefix)
        self.assertEqual(review_model._meta.db_table, f'reviews_{prefix}')
        self.assertEqual(restaurant_model._meta.db_table, 'reviews_restaurant')
        tables = connection.introspection.table_names()
        self.assertIn(f'reviews_{prefix}', tables)
        self.assertIn('reviews_restaurant', tables)
        self.assertNotIn(f'reviews_{absent_model_name.lower()}', tables)
        with self.assertRaises(LookupError):
            apps.get_model('reviews', absent_model_name)

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, review_model._meta.db_table,
            )
        unique_name = f'unique_user_restaurant_{prefix}'
        expected_names = {unique_name} | {
            f'{prefix}_{category}_between_1_and_20' for category in self.categories
        }
        self.assertEqual(
            {constraint.name for constraint in review_model._meta.constraints},
            expected_names,
        )
        self.assertTrue(constraints[unique_name]['unique'])
        self.assertEqual(
            set(constraints[unique_name]['columns']), {'user_id', 'restaurant_id'},
        )
        absent_prefix = absent_model_name.lower()
        self.assertNotIn(f'unique_user_restaurant_{absent_prefix}', constraints)
        for category in self.categories:
            with self.subTest(model=model_name, category=category):
                check = constraints[f'{prefix}_{category}_between_1_and_20']
                self.assertTrue(check['check'])
                self.assertEqual(set(check['columns']), {category})
                self.assertNotIn(
                    f'{absent_prefix}_{category}_between_1_and_20', constraints,
                )
        # FK names are backend-generated; verify both columns and destinations.
        self.assertEqual(
            {
                (tuple(constraint['columns']), constraint['foreign_key'])
                for constraint in constraints.values()
                if constraint['foreign_key'] is not None
            },
            {
                (('user_id',), (user_model._meta.db_table, user_model._meta.pk.column)),
                (('restaurant_id',), (
                    restaurant_model._meta.db_table, restaurant_model._meta.pk.column,
                )),
            },
        )
        connection.check_constraints()

    def _assert_constraints_are_enforced(self, apps, model_name):
        review_model = apps.get_model('reviews', model_name)
        scores = {category: self.review_values[category] for category in self.categories}
        with self.assertRaises(IntegrityError), transaction.atomic():
            review_model.objects.create(
                user_id=self.review_values['user_id'],
                restaurant_id=self.review_values['restaurant_id'], **scores,
            )
        for category in self.categories:
            for score in (0, 21):
                with self.subTest(model=model_name, category=category, score=score):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        review_model.objects.filter(pk=self.review_values['id']).update(
                            **{category: score},
                        )
        for field in ('user_id', 'restaurant_id'):
            with self.subTest(model=model_name, foreign_key=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    review_model.objects.filter(pk=self.review_values['id']).update(
                        **{field: 2**62},
                    )
                    # SQLite defers foreign keys until commit; check them explicitly.
                    connection.check_constraints(table_names=[review_model._meta.db_table])

    def test_upgrade_preserves_reviews_restaurants_accounts_and_renames_schema(self):
        apps = self._migrate(self.migrate_to)

        self._assert_preserved_data(apps, 'Review')
        self._assert_schema(apps, 'Review', 'review', 'Rating')
        self._assert_constraints_are_enforced(apps, 'Review')
        self._assert_preserved_data(apps, 'Review')

    def test_reversal_preserves_reviews_and_restores_historical_model_and_constraints(self):
        apps = self._migrate(self.migrate_to)
        self._assert_preserved_data(apps, 'Review')
        self._assert_schema(apps, 'Review', 'review', 'Rating')

        apps = self._migrate(self.migrate_from)

        self._assert_preserved_data(apps, 'Rating')
        self._assert_schema(apps, 'Rating', 'rating', 'Review')
        self._assert_constraints_are_enforced(apps, 'Rating')
        self._assert_preserved_data(apps, 'Rating')