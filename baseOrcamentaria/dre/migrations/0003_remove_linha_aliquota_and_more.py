# Generated by Django 5.0.3 on 2024-12-29 22:18

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dre', '0002_produto_remove_linha_nome_linha_produto'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='linha',
            name='aliquota',
        ),
        migrations.RemoveField(
            model_name='linha',
            name='quantidade_produzida',
        ),
    ]
