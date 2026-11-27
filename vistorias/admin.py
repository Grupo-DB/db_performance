from django.contrib import admin

from . import models

for m in (models.Unidade, models.Setor, models.Ficha, models.FichaVersao, models.TipoEquipamento, models.Equipamento,
          models.DestinatarioNotificacao, models.ProgramaItem, models.Vistoria, models.Suspensao, models.EmailVistoria,
          models.FechamentoMensal, models.Auditoria):
    admin.site.register(m)
