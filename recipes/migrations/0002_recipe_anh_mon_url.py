from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('recipes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='recipe',
            name='anh_mon_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
    ]
