import sqlite3

def get_db_connection():
    conn = sqlite3.connect("twitter_clone.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT ''
        )
        ''')

    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            timestamp DATETIME,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id INTEGER,
            user_id INTEGER,
            content TEXT,
            timestamp DATETIME,
            FOREIGN KEY(tweet_id) REFERENCES tweets(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(tweet_id) REFERENCES tweets(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS followers (
            follower_id INTEGER,
            followee_id INTEGER,
            UNIQUE(follower_id, followee_id)
        )
    """)

    # Only add 'bio' column if it doesn't already exist (prevents duplicate column error)
    c.execute("PRAGMA table_info(users)")
    cols = [row["name"] if isinstance(row, dict) or hasattr(row, "keys") else row[1] for row in c.fetchall()]
    if "bio" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
    # add display_name if missing
    if "display_name" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ''")

    conn.commit()
    conn.close()