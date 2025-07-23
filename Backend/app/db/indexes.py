from app.db.mongodb import db

def create_indexes():
    # File collection indexes
    db.files.create_index("owner_id")
    db.files.create_index("batch_id")
    db.files.create_index([("owner_id", 1), ("upload_date", -1)])
    db.files.create_index("gdrive_account_id")
    
    # Batch collection indexes
    db.batches.create_index("owner_id")
    
    # User collection indexes
    db.users.create_index("email", unique=True)
    
    print("All indexes created successfully")

if __name__ == "__main__":
    create_indexes()
