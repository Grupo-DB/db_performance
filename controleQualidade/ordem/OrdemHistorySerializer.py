# serializers.py
from rest_framework import serializers
from simple_history.utils import update_change_reason
from .models import Ordem

class OrdemHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField(source='instance.id', read_only=True)
    history_id = serializers.IntegerField()
    history_date = serializers.DateTimeField()
    history_user = serializers.SerializerMethodField()
    history_type = serializers.CharField()
    diff = serializers.SerializerMethodField()

    def get_history_user(self, obj):
        if obj.history_user:
            return obj.history_user.get_full_name() or obj.history_user.username
        return None

    def get_diff(self, obj):
        previous = obj.prev_record
        if not previous:
            return None

        diff = {}
        for field in obj.instance._meta.fields:
            field_name = field.name
            if getattr(previous, field_name, None) != getattr(obj, field_name, None):
                diff[field_name] = {
                    "before": getattr(previous, field_name, None),
                    "after": getattr(obj, field_name, None),
                }
        return diff
