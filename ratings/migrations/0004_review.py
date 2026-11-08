from django.db import migrations, models


CATEGORIES = ('food', 'drink', 'service', 'vibes', 'value')


class Migration(migrations.Migration):
    dependencies = [('ratings', '0003_restaurant_location')]

    operations = [
        migrations.RenameModel(old_name='Rating', new_name='Review'),
        migrations.RemoveConstraint(
            model_name='review', name='unique_user_restaurant_rating',
        ),
        *[
            migrations.RemoveConstraint(
                model_name='review', name=f'rating_{category}_between_1_and_20',
            )
            for category in CATEGORIES
        ],
        migrations.AddConstraint(
            model_name='review',
            constraint=models.UniqueConstraint(
                fields=('user', 'restaurant'),
                name='unique_user_restaurant_review',
            ),
        ),
        *[
            migrations.AddConstraint(
                model_name='review',
                constraint=models.CheckConstraint(
                    condition=models.Q(
                        **{f'{category}__gte': 1, f'{category}__lte': 20}
                    ),
                    name=f'review_{category}_between_1_and_20',
                ),
            )
            for category in CATEGORIES
        ],
    ]