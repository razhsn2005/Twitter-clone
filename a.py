import sqlite3

conn = sqlite3.connect("twitter_clone.db")
c = conn.cursor()

c.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")

conn.commit()
conn.close()

print("Done.")
