import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()  # reads .env into environment variables

user     = os.getenv("user")
password = os.getenv("password")
host     = os.getenv("host")
port     = os.getenv("port")
dbname   = os.getenv("database")

url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
engine = create_engine(url)

if __name__ == "__main__":
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        print(result.scalar())