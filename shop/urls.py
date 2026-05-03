from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.dashboard_home, name="dashboard"),
    path("orders/<str:filter_name>/", views.order_monitor, name="order_monitor"),
    path("customers/", views.customer_search, name="customer_search"),
    path("customers/<int:customer_id>/history/", views.customer_history, name="customer_history"),
]
