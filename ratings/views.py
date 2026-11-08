from django.db.models.aggregates import Avg
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Restaurant, Review


def get_koalas(score):
    koalas = int((score-75)/5) if score < 100 else 5
    return max(0, koalas)

@ensure_csrf_cookie
def home(request):
    return render(
        request,
        'ratings/home.html',
        {
            'categories': [
                ('food', 'Food', 'Every bite counts.'),
                ('drink', 'Drink', 'From first sip to last.'),
                ('service', 'Service', 'The people behind the experience.'),
                ('vibes', 'Vibes', 'The feeling of being there.'),
                ('value', 'Value', 'Was it worth it?'),
            ],
        },
    )


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = ['id', 'name', 'country', 'city']
        read_only_fields = ['id']


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_restaurant(request):
    serializer = RestaurantSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_restaurants(request):
    restaurants = Restaurant.objects.all().order_by('name')
    serializer = RestaurantSerializer(restaurants, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

def _get_restaurant(restaurant_id):
    # Avoid overflowing the signed 64-bit primary key in database adapters.
    if not 1 <= restaurant_id <= 2**63 - 1:
        raise NotFound('Restaurant not found.')
    try:
        return Restaurant.objects.get(pk=restaurant_id)
    except Restaurant.DoesNotExist:
        raise NotFound('Restaurant not found.') from None


class ReviewSerializer(serializers.Serializer):
    food = serializers.IntegerField(min_value=1, max_value=20)
    drink = serializers.IntegerField(min_value=1, max_value=20)
    service = serializers.IntegerField(min_value=1, max_value=20)
    vibes = serializers.IntegerField(min_value=1, max_value=20)
    value = serializers.IntegerField(min_value=1, max_value=20)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_my_reviews(request):
    reviews = Review.objects.filter(user=request.user).order_by('restaurant_id')
    results = []
    for review in reviews:
        scores = ReviewSerializer(review).data
        results.append(
            {
                'restaurant_id': review.restaurant_id,
                'scores': scores,
                'your_total': sum(scores.values()),
            }
        )
    return Response(results, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_all_reviews(request, restaurant_id):
    restaurant = _get_restaurant(restaurant_id)
    reviews = Review.objects.filter(restaurant=restaurant).order_by('pk')
    results = []
    for review in reviews:
        scores = ReviewSerializer(review).data
        results.append(
            {
                'restaurant_id': review.restaurant_id,
                'scores': scores,
                'total': sum(scores.values()),
            }
        )
    return Response(results, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_restaurants(request):
    filters = {}
    if 'city' in request.query_params:
        filters['city'] = request.query_params['city']
    if 'country' in request.query_params:
        filters['country'] = request.query_params['country']
    restaurants = Restaurant.objects.filter(**filters)
    
    results = []
    for restaurant in restaurants:
        reviews = Review.objects.filter(restaurant=restaurant)
        total_reviews = reviews.count()
        average_score = reviews.aggregate(
            food_avg=Avg('food'),
            drink_avg=Avg('drink'),
            service_avg=Avg('service'),
            vibes_avg=Avg('vibes'),
            value_avg=Avg('value')
        )
        total_average = sum(average_score.values()) / len(average_score) if total_reviews > 0 else 0
        koalas = get_koalas(total_average)
        results.append(
            {
                'id': restaurant.id,
                'name': restaurant.name,
                'city': restaurant.city,
                'country': restaurant.country,
                'total_reviews': total_reviews,
                'average_score': average_score,
                'total_average': total_average,
                'koalas': koalas,
            }
        )
    if 'count' in request.query_params:
        try:
            count = int(request.query_params['count'])
            results = results[:count]
        except ValueError:
            pass
    return Response(results, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_review(request, restaurant_id):
    restaurant = _get_restaurant(restaurant_id)
    serializer = ReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    scores = serializer.validated_data
    Review.objects.update_or_create(
        user=request.user,
        restaurant=restaurant,
        defaults=scores,
    )

    return Response(
        {
            'restaurant_id': restaurant_id,
            'scores': scores,
            'your_total': sum(scores.values()),
        },
        status=status.HTTP_200_OK,
    )
