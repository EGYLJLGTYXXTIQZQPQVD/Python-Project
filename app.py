# --- START OF FILE app.py ---

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Consider using a production-ready server like Gunicorn or Waitress
    # instead of app.run() in production.
    # For development:
    app.run(debug=app.config.get('DEBUG', False), # Use config setting for debug
            host='0.0.0.0', # Bind to all interfaces if needed (e.g., Docker)
            port=5000)
# --- END OF FILE app.py ---