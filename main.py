import os
from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import re
from markupsafe import Markup, escape
from dotenv import load_dotenv
from db import get_db_connection, init_db

app = Flask(__name__)
load_dotenv()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default")

init_db()

# add mention -> profile link filter
def mentionify(text):
    if not text:
        return Markup("")
    def repl(m):
        uname = m.group(1)
        # escape display and username; url_for will build proper link
        href = url_for("profile", username=uname)
        return Markup(f'<a href="{escape(href)}" class="text-blue-500 hover:underline">@{escape(uname)}</a>')
    # replace @username (letters, digits, underscore)
    result = re.sub(r'@([A-Za-z0-9_]+)', repl, escape(text))
    return Markup(result)

app.jinja_env.filters['mentionify'] = mentionify

# -----------------------------------------------------
# Routes
# -----------------------------------------------------

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))

    # pagination
    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except:
        page = 1
    PAGE_SIZE = 10
    offset = (page - 1) * PAGE_SIZE

    conn = get_db_connection()
    c = conn.cursor()

    # Main feed: self + followed users (with pagination)
    c.execute("""
        SELECT t.id, t.user_id, t.content, t.timestamp, u.username,
        (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id) AS like_count,
        EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = ?) AS liked
        FROM tweets t
        JOIN users u ON t.user_id = u.id
        LEFT JOIN followers f ON f.followee_id = t.user_id
        WHERE t.user_id = ? OR f.follower_id = ?
        GROUP BY t.id
        ORDER BY t.timestamp DESC
        LIMIT ? OFFSET ?
    """, (session["user_id"], session["user_id"], session["user_id"], PAGE_SIZE, offset))

    tweets = c.fetchall()

    tweet_list = []

    for t in tweets:
        c.execute("""
            SELECT r.content, r.timestamp, u.username
            FROM replies r
            JOIN users u ON r.user_id = u.id
            WHERE r.tweet_id = ?
            ORDER BY r.timestamp ASC
        """, (t["id"],))

        replies = c.fetchall()
        tweet_list.append({"tweet": t, "replies": replies})

    conn.close()
    return render_template("index.html", tweets=tweet_list, page=page)


# -----------------------------------------------------
# Authentication
# -----------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        display_name = request.form.get("display_name", "").strip()
        password = generate_password_hash(request.form["password"])

        conn = get_db_connection()
        c = conn.cursor()

        try:
            c.execute("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)",
                      (username, password, display_name))
            conn.commit()
        except:
            conn.close()
            return "Username already exists."

        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        else:
            return "Invalid login."

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------------------------------------
# Tweeting
# -----------------------------------------------------

@app.route("/tweet", methods=["POST"])
def tweet():
    if "user_id" not in session:
        return redirect(url_for("login"))

    content = request.form["content"]

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        INSERT INTO tweets (user_id, content, timestamp)
        VALUES (?, ?, ?)
    """, (session["user_id"], content, datetime.now()))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# -----------------------------------------------------
# Replies
# -----------------------------------------------------

@app.route("/reply/<int:tweet_id>", methods=["POST"])
def reply(tweet_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    content = request.form["content"]

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        INSERT INTO replies (tweet_id, user_id, content, timestamp)
        VALUES (?, ?, ?, ?)
    """, (tweet_id, session["user_id"], content, datetime.now()))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# -----------------------------------------------------
# Likes
# -----------------------------------------------------

