

# ChessHub

ChessHub is a Django-based chess booking application with Razorpay payment integration.

## Features

- User registration and authentication
- User profiles
- Booking dates and time slots
- Razorpay payment integration
- Payment verification
- Booking dashboard

## Technologies

- Python
- Django
- MySQL
- HTML, CSS, JavaScript
- Razorpay

## Requirements

- Python
- MySQL
- Git

## Local Setup

1. Clone this repository.
2. Create and activate a Python virtual environment.
3. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Create a local `.env` file using `.env.example` as a reference.
5. Configure the environment variables required by your project.
6. Create the MySQL database and configure the connection.
7. Apply migrations:

   ```bash
   python manage.py migrate
   ```

8. Start the development server:

   ```bash
   python manage.py runserver
   ```

## Security

- Never commit `.env` or real credentials.
- Use test payment credentials during development.
- Configure HTTPS and production security settings before deployment.

## License

No license has been specified yet.


