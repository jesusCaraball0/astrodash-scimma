from django.urls import path
from astrodash import ui_views

app_name = "astrodash"

urlpatterns = [
    # App static images (logo, favicon) served from app/astrodash/static/images/
    path("static/images/<path:path>", ui_views.serve_app_static_image, name="app_static_images"),
    # UI Views
    path("", ui_views.landing_page, name="landing_page"),
    path("select-model/", ui_views.model_selection, name="model_selection"),
    path("classify/", ui_views.classify, name="classify"),
    path("batch/", ui_views.batch_process, name="batch_process_ui"),
    path("team/", ui_views.team_members, name="team_members"),
    path("classify/twins/", ui_views.dash_twins, name="dash_twins"),
    path("classify/twins/data/", ui_views.dash_twins_data, name="dash_twins_data"),
    path("classify/twins/search/", ui_views.twins_search, name="twins_search"),
]
