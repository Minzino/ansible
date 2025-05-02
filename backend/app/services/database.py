# In-memory storage for cluster status (replace with DB/file later)
cluster_status_db = {}

def get_status_db():
    """Returns the in-memory status database."""
    return cluster_status_db 