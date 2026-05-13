from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.dashboard_home, name="dashboard"),
    path("orders/board/<str:tab>/", views.order_board, name="order_board"),
    path("orders/<int:pk>/", views.order_detail_shop, name="order_detail"),
    path("tickets/<int:pk>/next-stage/", views.ticket_next_stage, name="ticket_next_stage"),
    path("reports/", views.reports_dashboard, name="reports"),
    path("reports/daily-metrics/", views.trigger_daily_metrics, name="trigger_daily_metrics"),
    path("sql-assistant/", views.sql_assistant, name="sql_assistant"),
    path("monitor/<str:filter_name>/", views.order_monitor, name="order_monitor"),
    path("customers/", views.customer_search, name="customer_search"),
    path(
        "internal/profile-measurements/<int:customer_id>/",
        views.customer_profile_measurements_api,
        name="customer_profile_measurements",
    ),
    path("customers/<int:customer_id>/history/", views.customer_history, name="customer_history"),
]
