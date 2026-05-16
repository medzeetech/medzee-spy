from app.clients.supabase import get_supabase_client


def get_db():
    return get_supabase_client()
