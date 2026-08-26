from django.urls import path

from apps.auditoria import api

urlpatterns = [
    path('', api.registros, name='auditoria'),
]
