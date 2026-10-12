


from calendar import monthrange
from datetime import datetime
import json

import requests
import razorpay

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Booking, CustomUser, Holiday, Payment


MAX_SLOTS_PER_DAY = 5

PLAN_PRICES = {
    "basic": 300,
    "custom": 2400,
    "premium": 300,
}

ALLOWED_TIMES = {
    "09:00 - 10:00",
    "10:00 - 11:00",
    "11:00 - 12:00",
    "12:00 - 13:00",
    "13:00 - 14:00",
    "14:00 - 15:00",
    "15:00 - 16:00",
    "16:00 - 17:00",
    "17:00 - 18:00",
    "18:00 - 19:00",
}


# BOOKING VALIDATION

def _validate_booking_request(user, dates, time, plan):

    if not isinstance(dates, list) or not dates or not time:
        raise ValueError("Missing booking data")

    if plan not in PLAN_PRICES:
        raise ValueError("Invalid plan")

    if time not in ALLOWED_TIMES:
        raise ValueError("Invalid time slot")

    # Extra validation of time format
    try:
        time_from, time_to = time.split(" - ")
        t1 = datetime.strptime(time_from, "%H:%M")
        t2 = datetime.strptime(time_to, "%H:%M")
    except (ValueError, TypeError):
        raise ValueError("Invalid time format")

    if t1 >= t2:
        raise ValueError("Invalid time range")

    if plan == "basic" and len(dates) != 1:
        raise ValueError("Basic allows only 1 slot at a time")

    if plan == "custom" and len(dates) != 8:
        raise ValueError("Custom plan requires exactly 8 slots")

    parsed_dates = []
    today = timezone.localdate()

    for date_str in dates:

        try:
            date = datetime.strptime(
                str(date_str),
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            raise ValueError(f"Invalid date: {date_str}")

        if date < today:
            raise ValueError(f"{date} is in the past")

        if date in parsed_dates:
            raise ValueError(f"Duplicate date: {date}")

        if Holiday.objects.filter(date=date).exists():
            raise ValueError(f"{date} is a holiday")

        # Only active bookings should consume available slots
        if Booking.objects.filter(
            date=date,
            status="active"
        ).count() >= MAX_SLOTS_PER_DAY:

            raise ValueError(f"{date} is fully booked")

        # Same date + same time cannot be booked twice
        if Booking.objects.filter(
            date=date,
            time=time,
            status="active"
        ).exists():

            raise ValueError(
                f"{date} {time} is already taken"
            )

        # Same user cannot have duplicate active booking
        if Booking.objects.filter(
            user=user,
            date=date,
            time=time,
            status="active"
        ).exists():

            raise ValueError(
                f"{date} is already booked"
            )

        parsed_dates.append(date)

    return parsed_dates


def _booking_amount_paise(plan, date_count):

    if plan == "custom":
        rupees = PLAN_PRICES["custom"]
    else:
        rupees = PLAN_PRICES[plan] * date_count

    return rupees * 100


def _refund_test_payment(client, payment):

    try:

        client.payment.refund(
            payment.razorpay_payment_id,
            {
                "amount": payment.amount
            }
        )

        payment.status = "refunded"

        payment.save(
            update_fields=["status"]
        )

        return True

    except Exception:
        return False



# PROFILE

@login_required
def edit_profile(request):

    user = request.user

    if request.method == "POST":

        user.username = request.POST.get("username")
        user.email = request.POST.get("email")
        user.age = request.POST.get("age")
        user.gender = request.POST.get("gender")

        if request.FILES.get("image"):
            user.image = request.FILES.get("image")

        user.save()

        return redirect("dashboard")

    return render(
        request,
        "edit_profile.html"
    )


# AUTHENTICATION

def auth_page(request):

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":

        action = request.POST.get("action")

        # REGISTER

        if action == "register":

            username = request.POST.get("username")
            email = request.POST.get("email")
            password = request.POST.get("password")
            age = request.POST.get("age")
            gender = request.POST.get("gender")
            image = request.FILES.get("image")

            if CustomUser.objects.filter(
                username=username
            ).exists():

                messages.error(
                    request,
                    "Username already exists"
                )

                return redirect("auth")

            CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                age=age,
                gender=gender,
                image=image
            )

            messages.success(
                request,
                "Registration successful"
            )

            return redirect("auth")

        # LOGIN

        elif action == "login":

            username = request.POST.get("email")
            password = request.POST.get("password")

            user = authenticate(
                request,
                username=username,
                password=password
            )

            if user:

                login(request, user)

                return redirect("dashboard")

            else:

                messages.error(
                    request,
                    "Invalid credentials"
                )

    return render(
        request,
        "auth.html"
    )


# DASHBOARD

@login_required(login_url="auth")
def dashboard(request):

    today = timezone.localdate()

    month_start = today.replace(day=1)

    if today.month == 12:

        next_month = today.replace(
            year=today.year + 1,
            month=1,
            day=1
        )

    else:

        next_month = today.replace(
            month=today.month + 1,
            day=1
        )

    # Only current user's bookings
    user_bookings = Booking.objects.filter(
        user=request.user
    )

    active_bookings = user_bookings.filter(
        status="active"
    )

    total = user_bookings.count()

    active = active_bookings.filter(
        date__gte=today
    ).count()

    monthly = active_bookings.filter(
        date__gte=month_start,
        date__lt=next_month
    ).count()

    cancelled = user_bookings.filter(
        status="cancelled"
    ).count()

    booked_dates = list(
        active_bookings.values_list(
            "date",
            flat=True
        )
    )

    holidays = [
        {
            "date": str(h["date"]),
            "localName": h["name"]
        }
        for h in Holiday.objects.values(
            "date",
            "name"
        )
    ]

    return render(
        request,
        "dashboard.html",
        {
            "total": total,
            "active": active,
            "monthly": monthly,
            "cancelled": cancelled,
            "booked_dates": json.dumps(
                [str(d) for d in booked_dates]
            ),
            "holidays": json.dumps(
                holidays
            ),
            "current_year": today.year,
        }
    )


