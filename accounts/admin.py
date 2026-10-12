from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Holiday)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "date", "time", "plan", "status")
    search_fields = ("user__username", "time")
    list_filter = ("status", "plan", "date")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "razorpay_order_id", "razorpay_payment_id", "user",
        "amount", "currency", "plan", "status", "created_at", "paid_at",
    )
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "user__username")
    list_filter = ("status", "plan", "currency")
