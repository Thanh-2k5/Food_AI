"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from recognition import views as recognition_views
from recognition import page_views
from recognition.forms import EmailOrUsernameAuthenticationForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='auth_form.html',
            authentication_form=EmailOrUsernameAuthenticationForm,
            next_page='home',
            redirect_authenticated_user=True,
            extra_context={
                'page_title': 'Đăng nhập',
                'submit_label': 'Đăng nhập',
                'other_url': 'register',
                'other_label': 'Đăng ký ngay',
            },
        ),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(next_page='home'),
        name='logout',
    ),
    path('register/', page_views.register, name='register'),
    path('detect/', recognition_views.detect, name='detect'),
    path('recommendations/', page_views.recommendations, name='recommendations'),
    path(
        'recipe-detail/<int:recipe_id>/',
        page_views.recipe_detail,
        name='recipe_detail',
    ),
    path(
        'recipe-detail/',
        page_views.recipe_detail,
        name='recipe_detail_legacy',
    ),
    path('history/', page_views.history, name='history'),
    path(
        'history/<int:history_id>/remove/',
        page_views.remove_history,
        name='remove_history',
    ),
    path('favorites/', page_views.favorites, name='favorites'),
    path(
        'favorites/<int:favorite_id>/remove/',
        page_views.remove_favorite,
        name='remove_favorite',
    ),
    path(
        'recipe-detail/<int:recipe_id>/favorite/',
        page_views.toggle_favorite,
        name='toggle_favorite',
    ),
    path('', include('recognition.urls')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
