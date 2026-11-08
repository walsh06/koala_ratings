import django.db.models.deletion
from django.db import migrations, models


def discard_prototype_ratings(apps, schema_editor):
    # Explicitly agreed prototype reset: keep accounts and all unrelated data.
    rating = apps.get_model('ratings', 'Rating')
    rating.objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [('ratings', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='Restaurant',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('name', models.CharField(max_length=200)),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='rating', name='unique_user_restaurant_rating',
        ),
        migrations.RunPython(
            discard_prototype_ratings, reverse_code=migrations.RunPython.noop,
        ),
        migrations.RenameField(
            model_name='rating', old_name='restaurant_id', new_name='restaurant',
        ),
        migrations.AlterField(
            model_name='rating', name='restaurant',
            field=models.ForeignKey(
                db_column='restaurant_id',
                on_delete=django.db.models.deletion.PROTECT,
                to='ratings.restaurant',
            ),
        ),
        migrations.AddConstraint(
            model_name='rating',
            constraint=models.UniqueConstraint(
                fields=('user', 'restaurant'),
                name='unique_user_restaurant_rating',
            ),
        ),
    ]