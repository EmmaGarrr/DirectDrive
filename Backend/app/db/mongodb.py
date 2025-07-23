from pymongo import MongoClient
from app.core.config import settings

# Improved MongoDB client with connection pooling
client = MongoClient(
    settings.MONGODB_URI,
    maxPoolSize=100,
    minPoolSize=10,
    maxIdleTimeMS=30000,
    waitQueueTimeoutMS=5000
)
db = client[settings.DATABASE_NAME]