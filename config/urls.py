"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path
from django.views.generic import TemplateView

from reviews.views import (
    add_restaurant, home, list_all_reviews, list_my_reviews, submit_review,
    get_restaurants,
)

urlpatterns = [
    path('', home, name='home'),
    path(
        'restaurants/',
        TemplateView.as_view(template_name='reviews/restaurants.html'),
        name='restaurants',
    ),
    path(
        'login/',
        LoginView.as_view(template_name='reviews/login.html', next_page='home'),
        name='login',
    ),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('admin/', admin.site.urls),
    path('api-auth/', include('rest_framework.urls')),
    path('api/me/reviews/', list_my_reviews, name='my-reviews'),
    path('api/restaurants/', add_restaurant, name='add-restaurant'),
    path('api/restaurants/get/', get_restaurants, name='get-restaurants'),
    path(
        'api/restaurants/<int:restaurant_id>/reviews/all/',
        list_all_reviews,
        name='list-all-reviews',
    ),
    path(
        'api/restaurants/<int:restaurant_id>/submit-review/',
        submit_review,
        name='submit-review',
    ),
]