# LOGOUT

@login_required
def logout_page(request):

    logout(request)

    return redirect("auth")


# LEGACY DIRECT BOOKING

@login_required
def book_slot(request):

    if request.method == "POST":

        date = request.POST.get("date")
        time = request.POST.get("time")

        # Prevent duplicate active booking
        if Booking.objects.filter(
            date=date,
            time=time,
            status="active"
        ).exists():

            return render(
                request,
                "booking.html",
                {
                    "error": "Slot already booked"
                }
            )

        try:

            Booking.objects.create(
                user=request.user,
                date=date,
                time=time,
                status="active"
            )

        except IntegrityError:

            return render(
                request,
                "booking.html",
                {
                    "error": "Slot was just booked by someone else"
                }
            )

        return render(
            request,
            "booking.html",
            {
                "success": "Booking successful"
            }
        )

    return render(
        request,
        "booking.html"
    )


# SAVE BOOKING

# @login_required
# @require_POST
# def save_booking(request):

#     # Legacy direct-booking endpoint.
#     # New UI uses Razorpay payment first.

#     try:

#         data = json.loads(request.body)

#         dates = data.get("dates", [])
#         time = data.get("time")
#         plan = data.get("plan")

#         parsed_dates = _validate_booking_request(
#             request.user,
#             dates,
#             time,
#             plan
#         )

#         with transaction.atomic():

#             for date in parsed_dates:

#                 Booking.objects.create(
#                     user=request.user,
#                     date=date,
#                     time=time,
#                     plan=plan,
#                     status="active"
#                 )

#         return JsonResponse(
#             {
#                 "success": True
#             }
#         )

#     except ValueError as exc:

#         return JsonResponse(
#             {
#                 "error": str(exc)
#             },
#             status=400
#         )

#     except Exception:

#         return JsonResponse(
#             {
#                 "error": "Unable to save booking"
#             },
#             status=500
#         )


# RAZORPAY - CREATE ORDER

@login_required
@require_POST
def create_payment_order(request):

    try:

        data = json.loads(request.body)

        dates = data.get("dates", [])
        time = data.get("time")
        plan = data.get("plan")

        parsed_dates = _validate_booking_request(
            request.user,
            dates,
            time,
            plan
        )

        key_id = getattr(
            settings,
            "RAZORPAY_KEY_ID",
            ""
        )

        key_secret = getattr(
            settings,
            "RAZORPAY_KEY_SECRET",
            ""
        )

        if not key_id or not key_secret:

            return JsonResponse(
                {
                    "error":
                    "Razorpay Test Mode is not configured."
                },
                status=503
            )

        amount = _booking_amount_paise(
            plan,
            len(parsed_dates)
        )

        client = razorpay.Client(
            auth=(
                key_id,
                key_secret
            )
        )

        receipt = (
            f"chesshub-"
            f"{request.user.id}-"
            f"{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
        )[-40:]

        order = client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "receipt": receipt,
                "notes": {
                    "user_id": str(
                        request.user.id
                    ),
                    "plan": plan,
                    "booking_time": time,
                    "booking_dates":
                        ",".join(
                            d.isoformat()
                            for d in parsed_dates
                        ),
                },
            }
        )

        Payment.objects.create(
            user=request.user,
            razorpay_order_id=order["id"],
            amount=amount,
            currency="INR",
            plan=plan,
            dates=[
                d.isoformat()
                for d in parsed_dates
            ],
            time=time
        )

        return JsonResponse(
            {
                "key": key_id,
                "order_id": order["id"],
                "amount": amount,
                "currency": "INR",
                "name": "ChessHub",
                "description":
                    f"{plan.title()} booking",
                "prefill": {
                    "name":
                        request.user.get_full_name()
                        or request.user.username,
                    "email":
                        request.user.email,
                },
            }
        )

    except ValueError as exc:

        return JsonResponse(
            {
                "error": str(exc)
            },
            status=400
        )

    except Exception:

        return JsonResponse(
            {
                "error":
                    "Unable to create Razorpay order"
            },
            status=500
        )


# RAZORPAY - VERIFY PAYMENT

