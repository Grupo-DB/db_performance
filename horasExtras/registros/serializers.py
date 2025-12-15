from rest_framework import serializers
from controleQualidade.ensaio.serializers import EnsaioSerializer
from controleQualidade.calculosEnsaio.serializers import CalculoEnsaioSerializer
from controleQualidade.ensaio.models import Ensaio
from controleQualidade.calculosEnsaio.models import CalculoEnsaio
from .models import RegistroHoraExtra



class RegistroHoraExtraSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroHoraExtra
        fields = '__all__'