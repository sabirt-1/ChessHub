
from django.urls import path
from .views import *

urlpatterns = [
    path('', auth_page, name='auth'),
    path('dashboard/', dashboard, name='dashboard'),
    path('logout/', logout_page, name='logout'),
    path('edit_profile/', edit_profile, name='edit_profile'),
    path('booking_advanced/', booking_advanced, name='booking_advanced'),
    # path('save-booking/', save_booking),
    path('create-payment-order/', create_payment_order, name='create_payment_order'),
    path('verify-payment/', verify_payment, name='verify_payment'),
    path('payment-success/', payment_success, name='payment_success'),
    path('payment-failed/', payment_failed, name='payment_failed'),
    path('get-holidays/', get_holidays, name='get_holidays'),

    path('history/', history, name='history'),
    path('delete/<int:id>/', delete_booking),
    path('reschedule/<int:id>/', reschedule),
]