@login_required
@require_POST
def verify_payment(request):

    payment = None
    client = None

    try:

        data = json.loads(request.body)

        order_id = data.get(
            "razorpay_order_id"
        )

        payment_id = data.get(
            "razorpay_payment_id"
        )

        signature = data.get(
            "razorpay_signature"
        )

        if not order_id or not payment_id or not signature:

            return JsonResponse(
                {
                    "error":
                        "Incomplete payment response"
                },
                status=400
            )

        payment = get_object_or_404(
            Payment,
            razorpay_order_id=order_id,
            user=request.user
        )

        if payment.status == "paid":

            return JsonResponse(
                {
                    "success": True,
                    "order_id": order_id
                }
            )

        key_id = getattr(
            settings,
            "RAZORPAY_KEY_ID",
            ""
        )

        key_secret = getattr(
            settings,
            "RAZORPAY_KEY_SECRET",
            ""
        )

        if not key_id or not key_secret:

            return JsonResponse(
                {
                    "error":
                        "Razorpay is not configured"
                },
                status=503
            )

        client = razorpay.Client(
            auth=(
                key_id,
                key_secret
            )
        )

        # 1. Verify Razorpay signature

        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )

        # 2. Fetch payment from Razorpay

        gateway_payment = client.payment.fetch(
            payment_id
        )

        gateway_order_id = gateway_payment.get(
            "order_id"
        )

        gateway_amount = int(
            gateway_payment.get(
                "amount",
                0
            )
        )

        gateway_currency = gateway_payment.get(
            "currency"
        )

        gateway_status = gateway_payment.get(
            "status"
        )

        if gateway_order_id != order_id:

            raise ValueError(
                "Payment does not belong to this order"
            )

        if (
            gateway_amount != payment.amount
            or gateway_currency != payment.currency
        ):

            raise ValueError(
                "Payment amount does not match the booking"
            )

        if gateway_status != "captured":

            raise ValueError(
                "Payment has not been captured"
            )

        # Keep gateway payment ID
        payment.razorpay_payment_id = payment_id

        payment.save(
            update_fields=[
                "razorpay_payment_id"
            ]
        )

        # 3. Validate booking again

        parsed_dates = _validate_booking_request(
            request.user,
            payment.dates,
            payment.time,
            payment.plan
        )

        try:

            with transaction.atomic():

                created_bookings = []

                for date in parsed_dates:

                    created_bookings.append(
                        Booking.objects.create(
                            user=request.user,
                            date=date,
                            time=payment.time,
                            plan=payment.plan,
                            status="active"
                        )
                    )

                payment.razorpay_payment_id = payment_id
                payment.status = "paid"
                payment.paid_at = timezone.now()

                payment.save(
                    update_fields=[
                        "razorpay_payment_id",
                        "status",
                        "paid_at"
                    ]
                )

        except IntegrityError:

            payment.razorpay_payment_id = payment_id
            payment.status = "booking_failed"

            payment.save(
                update_fields=[
                    "razorpay_payment_id",
                    "status"
                ]
            )

            if _refund_test_payment(
                client,
                payment
            ):

                return JsonResponse(
                    {
                        "error":
                            "The slot was taken by another booking. "
                            "Your Test Mode payment was refunded.",
                        "order_id": order_id,
                    },
                    status=409
                )

            return JsonResponse(
                {
                    "error":
                        "The slot was taken by another booking. "
                        "Payment was captured but could not be "
                        "refunded automatically; contact support "
                        "with the Order ID.",
                    "order_id": order_id,
                },
                status=409
            )

        return JsonResponse(
            {
                "success": True,
                "order_id": order_id,
                "payment_id": payment_id,
                "booking_ids":
                    [
                        b.id
                        for b in created_bookings
                    ],
            }
        )

    except razorpay.errors.SignatureVerificationError:

        if payment:

            payment.status = "failed"

            payment.save(
                update_fields=["status"]
            )

        return JsonResponse(
            {
                "error":
                    "Payment verification failed"
            },
            status=400
        )

    except ValueError as exc:

        if payment:

            payment.status = "booking_failed"

            payment.save(
                update_fields=["status"]
            )

            if (
                client
                and payment.razorpay_payment_id
            ):

                _refund_test_payment(
                    client,
                    payment
                )

        return JsonResponse(
            {
                "error":
                    f"Payment could not be confirmed: {exc}"
            },
            status=409
        )

    except Exception:

        if payment and payment.status == "created":

            payment.status = "failed"

            payment.save(
                update_fields=["status"]
            )

        return JsonResponse(
            {
                "error":
                    "Payment verification failed"
            },
            status=400
        )


# PAYMENT SUCCESS

@login_required
def payment_success(request):

    order_id = request.GET.get(
        "order_id"
    )

    payment = get_object_or_404(
        Payment,
        razorpay_order_id=order_id,
        user=request.user
    )

    if payment.status != "paid":

        return redirect(
            f"/payment-failed/?order_id={order_id}"
        )

    bookings = Booking.objects.filter(
        user=request.user,
        date__in=[
            str(d)
            for d in payment.dates
        ],
        time=payment.time,
        status="active"
    ).order_by("date")

    return render(
        request,
        "payment_success.html",
        {
            "payment": payment,
            "bookings": bookings,
        }
    )


# PAYMENT FAILED

@login_required
def payment_failed(request):

    order_id = request.GET.get(
        "order_id"
    )

    payment = None

    if order_id:

        payment = Payment.objects.filter(
            razorpay_order_id=order_id,
            user=request.user
        ).first()

    return render(
        request,
        "payment_failed.html",
        {
            "payment": payment
        }
    )


# ADVANCED BOOKING

@login_required
def booking_advanced(request):

    # All active bookings are needed so that the calendar
    # can show globally unavailable slots.

    bookings = Booking.objects.filter(
        status="active"
    )

    holidays = [
        {
            "date": str(h["date"]),
            "localName": h["name"]
        }
        for h in Holiday.objects.values(
            "date",
            "name"
        )
    ]

    slot_data = (
        bookings
        .values("date")
        .annotate(total=Count("id"))
    )

    slot_counts = {
        str(s["date"]): s["total"]
        for s in slot_data
    }

    context = {

        "booked_dates": json.dumps(
            [
                str(b.date)
                for b in bookings
            ]
        ),

        "booked_slots": json.dumps(
            [
                {
                    "date": str(b.date),
                    "time": b.time
                }
                for b in bookings
            ]
        ),

        "holidays": json.dumps(
            holidays
        ),

        "slot_counts": json.dumps(
            slot_counts
        ),
    }

    return render(
        request,
        "booking_advanced.html",
        context
    )


