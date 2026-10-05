import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()  # reads .env into environment variables

username     = os.getenv("user")
userpassword = os.getenv("password")
hostname    = os.getenv("host")
port     = os.getenv("port")
dbname   = os.getenv("database")

url = f"postgresql+psycopg2://{username}:{userpassword}@{hostname}:{port}/{dbname}"
engine = create_engine(url)

if __name__ == "__main__":
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        print(result.scalar())