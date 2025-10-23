from flask import Flask, request, render_template_string, redirect, url_for, session
import re

app = Flask(__name__)
app.secret_key = "my_secret_key_123"  # তোমার নিজের secret key দাও

# ========== ADMIN LOGIN ========== #
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "12345"

# ========== SIMPLE HTML TEMPLATES ========== #
login_page = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Login</title>
  <style>
    body {font-family: Arial; background: #121212; color: white; text-align: center;}
    form {margin-top: 150px;}
    input {padding: 10px; margin: 5px; border-radius: 5px;}
    button {padding: 10px 20px; border: none; background: #007bff; color: white; border-radius: 5px;}
  </style>
</head>
<body>
  <h2>🔐 Admin Login</h2>
  <form method="post" action="/login">
    <input type="text" name="username" placeholder="Username" required><br>
    <input type="password" name="password" placeholder="Password" required><br>
    <button type="submit">Login</button>
  </form>
</body>
</html>
"""

admin_panel = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Panel</title>
  <style>
    body {font-family: Arial; background: #121212; color: white; text-align: center;}
    input {padding: 10px; width: 50%; margin: 10px; border-radius: 5px;}
    button {padding: 10px 20px; border: none; background: #28a745; color: white; border-radius: 5px;}
    a {color: #ff4757; text-decoration: none;}
  </style>
</head>
<body>
  <h2>⚙️ Direct Link Generator</h2>
  <form method="post" action="/generate">
    <input type="text" name="url" placeholder="Enter your link here..." required><br>
    <button type="submit">Generate Direct Link</button>
  </form>
  {% if link %}
    <h3>✅ Direct Link:</h3>
    <p><a href="{{ link }}" target="_blank">{{ link }}</a></p>
  {% endif %}
  <br><a href="/logout">Logout</a>
</body>
</html>
"""

# ========== DIRECT LINK GENERATOR LOGIC ========== #
def generate_direct_link(url):
    # Google Drive Link
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    # Dropbox Link
    if "dropbox.com" in url:
        return url.replace("www.dropbox.com", "dl.dropboxusercontent.com")

    # Mediafire Link
    if "mediafire.com" in url:
        return url.replace("mediafire.com/file/", "download.mediafire.com/")

    # Default (no match)
    return url

# ========== ROUTES ========== #
@app.route("/")
def home():
    if "logged_in" in session:
        return redirect(url_for("admin"))
    return render_template_string(login_page)

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["logged_in"] = True
        return redirect(url_for("admin"))
    return "<h3 style='color:red;'>❌ Wrong username or password</h3><a href='/'>Go Back</a>"

@app.route("/admin")
def admin():
    if "logged_in" not in session:
        return redirect("/")
    return render_template_string(admin_panel)

@app.route("/generate", methods=["POST"])
def generate():
    if "logged_in" not in session:
        return redirect("/")
    url = request.form.get("url")
    link = generate_direct_link(url)
    return render_template_string(admin_panel, link=link)

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/")

# ========== RENDER SERVER CHECK ========== #
@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