# GET HOLIDAYS

@login_required
def get_holidays(request):

    year = timezone.localdate().year

    try:

        response = requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/"
            f"{year}/IN",
            timeout=5
        )

        response.raise_for_status()

        return JsonResponse(
            response.json(),
            safe=False
        )

    except requests.RequestException:

        return JsonResponse(
            {
                "error":
                    "Holiday service unavailable"
            },
            status=502
        )


# BOOKING HISTORY

@login_required
def history(request):

    bookings = Booking.objects.filter(
        user=request.user
    ).order_by(
        "-date",
        "time"
    )

    return render(
        request,
        "history.html",
        {
            "bookings": bookings
        }
    )


# DELETE / CANCEL BOOKING

@login_required
@require_POST
def delete_booking(request, id):

    booking = get_object_or_404(
        Booking,
        id=id,
        user=request.user,
        status="active"
    )

    # Do not physically delete the booking.
    # Keep history and mark it as cancelled.
    booking.status = "cancelled"

    booking.save(
        update_fields=["status"]
    )

    return redirect("history")


# RESCHEDULE BOOKING

@login_required
@require_POST
def reschedule(request, id):

    booking = get_object_or_404(
        Booking,
        id=id,
        user=request.user,
        status="active"
    )

    try:

        data = json.loads(
            request.body
        )

        new_date = datetime.strptime(
            data.get("date"),
            "%Y-%m-%d"
        ).date()

        new_time = data.get(
            "time"
        )

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError
    ):

        return JsonResponse(
            {
                "error":
                    "Invalid date or request data"
            },
            status=400
        )

    if new_time not in ALLOWED_TIMES:

        return JsonResponse(
            {
                "error":
                    "Invalid time slot"
            },
            status=400
        )

    if new_date < timezone.localdate():

        return JsonResponse(
            {
                "error":
                    "Cannot move a booking into the past"
            },
            status=400
        )

    if Holiday.objects.filter(
        date=new_date
    ).exists():

        return JsonResponse(
            {
                "error":
                    f"{new_date} is a holiday"
            },
            status=400
        )

    # Daily capacity
    if Booking.objects.filter(
        date=new_date,
        status="active"
    ).exclude(
        id=booking.id
    ).count() >= MAX_SLOTS_PER_DAY:

        return JsonResponse(
            {
                "error":
                    f"{new_date} is fully booked"
            },
            status=400
        )

    # Slot availability
    if Booking.objects.filter(
        date=new_date,
        time=new_time,
        status="active"
    ).exclude(
        id=booking.id
    ).exists():

        return JsonResponse(
            {
                "error":
                    "Slot already booked"
            },
            status=400
        )

    # User duplicate booking
    if Booking.objects.filter(
        user=request.user,
        date=new_date,
        time=new_time,
        status="active"
    ).exclude(
        id=booking.id
    ).exists():

        return JsonResponse(
            {
                "error":
                    "You already have a booking at this time"
            },
            status=400
        )

    try:

        booking.date = new_date
        booking.time = new_time

        booking.save(
            update_fields=[
                "date",
                "time"
            ]
        )

    except IntegrityError:

        return JsonResponse(
            {
                "error":
                    "Slot was just booked by someone else"
            },
            status=409
        )

    return JsonResponse(
        {
            "success": True
        }
    )













# from django.shortcuts import render, redirect
# from django.contrib.auth import login, authenticate, logout
# from django.contrib import messages
# from django.contrib.auth.decorators import login_required
# from .models import CustomUser
# from .models import *
# import requests
# from django.http import JsonResponse
# import json
# from .models import Booking , Holiday
# from django.shortcuts import get_object_or_404
# from datetime import datetime
# from django.views.decorators.csrf import csrf_exempt
# from django.db.models import Count
# from django.db import transaction
# from django.conf import settings
# from django.utils import timezone
# from django.views.decorators.http import require_POST
# import razorpay
# from datetime import datetime
# MAX_SLOTS_PER_DAY = 5
# PLAN_PRICES = {
#     "basic": 300,
#     "custom": 2400,
#     "premium": 300,
# }


# def _validate_booking_request(user, dates, time, plan):
#     if not dates or not time:
#         raise ValueError("Missing booking data")
#     if plan not in PLAN_PRICES:
#         raise ValueError("Invalid plan")

#     try:
#         time_from, time_to = time.split(" - ")
#         t1 = datetime.strptime(time_from, "%H:%M")
#         t2 = datetime.strptime(time_to, "%H:%M")
#     except (ValueError, TypeError):
#         raise ValueError("Invalid time format")

#     if t1 >= t2:
#         raise ValueError("Invalid time range")

#     if plan == "basic" and len(dates) != 1:
#         raise ValueError("Basic allows only 1 slot at a time")
#     if plan == "custom" and len(dates) != 8:
#         raise ValueError("Custom plan requires exactly 8 slots")

#     parsed_dates = []
#     for date_str in dates:
#         try:
#             date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
#         except (TypeError, ValueError):
#             raise ValueError(f"Invalid date: {date_str}")

