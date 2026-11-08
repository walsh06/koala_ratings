from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ratings', '0002_restaurant')]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='country',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='restaurant',
            name='city',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
    ]