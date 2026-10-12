# ChessHub setup

## 1. Create the environment

```bash
python -m venv env
env\\Scripts\\activate
pip install -r requirements.txt
```

## 2. Configure environment variables

Copy `.env.example` to `.env` and set the Django, MySQL, and Razorpay **Test Mode** credentials.

Never commit `.env`.

## 3. Apply migrations

```bash
python manage.py migrate
python manage.py check
```

## 4. Run

```bash
python manage.py runserver
```

## Razorpay flow

The server validates the booking and calculates the amount before creating a Razorpay Test Mode Order. After Checkout, it verifies the Razorpay signature and then fetches the payment to confirm the order ID, amount, currency, and captured status. Only after those checks are bookings created.

If a captured Test Mode payment cannot be matched to available slots, the server attempts a refund and records the payment outcome.

Never expose `RAZORPAY_KEY_SECRET` in browser JavaScript.