#         if date in parsed_dates:
#             raise ValueError(f"Duplicate date: {date}")
#         if Holiday.objects.filter(date=date).exists():
#             raise ValueError(f"{date} is a holiday")
#         if Booking.objects.filter(date=date).count() >= MAX_SLOTS_PER_DAY:
#             raise ValueError(f"{date} is fully booked")
#         if Booking.objects.filter(date=date, time=time).exists():
#             raise ValueError(f"{date} {time} already taken")
#         if Booking.objects.filter(user=user, date=date, time=time).exists():
#             raise ValueError(f"{date} already booked")

#         parsed_dates.append(date)

#     return parsed_dates


# def _booking_amount_paise(plan, date_count):
#     if plan == "custom":
#         rupees = PLAN_PRICES["custom"]
#     else:
#         rupees = PLAN_PRICES[plan] * date_count
#     return rupees * 100


# # Create your views here.
# @login_required
# def edit_profile(request):
#     user = request.user

#     if request.method == 'POST':
#         user.username = request.POST.get('username')
#         user.email = request.POST.get('email')
#         user.age = request.POST.get('age')
#         user.gender = request.POST.get('gender')

#         if request.FILES.get('image'):
#             user.image = request.FILES.get('image')

#         user.save()
#         return redirect('dashboard')
    
#     return render(request, 'edit_profile.html')

# def auth_page(request):
#     if request.user.is_authenticated:
#         return redirect('dashboard')

#     if request.method == 'POST':
#         action = request.POST.get('action')

#         # REGISTER
#         if action == 'register':
#             username = request.POST.get('username')
#             email = request.POST.get('email')
#             password = request.POST.get('password')
#             age = request.POST.get('age')
#             gender = request.POST.get('gender')
#             image = request.FILES.get('image')

#             if CustomUser.objects.filter(username=username).exists():
#                 messages.error(request, "Username already exists")
#                 return redirect('auth')
            
#             user = CustomUser.objects.create_user(
#                 username=username,
#                 email=email,
#                 password=password,
#                 age=age,
#                 gender=gender,
#                 image=image
#             )

#             messages.success(request, "Registration successful")
#             return redirect('auth')
        
#         # LOGIN
#         elif action == 'login':
#             username = request.POST.get('email') # we use username field
#             password = request.POST.get('password')

#             user = authenticate(request, username=username, password=password)

#             if user:
#                 login(request, user)
#                 return redirect('dashboard')
#             else:
#                 messages.error(request, "Invalid credentials")
            
#     return render(request, 'auth.html')

# import requests
# from datetime import datetime
# from calendar import monthrange

# @login_required(login_url='auth')
# def dashboard(request):

#     #  stats
#     total = Booking.objects.count()
#     active = Booking.objects.count()
#     monthly = Booking.objects.filter(date__month=datetime.now().month).count()
#     cancelled = 0

#     #  bookings
#     bookings = Booking.objects.values_list('date', flat=True)
#     booked_dates = [str(d) for d in bookings]


#     holidays = list(Holiday.objects.values('date', 'name'))

#     holidays = [
#         {
#             "date": str(h["date"]),
#             "localName": h["name"]
#         }
#         for h in holidays
#     ]

#     return render(request, 'dashboard.html', {
#         'total': total,
#         'active': active,
#         'monthly': monthly,
#         'cancelled': cancelled,
#         'booked_dates': booked_dates,
#         'holidays': holidays
#     })

# @login_required
# def logout_page(request):
#     logout(request)
#     return redirect('auth')


# # booking system

# @login_required
# def book_slot(request):
#     if request.method == 'POST':
#         date = request.POST.get('date')
#         time = request.POST.get('time')

#         # prevent duplicate booking 
#         if Booking.objects.filter(date=date, time=time).exists():
#             return render(request, 'booking.html', {
#                 'error': "Slots already booked"
#             })
        
#         Booking.objects.create(
#             user=request.user,
#             date=date,
#             time=time
#             # plan=plan  # ADD THIS
#         )

#         return render(request, 'booking.html', {
#             'success': "Booking successful"
#         })
    
#     return render(request, 'booking.html')



# # SAVE BOOKING

# @login_required
# @require_POST
# def save_booking(request):
#     # Legacy direct-booking endpoint. New UI uses Razorpay payment first.
#     try:
#         data = json.loads(request.body)
#         dates = data.get("dates", [])
#         time = data.get("time")
#         plan = data.get("plan")
#         parsed_dates = _validate_booking_request(request.user, dates, time, plan)
#         with transaction.atomic():
#             for date in parsed_dates:
#                 Booking.objects.create(user=request.user, date=date, time=time, plan=plan)
#         return JsonResponse({"success": True})
#     except ValueError as exc:
#         return JsonResponse({"error": str(exc)}, status=400)
#     except Exception:
#         return JsonResponse({"error": "Unable to save booking"}, status=500)


# @login_required
# @require_POST
# def create_payment_order(request):
#     try:
#         data = json.loads(request.body)
#         dates = data.get("dates", [])
#         time = data.get("time")
#         plan = data.get("plan")
#         parsed_dates = _validate_booking_request(request.user, dates, time, plan)

#         key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
#         key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
#         if not key_id or not key_secret:
#             return JsonResponse({
#                 "error": "Razorpay Test Mode is not configured. Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to your environment."
#             }, status=503)