@app.route("/like/<int:tweet_id>")
def like(tweet_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()

    # Check if already liked
    c.execute("""
        SELECT 1 FROM likes WHERE tweet_id = ? AND user_id = ?
    """, (tweet_id, session["user_id"]))

    already = c.fetchone()

    if already:
        c.execute("""
            DELETE FROM likes WHERE tweet_id = ? AND user_id = ?
        """, (tweet_id, session["user_id"]))
    else:
        c.execute("""
            INSERT INTO likes (tweet_id, user_id)
            VALUES (?, ?)
        """, (tweet_id, session["user_id"]))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# -----------------------------------------------------
# User list (follow suggestions)
# -----------------------------------------------------

@app.route("/users")
def users():
    # require login
    if "user_id" not in session:
        return redirect(url_for("login"))

    # render the search UI (search performed via /search)
    return render_template("search.html", query="", results={"tweets": [], "users": []})

# -----------------------------------------------------
# Follow / Unfollow
# -----------------------------------------------------

@app.route("/follow/<username>", methods=["GET", "POST"])
def follow(username):
    # require login
    if "user_id" not in session:
        return redirect(url_for("login"))

    # determine where to go back to after following
    redirect_target = request.referrer or url_for("users")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    target = c.fetchone()
    if not target:
        conn.close()
        return render_template("user_not_found.html", username=username)

    # Prevent following yourself
    if target["id"] == session["user_id"]:
        conn.close()
        return redirect(redirect_target)

    # Check if already following
    c.execute("SELECT 1 FROM followers WHERE follower_id = ? AND followee_id = ?",
              (session["user_id"], target["id"]))
    if c.fetchone():
        conn.close()
        return redirect(redirect_target)

    try:
        c.execute("""
            INSERT INTO followers (follower_id, followee_id)
            VALUES (?, ?)
        """, (session["user_id"], target["id"]))
        conn.commit()
    except sqlite3.IntegrityError:
        # unique constraint / race - ignore
        pass
    finally:
        conn.close()

    return redirect(redirect_target)


@app.route("/unfollow/<username>", methods=["GET", "POST"])
def unfollow(username):
    # require login
    if "user_id" not in session:
        return redirect(url_for("login"))

    # determine where to go back to after unfollowing
    redirect_target = request.referrer or url_for("users")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    target = c.fetchone()
    if not target:
        conn.close()
        return render_template("user_not_found.html", username=username)

    # Prevent unfollowing yourself (no-op)
    if target["id"] == session["user_id"]:
        conn.close()
        return redirect(redirect_target)

    c.execute("""
        DELETE FROM followers
        WHERE follower_id = ? AND followee_id = ?
    """, (session["user_id"], target["id"]))

    conn.commit()
    conn.close()

    return redirect(redirect_target)

# -----------------------------------------------------
# Profile Page
# -----------------------------------------------------

@app.route("/user/<username>")
def profile(username):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT id, username, bio, display_name FROM users WHERE username = ?
    """, (username,))
    user = c.fetchone()

    if not user:
        conn.close()
        return render_template("user_not_found.html", username=username)

    # use a safe viewer id (avoid KeyError when not logged in)
    viewer_id = session.get("user_id", -1)

    # Tweets by this user
    c.execute("""
        SELECT t.id, t.content, t.timestamp,
        (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id) AS like_count,
        EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = ?) AS liked
        FROM tweets t
        WHERE user_id = ?
        ORDER BY timestamp DESC
    """, (viewer_id, user["id"]))

    tweets = c.fetchall()

    # Count followers / following
    c.execute("SELECT COUNT(*) FROM followers WHERE followee_id = ?", (user["id"],))
    followers = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM followers WHERE follower_id = ?", (user["id"],))
    following = c.fetchone()[0]

    # Check if viewer follows them (viewer_id may be -1 -> not following)
    c.execute("""
        SELECT 1 FROM followers
        WHERE follower_id = ? AND followee_id = ?
    """, (viewer_id, user["id"]))
    is_following = c.fetchone() is not None

    conn.close()

    return render_template(
        "profile.html",
        profile_user=user,
        tweets=tweets,
        followers=followers,
        following=following,
        is_following=is_following
    )

# -----------------------------------------------------
# Bio Editing
# -----------------------------------------------------

@app.route("/edit_bio", methods=["POST"])
def edit_bio():
    new_bio = request.form["bio"]
    new_display = request.form.get("display_name", "").strip()

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("UPDATE users SET bio = ?, display_name = ? WHERE id = ?", (new_bio, new_display, session["user_id"]))
    conn.commit()
    conn.close()

    return redirect(url_for("profile", username=session["username"]))


# -----------------------------------------------------
# Edit and Delete Tweets
# -----------------------------------------------------

@app.route("/edit_tweet/<int:tweet_id>", methods=["GET", "POST"])
def edit_tweet(tweet_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id, user_id, content FROM tweets WHERE id = ?", (tweet_id,))
    tweet = c.fetchone()
    if not tweet:
        conn.close()
        return "Tweet not found."

    # ownership check
    if tweet["user_id"] != session["user_id"]:
        conn.close()
        return "Unauthorized."

    if request.method == "POST":
        new_content = request.form.get("content", "").strip()
        if not new_content:
            conn.close()
            return "Content cannot be empty."

        c.execute("UPDATE tweets SET content = ?, timestamp = ? WHERE id = ?",
                  (new_content, datetime.now(), tweet_id))
        conn.commit()
        conn.close()
        # always return to main feed after saving
        return redirect(url_for("index"))

    conn.close()
    return render_template("edit_tweet.html", tweet=tweet)


@app.route("/delete_tweet/<int:tweet_id>", methods=["POST"])
def delete_tweet(tweet_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    # where to return after delete
    redirect_target = request.referrer or url_for("profile", username=session["username"])

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT user_id FROM tweets WHERE id = ?", (tweet_id,))
    t = c.fetchone()
    if not t:
        conn.close()
        return "Tweet not found."

    if t["user_id"] != session["user_id"]:
        conn.close()
        return "Unauthorized."

    # delete likes, replies, then tweet
    c.execute("DELETE FROM likes WHERE tweet_id = ?", (tweet_id,))
    c.execute("DELETE FROM replies WHERE tweet_id = ?", (tweet_id,))
    c.execute("DELETE FROM tweets WHERE id = ?", (tweet_id,))

    conn.commit()
    conn.close()

    return redirect(redirect_target)

# -----------------------------------------------------
# Search
# -----------------------------------------------------

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("search.html", query=q, results={"tweets": [], "users": []})

    like_q = f"%{q}%"
    conn = get_db_connection()
    c = conn.cursor()

    # search tweets
    c.execute("""
        SELECT t.id, t.content, t.timestamp, u.username,
        (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id) AS like_count
        FROM tweets t
        JOIN users u ON t.user_id = u.id
        WHERE t.content LIKE ?
        ORDER BY t.timestamp DESC
        LIMIT 50
    """, (like_q,))
    tweets = c.fetchall()

    # search users
    c.execute("""
        SELECT id, username, bio FROM users
        WHERE username LIKE ? OR bio LIKE ?
        LIMIT 50
    """, (like_q, like_q))
    users_found = c.fetchall()

    conn.close()
    return render_template("search.html", query=q, results={"tweets": tweets, "users": users_found})

# -----------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
