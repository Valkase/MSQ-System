import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL

from app_paths import env_file_path

# Frozen build: %APPDATA%\HealthCenterSystem\.env. From source: <project>/.env.
load_dotenv(env_file_path())

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Built with URL.create so special characters in the password (@, :, /, %, ...)
# are escaped correctly instead of corrupting the connection string.
DATABASE_URL = URL.create(
    "postgresql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT) if DB_PORT else None,
    database=DB_NAME,
).render_as_string(hide_password=False)