#         client = razorpay.Client(auth=(key_id, key_secret))
#         amount = _booking_amount_paise(plan, len(parsed_dates))
#         receipt = f"chesshub-{request.user.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"[-40:]
#         order = client.order.create({
#             "amount": amount,
#             "currency": "INR",
#             "receipt": receipt,
#             "notes": {
#                 "user_id": str(request.user.id),
#                 "plan": plan,
#                 "booking_time": time,
#             },
#         })

#         Payment.objects.create(
#             user=request.user,
#             razorpay_order_id=order["id"],
#             amount=amount,
#             plan=plan,
#             dates=[d.isoformat() for d in parsed_dates],
#             time=time,
#         )

#         return JsonResponse({
#             "key": key_id,
#             "order_id": order["id"],
#             "amount": amount,
#             "currency": "INR",
#             "name": "ChessHub",
#             "description": f"{plan.title()} booking",
#             "prefill": {
#                 "name": request.user.get_full_name() or request.user.username,
#                 "email": request.user.email,
#             },
#         })
#     except ValueError as exc:
#         return JsonResponse({"error": str(exc)}, status=400)
#     except Exception:
#         return JsonResponse({"error": "Unable to create Razorpay order"}, status=500)


# @login_required
# @require_POST
# def verify_payment(request):
#     payment = None
#     try:
#         data = json.loads(request.body)
#         order_id = data.get("razorpay_order_id")
#         payment_id = data.get("razorpay_payment_id")
#         signature = data.get("razorpay_signature")

#         if not order_id or not payment_id or not signature:
#             return JsonResponse({"error": "Incomplete payment response"}, status=400)

#         payment = get_object_or_404(
#             Payment, razorpay_order_id=order_id, user=request.user
#         )

#         if payment.status == "paid":
#             return JsonResponse({"success": True, "order_id": order_id})

#         key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
#         key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
#         if not key_id or not key_secret:
#             return JsonResponse({"error": "Razorpay is not configured"}, status=503)

#         client = razorpay.Client(auth=(key_id, key_secret))
#         client.utility.verify_payment_signature({
#             "razorpay_order_id": order_id,
#             "razorpay_payment_id": payment_id,
#             "razorpay_signature": signature,
#         })

#         parsed_dates = _validate_booking_request(
#             request.user, payment.dates, payment.time, payment.plan
#         )

#         with transaction.atomic():
#             created_bookings = []
#             for date in parsed_dates:
#                 created_bookings.append(Booking.objects.create(
#                     user=request.user,
#                     date=date,
#                     time=payment.time,
#                     plan=payment.plan,
#                 ))

#             payment.razorpay_payment_id = payment_id
#             payment.status = "paid"
#             payment.paid_at = timezone.now()
#             payment.save(update_fields=[
#                 "razorpay_payment_id", "status", "paid_at"
#             ])

#         return JsonResponse({
#             "success": True,
#             "order_id": order_id,
#             "payment_id": payment_id,
#             "booking_ids": [b.id for b in created_bookings],
#         })

#     except razorpay.errors.SignatureVerificationError:
#         if payment:
#             payment.status = "failed"
#             payment.save(update_fields=["status"])
#         return JsonResponse({"error": "Payment verification failed"}, status=400)
#     except ValueError as exc:
#         if payment:
#             payment.status = "booking_failed"
#             payment.save(update_fields=["status"])
#         return JsonResponse({
#             "error": f"Payment received, but booking could not be confirmed: {exc}"
#         }, status=409)
#     except Exception:
#         return JsonResponse({"error": "Payment verification failed"}, status=400)


# @login_required
# def payment_success(request):
#     order_id = request.GET.get("order_id")
#     payment = get_object_or_404(Payment, razorpay_order_id=order_id, user=request.user)
#     if payment.status != "paid":
#         return redirect("payment_failed")

#     dates = [str(d) for d in payment.dates]
#     bookings = Booking.objects.filter(
#         user=request.user, date__in=dates, time=payment.time, plan=payment.plan
#     ).order_by("date")
#     return render(request, "payment_success.html", {
#         "payment": payment,
#         "bookings": bookings,
#     })


# @login_required
# def payment_failed(request):
#     order_id = request.GET.get("order_id")
#     payment = None
#     if order_id:
#         payment = Payment.objects.filter(
#             razorpay_order_id=order_id, user=request.user
#         ).first()
#     return render(request, "payment_failed.html", {"payment": payment})


# # ADVANCE BOOKING
# @login_required
# def booking_advanced(request):
#     user = request.user

#     holidays = Holiday.objects.all()

#     # USER BOOKINGS
#     # IMPORTANT: All BOOKINGS (not only user)

#     bookings = Booking.objects.all()

#     booked_dates = [str(b.date) for b in bookings]
#     booked_slots = [
#         {"date": str(b.date), "time": b.time}
#         for b in bookings
#     ]

#     # HOLIDAYS
#     holidays = list(Holiday.objects.values('date', 'name'))

#     # convert for JS
#     holidays_json = json.dumps([
#         {
#             "date": str(h["date"]),
#             "localName": h["name"]
#         } 
#         for h in holidays
#     ])

#     # SLOT COUNT PER DAY(IMP)
#     slot_data = Booking.objects.values('date').annotate(total=Count('id'))

#     slot_counts = {
#         str(s['date']): s['total']
#         for s in slot_data
#     }

#     # "max_slots": MAX_SLOTS_PER_DAY,

#     context = {
#         "booked_dates": json.dumps(booked_dates),
#         "booked_slots": json.dumps(booked_slots),
#         "holidays": holidays_json,
#         "slot_counts": json.dumps(slot_counts),
#         # "max_slots": MAX_SLOTS_PER_DAY,
#     }

