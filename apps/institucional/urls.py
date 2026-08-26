from django.urls import path

from apps.institucional import api

urlpatterns = [
    path('units', api.unidades, name='unidades'),
    path('coordinations', api.coordenacoes, name='coordenacoes'),
    path('demands', api.demandas, name='demandas'),
    path('services', api.servicos, name='servicos'),
]
