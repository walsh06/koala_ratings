from django.conf import settings
from django.db import models


class Restaurant(models.Model):
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.PROTECT, db_column='restaurant_id'
    )
    food = models.PositiveSmallIntegerField()
    drink = models.PositiveSmallIntegerField()
    service = models.PositiveSmallIntegerField()
    vibes = models.PositiveSmallIntegerField()
    value = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'restaurant'],
                name='unique_user_restaurant_review',
            ),
            *[
                models.CheckConstraint(
                    condition=models.Q(
                        **{f'{category}__gte': 1, f'{category}__lte': 20}
                    ),
                    name=f'review_{category}_between_1_and_20',
                )
                for category in ('food', 'drink', 'service', 'vibes', 'value')
            ],
        ]