#     return render(request, "booking_advanced.html", context)


# @login_required
# def get_holidays(request):
#     url = "https://date.nager.at/api/v3/PublicHolidays/2026/IN"
#     response = requests.get(url)
#     return response.json()


# @login_required
# def history(request):
#     bookings = Booking.objects.filter(user=request.user)
#     return render(request, 'history.html', {'bookings': bookings})


# @login_required
# @require_POST
# def delete_booking(request, id):
#     booking = get_object_or_404(Booking, id=id, user=request.user)
#     booking.delete()
#     return redirect('history')



# @login_required
# def reschedule(request, id):

#     booking = get_object_or_404(Booking, id=id, user=request.user)

#     if request.method == "POST":
#         try:
#             data = json.loads(request.body)
#             new_date = data.get("date")
#             new_time = data.get("time")
#             new_date = datetime.strptime(new_date, "%Y-%m-%d").date()
#         except (TypeError, ValueError, json.JSONDecodeError):
#             return JsonResponse({"error": "Invalid date or request data"}, status=400)

#         if not new_time:
#             return JsonResponse({"error": "Time is required"}, status=400)

#         if Holiday.objects.filter(date=new_date).exists():
#             return JsonResponse({"error": f"{new_date} is a holiday"}, status=400)

#         # Exclude the booking being moved from the daily count and slot check.
#         if Booking.objects.filter(date=new_date).exclude(id=booking.id).count() >= MAX_SLOTS_PER_DAY:
#             return JsonResponse({"error": f"{new_date} is fully booked"}, status=400)

#         if Booking.objects.filter(date=new_date, time=new_time).exclude(id=booking.id).exists():
#             return JsonResponse({"error": "Slot already booked"}, status=400)

#         if Booking.objects.filter(user=request.user, date=new_date, time=new_time).exclude(id=booking.id).exists():
#             return JsonResponse({"error": "You already have a booking at this time"}, status=400)

#         booking.date = new_date
#         booking.time = new_time
#         booking.save(update_fields=["date", "time"])

#         return JsonResponse({"success": True})

#     return JsonResponse({"error": "Invalid request"})










# from django.shortcuts import render, redirect
# from django.contrib.auth import login, authenticate, logout
# from django.contrib import messages
# from django.contrib.auth.decorators import login_required
# from .models import CustomUser
# from .models import *
# import requests
# from django.http import JsonResponse
# import json
# from .models import Booking , Holiday
# from django.shortcuts import get_object_or_404
# from datetime import datetime
# from django.views.decorators.csrf import csrf_exempt
# from django.db.models import Count
# from datetime import datetime
# MAX_SLOTS_PER_DAY = 5


# # Create your views here.
# @login_required
# def edit_profile(request):
#     user = request.user

#     if request.method == 'POST':
#         user.username = request.POST.get('username')
#         user.email = request.POST.get('email')
#         user.age = request.POST.get('age')
#         user.gender = request.POST.get('gender')

#         if request.FILES.get('image'):
#             user.image = request.FILES.get('image')

#         user.save()
#         return redirect('dashboard')
    
#     return render(request, 'edit_profile.html')

# def auth_page(request):
#     if request.user.is_authenticated:
#         return redirect('dashboard')

#     if request.method == 'POST':
#         action = request.POST.get('action')

#         # REGISTER
#         if action == 'register':
#             username = request.POST.get('username')
#             email = request.POST.get('email')
#             password = request.POST.get('password')
#             age = request.POST.get('age')
#             gender = request.POST.get('gender')
#             image = request.FILES.get('image')

#             if CustomUser.objects.filter(username=username).exists():
#                 messages.error(request, "Username already exists")
#                 return redirect('auth')
            
#             user = CustomUser.objects.create_user(
#                 username=username,
#                 email=email,
#                 password=password,
#                 age=age,
#                 gender=gender,
#                 image=image
#             )

#             messages.success(request, "Registration successful")
#             return redirect('auth')
        
#         # LOGIN
#         elif action == 'login':
#             username = request.POST.get('email') # we use username field
#             password = request.POST.get('password')

#             user = authenticate(request, username=username, password=password)

#             if user:
#                 login(request, user)
#                 return redirect('dashboard')
#             else:
#                 messages.error(request, "Invalid credentials")
            
#     return render(request, 'auth.html')

# import requests
# from datetime import datetime
# from calendar import monthrange

# @login_required(login_url='auth')
# def dashboard(request):

#     #  stats
#     total = Booking.objects.count()
#     active = Booking.objects.count()
#     monthly = Booking.objects.filter(date__month=datetime.now().month).count()
#     cancelled = 0

#     #  bookings
#     bookings = Booking.objects.values_list('date', flat=True)
#     booked_dates = [str(d) for d in bookings]


#     holidays = list(Holiday.objects.values('date', 'name'))

#     holidays = [
#         {
#             "date": str(h["date"]),
#             "localName": h["name"]
#         }
#         for h in holidays
#     ]

#     return render(request, 'dashboard.html', {
#         'total': total,
#         'active': active,
#         'monthly': monthly,
#         'cancelled': cancelled,
#         'booked_dates': booked_dates,
#         'holidays': holidays
#     })

# @login_required
# def logout_page(request):
#     logout(request)
#     return redirect('auth')


# # booking system

# @login_required
# def book_slot(request):
#     if request.method == 'POST':
#         date = request.POST.get('date')
#         time = request.POST.get('time')

