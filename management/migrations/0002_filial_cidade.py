# Generated by Django 5.0.3 on 2024-04-16 11:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='filial',
            name='cidade',
            field=models.CharField(default=65, max_length=50),
            preserve_default=False,
        ),
    ]