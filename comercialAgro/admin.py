from django.contrib import admin

from .models import AreaPlantada, BuscaCarMunicipio, Contato, Cotacao, ImovelCar, MetaAgro, Produtor, VendedorAgro

admin.site.register([VendedorAgro, MetaAgro, Produtor, Contato, Cotacao, AreaPlantada, ImovelCar, BuscaCarMunicipio])