#         # prevent duplicate booking 
#         if Booking.objects.filter(date=date, time=time).exists():
#             return render(request, 'booking.html', {
#                 'error': "Slots already booked"
#             })
        
#         Booking.objects.create(
#             user=request.user,
#             date=date,
#             time=time
#             # plan=plan  # ADD THIS
#         )

#         return render(request, 'booking.html', {
#             'success': "Booking successful"
#         })
    
#     return render(request, 'booking.html')



# # SAVE BOOKING

# @login_required
# def save_booking(request):

#     if request.method != "POST":
#         return JsonResponse({"error": "Invalid request"}, status=400)

#     try:
#         data = json.loads(request.body)

#         dates = data.get("dates", [])
#         time = data.get("time")
#         plan = data.get("plan") 

#         if not dates or not time:
#             return JsonResponse({"error": "Missing data"}, status=400)

#         user = request.user

#         # TIME VALIDATION
#         time_from, time_to = time.split(" - ")
#         t1 = datetime.strptime(time_from, "%H:%M")
#         t2 = datetime.strptime(time_to, "%H:%M")

#         if t1 >= t2:
#             return JsonResponse({"error": "Invalid time range"}, status=400)
        
#         # PLAN LOGIC 

#         # USER TOTAL LIMIT (PREMIUM = 8) 

#         if plan == "basic":
#             if len(dates) > 1:
#                 return JsonResponse({"error": "Basic allows only 1 slot at a time"}, status=400)
                
#         elif plan == "custom":

#             # ✅ must select exactly 8 slots in THIS request only
#             if len(dates) != 8:
#                 return JsonResponse({
#                     "error": "Custom plan requires exactly 8 slots"
#                 }, status=400)
            
            
#         # premium -> NO LIMIT

#         # Booking loop
        
#         for date_str in dates:
#             date = datetime.strptime(date_str, "%Y-%m-%d").date()

#             # HOLIDAY
#             if Holiday.objects.filter(date=date).exists():
#                 return JsonResponse({"error": f"{date} is a holiday"}, status=400)

#             #  DAILY LIMIT (THIS WAS WRONG BEFORE)
#             # PER DAY LIMIT(5)
#             day_count = Booking.objects.filter(date=date).count()

#             if day_count >= MAX_SLOTS_PER_DAY:
#                 return JsonResponse({"error": f"{date} is fully booked"}, status=400)

#             #  SAME TIME SLOT CHECK
#             if Booking.objects.filter(date=date, time=time).exists():
#                 return JsonResponse({"error": f"{date} {time} already taken"}, status=400)

#             #  USER DUPLICATE
#             if Booking.objects.filter(user=user, date=date, time=time).exists():
#                 return JsonResponse({"error": f"{date} already booked"}, status=400)

#             # SAVE
#             Booking.objects.create(
#                 user=user,
#                 date=date,
#                 time=time,
#                 plan=plan   
#             )

#         return JsonResponse({"success": True})

#     except Exception as e:
#         return JsonResponse({"error": str(e)}, status=500)

    
# # ADVANCE BOOKING
# @login_required
# def booking_advanced(request):
#     user = request.user

#     holidays = Holiday.objects.all()

#     # USER BOOKINGS
#     # IMPORTANT: All BOOKINGS (not only user)

#     bookings = Booking.objects.all()

#     booked_dates = [str(b.date) for b in bookings]
#     booked_slots = [
#         {"date": str(b.date), "time": b.time}
#         for b in bookings
#     ]

#     # HOLIDAYS
#     holidays = list(Holiday.objects.values('date', 'name'))

#     # convert for JS
#     holidays_json = json.dumps([
#         {
#             "date": str(h["date"]),
#             "localName": h["name"]
#         } 
#         for h in holidays
#     ])

#     # SLOT COUNT PER DAY(IMP)
#     slot_data = Booking.objects.values('date').annotate(total=Count('id'))

#     slot_counts = {
#         str(s['date']): s['total']
#         for s in slot_data
#     }

#     # "max_slots": MAX_SLOTS_PER_DAY,

#     context = {
#         "booked_dates": json.dumps(booked_dates),
#         "booked_slots": json.dumps(booked_slots),
#         "holidays": holidays_json,
#         "slot_counts": json.dumps(slot_counts),
#         # "max_slots": MAX_SLOTS_PER_DAY,
#     }

#     return render(request, "booking_advanced.html", context)


# @login_required
# def get_holidays():
#     url = "https://date.nager.at/api/v3/PublicHolidays/2026/IN"
#     response = requests.get(url)
#     return response.json()


# @login_required
# def history(request):
#     bookings = Booking.objects.filter(user=request.user)
#     return render(request, 'history.html', {'bookings': bookings})


# @login_required
# def delete_booking(request, id):
#     booking = get_object_or_404(Booking, id=id)
#     booking.delete()
#     return redirect('history')



# @login_required
# def reschedule(request, id):

#     booking = get_object_or_404(Booking, id=id, user=request.user)

#     if request.method == "POST":
#         data = json.loads(request.body)

#         new_date = data.get("date")
#         new_time = data.get("time")

#         # VALIDATION
#         if Booking.objects.filter(date=new_date, time=new_time).exists():
#             return JsonResponse({"error": "Slot already booked"})

#         booking.date = new_date
#         booking.time = new_time
#         booking.save()

#         return JsonResponse({"success": True})

#     return JsonResponse({"error": "Invalid request"})
