# Edifyce

A web-based formal proof assistant built with Django. Edifyce lets users define formal systems, write proofs, and have them mechanically verified.

## Features

- Define custom formal systems with axioms and inference rules
- Write and verify formal proofs step-by-step
- Import and build on existing formal systems
- Google OAuth authentication
- Collaborative proof sharing

## Tech Stack

- **Backend:** Django 3.2
- **Auth:** django-allauth with Google OAuth
- **Database:** SQLite (development) / MySQL (production)
- **Frontend:** Django templates, CSS

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/jamesherring/edifyce.git
   cd edifyce
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

5. **Run migrations**
   ```bash
   python manage.py migrate
   ```

6. **Collect static files**
   ```bash
   python manage.py collectstatic
   ```

7. **Start the development server**
   ```bash
   python manage.py runserver
   ```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
