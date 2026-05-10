from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
import hashlib, os, time, secrets, random, re, html
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import bleach

load_dotenv()

# ── Auto-detect database: PostgreSQL on Render, MySQL locally ──
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_POSTGRES  = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2, psycopg2.extras
else:
    import pymysql, pymysql.cursors

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clothstore_secret_key_v3_2024')

# ─────────────────────────────────────────────
# SECURITY SETUP
# ─────────────────────────────────────────────

# ── 1. Rate Limiter (DoS Protection) ──────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "60 per hour"],
    storage_uri="memory://",
)

# ── 2. Security Headers ────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options']    = 'nosniff'
    response.headers['X-Frame-Options']           = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']          = '1; mode=block'
    response.headers['Referrer-Policy']           = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']        = 'geolocation=(), microphone=(), camera=()'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ── 3. Input Sanitizer (XSS + SQL Injection prevention) ──
def sanitize(text, max_length=500):
    """Strip HTML tags and dangerous characters from user input."""
    if not text:
        return ''
    # Remove HTML tags
    clean = bleach.clean(str(text), tags=[], strip=True)
    # Remove SQL injection patterns
    sql_patterns = [
        r"(--|;|/\*|\*/)",
        r"(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|SCRIPT)",
    ]
    for pattern in sql_patterns:
        clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
    return clean[:max_length].strip()

def sanitize_email(email):
    """Validate and sanitize email address."""
    email = str(email).strip().lower()[:150]
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return None
    return email

def sanitize_phone(phone):
    """Only allow digits and + for phone numbers."""
    return re.sub(r'[^\d+\-\s]', '', str(phone))[:20]

# ── 4. Brute Force Tracker ─────────────────────
login_attempts = {}  # ip -> {'count': n, 'blocked_until': timestamp}

def is_ip_blocked(ip):
    data = login_attempts.get(ip, {})
    blocked_until = data.get('blocked_until', 0)
    if time.time() < blocked_until:
        remaining = int(blocked_until - time.time())
        return True, remaining
    return False, 0

def record_failed_login(ip):
    if ip not in login_attempts:
        login_attempts[ip] = {'count': 0, 'blocked_until': 0}
    login_attempts[ip]['count'] += 1
    if login_attempts[ip]['count'] >= 5:
        # Block for 15 minutes after 5 failed attempts
        login_attempts[ip]['blocked_until'] = time.time() + 900
        login_attempts[ip]['count'] = 0

def reset_login_attempts(ip):
    if ip in login_attempts:
        del login_attempts[ip]

# On Render, use /tmp for uploads (static dir may not be writable)
# For permanent uploads, use Cloudinary or AWS S3
UPLOAD_FOLDER      = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'static', 'uploads'))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER']      = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

def get_db():
    if USE_POSTGRES:
        # Render PostgreSQL
        url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return conn
    else:
        # Local MySQL
        return pymysql.connect(
            host='localhost', port=3306,
            user='root',
            password='02mM8943',
            database='clothstore',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(field):
    f = request.files.get(field)
    if f and f.filename and allowed_file(f.filename):
        fname = secure_filename(f.filename)
        base, ext = os.path.splitext(fname)
        fname = f"{base}_{int(time.time())}{ext}"
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        return '/static/uploads/' + fname
    return None

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('is_admin'):
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))
        return f(*a, **kw)
    return dec

def get_cart_count():
    if 'user_id' not in session or session.get('is_admin'):
        return 0
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT SUM(quantity) AS t FROM cart WHERE user_id=%s", (session['user_id'],))
            r = c.fetchone()
        return r['t'] or 0
    finally:
        db.close()

def get_all_settings():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT setting_key, setting_value FROM site_settings")
            rows = c.fetchall()
        return {r['setting_key']: r['setting_value'] for r in rows}
    finally:
        db.close()

def get_unread_chat_count():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT COUNT(*) AS n FROM chat_messages WHERE sender='user' AND is_read=0")
            return c.fetchone()['n']
    finally:
        db.close()

@app.context_processor
def inject_globals():
    s = get_all_settings()
    u = get_unread_chat_count() if session.get('is_admin') else 0
    return dict(site=s, unread_chat_count=u)

# ─── PUBLIC ───────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM products WHERE is_featured=1 AND stock>0 LIMIT 8")
            featured = c.fetchall()
            c.execute("SELECT * FROM products WHERE is_new=1 AND stock>0 LIMIT 8")
            new_arrivals = c.fetchall()
    finally:
        db.close()
    return render_template('index.html', featured=featured, new_arrivals=new_arrivals, cart_count=get_cart_count())

@app.route('/products')
def products():
    cat    = request.args.get('category', '')
    gender = request.args.get('gender', '')
    search = request.args.get('search', '')
    sort   = request.args.get('sort', 'newest')
    db = get_db()
    try:
        with db.cursor() as c:
            q, p = "SELECT * FROM products WHERE stock>0", []
            if cat:    q += " AND category=%s"; p.append(cat)
            if gender: q += " AND gender=%s";   p.append(gender)
            if search:
                q += " AND (name LIKE %s OR description LIKE %s)"
                p += [f'%{search}%', f'%{search}%']
            q += {'price_asc': " ORDER BY price ASC", 'price_desc': " ORDER BY price DESC"}.get(sort, " ORDER BY id DESC")
            c.execute(q, p); items = c.fetchall()
            c.execute("SELECT DISTINCT category FROM products")
            categories = [r['category'] for r in c.fetchall()]
    finally:
        db.close()
    return render_template('products.html', products=items, categories=categories,
                           selected_category=cat, selected_gender=gender,
                           search=search, sort=sort, cart_count=get_cart_count())

@app.route('/product/<int:pid>')
def product_detail(pid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM products WHERE id=%s", (pid,))
            product = c.fetchone()
            if not product:
                return redirect(url_for('products'))
            c.execute("SELECT * FROM products WHERE category=%s AND id!=%s AND stock>0 LIMIT 4",
                      (product['category'], pid))
            related = c.fetchall()
            c.execute("""SELECT r.*, u.name AS reviewer_name
                         FROM reviews r JOIN users u ON r.user_id=u.id
                         WHERE r.product_id=%s AND r.is_approved=1
                         ORDER BY r.id DESC""", (pid,))
            reviews = c.fetchall()
            avg_rating = round(sum(r['rating'] for r in reviews) / len(reviews), 1) if reviews else 0
            can_review = False
            user_review = None
            if session.get('user_id') and not session.get('is_admin'):
                # Allow review if user has any order containing this product (any status except cancelled)
                c.execute("""SELECT oi.id FROM order_items oi
                             JOIN orders o ON oi.order_id=o.id
                             WHERE o.user_id=%s AND oi.product_id=%s
                             AND o.status = 'delivered'
                             LIMIT 1""", (session['user_id'], pid))
                can_review = bool(c.fetchone())
                c.execute("SELECT * FROM reviews WHERE product_id=%s AND user_id=%s",
                          (pid, session['user_id']))
                user_review = c.fetchone()
    finally:
        db.close()
    return render_template('product_detail.html', product=product, related=related,
                           reviews=reviews, avg_rating=avg_rating,
                           can_review=can_review, user_review=user_review,
                           cart_count=get_cart_count())

# ─── AUTH ─────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        ip    = get_remote_address()
        # Check brute force block
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            flash(f'Too many failed attempts. Try again in {remaining//60}m {remaining%60}s.', 'error')
            return render_template('login.html', cart_count=0)

        ident = sanitize(request.form.get('identifier', '').strip(), 150)
        pw    = hash_password(request.form.get('password', ''))
        db = get_db()
        try:
            with db.cursor() as c:
                # Parameterized query — safe from SQL injection
                c.execute("SELECT * FROM users WHERE (email=%s OR phone=%s) AND password=%s",
                          (ident, ident, pw))
                user = c.fetchone()
        finally:
            db.close()
        if user:
            if user.get('tag') == 'Blocked':
                flash('Account blocked. Contact support.', 'error')
                return redirect(url_for('login'))
            reset_login_attempts(ip)
            session.update(user_id=user['id'], username=user['name'], is_admin=user['is_admin'])
            flash('Welcome back, ' + user['name'] + '!', 'success')
            return redirect(url_for('admin_dashboard') if user['is_admin'] else url_for('index'))
        # Failed — record attempt
        record_failed_login(ip)
        attempts = login_attempts.get(ip, {}).get('count', 0)
        remaining_tries = max(0, 5 - attempts)
        flash(f'Invalid email/phone or password. {remaining_tries} attempts remaining.', 'error')
    return render_template('login.html', cart_count=0)

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def register():
    if request.method == 'POST':
        name  = sanitize(request.form.get('name', ''), 100)
        email = sanitize_email(request.form.get('email', ''))
        phone = sanitize_phone(request.form.get('phone', ''))
        pw    = request.form.get('password', '')

        if not name:
            flash('Invalid name.', 'error'); return render_template('register.html', cart_count=0)
        if not email:
            flash('Invalid email address.', 'error'); return render_template('register.html', cart_count=0)
        if len(pw) < 6:
            flash('Password must be at least 6 characters.', 'error'); return render_template('register.html', cart_count=0)

        pw_hash = hash_password(pw)
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("INSERT INTO users (name,email,phone,password,tag) VALUES (%s,%s,%s,%s,'New')",
                          (name, email, phone or None, pw_hash))
            db.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower() or '1062' in str(e):
                flash('Email already registered.', 'error')
            else:
                flash(f'Registration error: {str(e)}', 'error')
        finally:
            db.close()
    return render_template('register.html', cart_count=0)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ─── FORGOT PASSWORD (OTP) ────────────────────────────────
@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password():
    if request.method == 'POST':
        ident = request.form.get('identifier', '').strip()
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("SELECT * FROM users WHERE email=%s OR phone=%s", (ident, ident))
                user = c.fetchone()
            if user:
                otp = str(random.randint(100000, 999999))
                from datetime import datetime, timedelta
                expiry = datetime.now() + timedelta(minutes=15)
                with db.cursor() as c:
                    c.execute("UPDATE users SET reset_token=%s, reset_expiry=%s WHERE id=%s",
                              (otp, expiry, user['id']))
                db.commit()
                session['otp_user_id'] = user['id']
                flash(f'[Dev mode] Your OTP is: {otp}', 'success')
                return redirect(url_for('verify_otp'))
            else:
                flash('No account found with that email or phone.', 'error')
        finally:
            db.close()
    return render_template('forgot_password.html', cart_count=0)

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'otp_user_id' not in session:
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        otp = request.form.get('otp', '').strip()
        from datetime import datetime
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("SELECT * FROM users WHERE id=%s AND reset_token=%s AND reset_expiry>%s",
                          (session['otp_user_id'], otp, datetime.now()))
                user = c.fetchone()
            if user:
                session['reset_user_id'] = user['id']
                session.pop('otp_user_id', None)
                return redirect(url_for('reset_password'))
            flash('Invalid or expired OTP.', 'error')
        finally:
            db.close()
    return render_template('verify_otp.html', cart_count=0)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if 'reset_user_id' not in session:
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        pw = hash_password(request.form['password'])
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("UPDATE users SET password=%s, reset_token=NULL, reset_expiry=NULL WHERE id=%s",
                          (pw, session['reset_user_id']))
            db.commit()
        finally:
            db.close()
        session.pop('reset_user_id', None)
        flash('Password reset! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', cart_count=0)

# ─── CART ─────────────────────────────────────────────────
@app.route('/cart')
@login_required
def cart():
    if session.get('is_admin'):
        flash('Admins cannot use the cart.', 'error')
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""SELECT c.id, c.quantity, c.size, p.name, p.price,
                         p.original_price, p.image, p.id AS product_id
                         FROM cart c JOIN products p ON c.product_id=p.id
                         WHERE c.user_id=%s""", (session['user_id'],))
            items = c.fetchall()
    finally:
        db.close()
    subtotal = sum(i['price'] * i['quantity'] for i in items)
    return render_template('cart.html', items=items, subtotal=subtotal, cart_count=len(items))

@app.route('/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    pid = request.form.get('product_id', type=int)
    if session.get('is_admin'):
        flash('Admins cannot add to cart.', 'error')
        return redirect(url_for('product_detail', pid=pid) if pid else url_for('admin_products'))
    qty  = request.form.get('quantity', 1, type=int)
    size = request.form.get('size', 'M')
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT id, quantity FROM cart WHERE user_id=%s AND product_id=%s AND size=%s",
                      (session['user_id'], pid, size))
            ex = c.fetchone()
            if ex:
                c.execute("UPDATE cart SET quantity=%s WHERE id=%s", (ex['quantity'] + qty, ex['id']))
            else:
                c.execute("INSERT INTO cart (user_id, product_id, quantity, size) VALUES (%s,%s,%s,%s)",
                          (session['user_id'], pid, qty, size))
        db.commit()
    finally:
        db.close()
    flash('Added to cart!', 'success')
    return redirect(url_for('product_detail', pid=pid))

@app.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    cid = request.form.get('cart_id', type=int)
    qty = request.form.get('quantity', type=int)
    db = get_db()
    try:
        with db.cursor() as c:
            if qty and qty > 0:
                c.execute("UPDATE cart SET quantity=%s WHERE id=%s AND user_id=%s",
                          (qty, cid, session['user_id']))
            else:
                c.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session['user_id']))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:cid>')
@login_required
def remove_from_cart(cid):
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session['user_id']))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('cart'))

# ─── VOUCHER ──────────────────────────────────────────────
@app.route('/voucher/validate', methods=['POST'])
@login_required
def validate_voucher():
    from datetime import date
    code     = request.form.get('code', '').strip().upper()
    subtotal = request.form.get('subtotal', 0, type=float)
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""SELECT * FROM vouchers WHERE code=%s AND is_active=1
                         AND (expires_at IS NULL OR expires_at>=%s)
                         AND (max_uses IS NULL OR used_count<max_uses)
                         AND (user_id IS NULL OR user_id=%s)""",
                      (code, date.today(), session['user_id']))
            v = c.fetchone()
        if not v:
            return jsonify(success=False, message='Invalid or expired voucher.')
        if subtotal < float(v['min_order']):
            return jsonify(success=False, message=f"Min order ৳{v['min_order']:.0f} required.")
        disc = float(v['discount_pct']) / 100 * subtotal if v['discount_pct'] > 0 else float(v['discount_amt'])
        disc = min(round(disc, 2), subtotal)
        return jsonify(success=True, discount=disc, message=f'Applied! -{disc:.0f}৳', voucher_id=v['id'])
    finally:
        db.close()

# ─── CHECKOUT SELECTED ────────────────────────────────────
@app.route('/checkout/selected', methods=['POST'])
@login_required
def checkout_selected():
    if session.get('is_admin'):
        flash('Admins cannot checkout.', 'error')
        return redirect(url_for('admin_dashboard'))
    selected_ids = request.form.getlist('selected_items')
    if not selected_ids:
        flash('Please select at least one item.', 'error')
        return redirect(url_for('cart'))
    db = get_db()
    try:
        with db.cursor() as c:
            fmt = ','.join(['%s'] * len(selected_ids))
            c.execute(f"""SELECT c.id AS cart_id, c.quantity, c.size,
                          p.name, p.price, p.id AS product_id, p.image
                          FROM cart c JOIN products p ON c.product_id=p.id
                          WHERE c.id IN ({fmt}) AND c.user_id=%s""",
                      (*selected_ids, session['user_id']))
            items = c.fetchall()
            c.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
            user = c.fetchone()
    finally:
        db.close()
    if not items:
        flash('No valid items found.', 'error')
        return redirect(url_for('cart'))
    subtotal = sum(i['price'] * i['quantity'] for i in items)
    return render_template('checkout.html', items=items, subtotal=subtotal,
                           settings=get_all_settings(), cart_count=get_cart_count(),
                           user_name=user['name'], user_phone=user.get('phone', '') or '')

# ─── CHECKOUT POST ────────────────────────────────────────
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
@limiter.limit("30 per hour")
def checkout():
    if session.get('is_admin'):
        flash('Admins cannot checkout.', 'error')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'GET':
        return redirect(url_for('cart'))

    # ── POST: place the order ──
    payment_method  = request.form.get('payment_method', 'cod')
    voucher_id      = request.form.get('voucher_id', type=int)
    discount_amount = request.form.get('discount_amount', 0.0, type=float)
    name            = sanitize(request.form.get('name', ''), 100)
    phone           = sanitize_phone(request.form.get('phone', ''))
    city            = sanitize(request.form.get('city', ''), 100)
    address_raw     = sanitize(request.form.get('address', ''), 300)
    full_address    = f"{city}, {address_raw}".strip(', ') if city else address_raw
    selected_ids    = request.form.getlist('selected_items')

    if not name or not phone or not address_raw:
        flash('Please fill in your name, phone and address.', 'error')
        return redirect(url_for('cart'))

    db = get_db()
    try:
        # If selected_items were passed use them, otherwise use entire cart
        if selected_ids:
            fmt = ','.join(['%s'] * len(selected_ids))
            with db.cursor() as c:
                c.execute(f"""SELECT c.id AS cart_id, c.quantity, c.size,
                              p.id AS product_id, p.price
                              FROM cart c JOIN products p ON c.product_id=p.id
                              WHERE c.id IN ({fmt}) AND c.user_id=%s""",
                          (*selected_ids, session['user_id']))
                items = c.fetchall()
        else:
            # Fallback: use all cart items
            with db.cursor() as c:
                c.execute("""SELECT c.id AS cart_id, c.quantity, c.size,
                              p.id AS product_id, p.price
                              FROM cart c JOIN products p ON c.product_id=p.id
                              WHERE c.user_id=%s""", (session['user_id'],))
                items = c.fetchall()

        if not items:
            flash('Your cart is empty.', 'error')
            return redirect(url_for('cart'))

        subtotal    = sum(float(i['price']) * int(i['quantity']) for i in items)
        delivery    = 0 if subtotal >= 2000 else 80
        final_total = max(subtotal + delivery - discount_amount, 0)

        with db.cursor() as c:
            c.execute("""INSERT INTO orders
                (user_id, name, phone, address, total, discount_amount, payment_method)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (session['user_id'], name, phone, full_address,
                 final_total, discount_amount, payment_method))
            oid = c.lastrowid

            for item in items:
                c.execute("INSERT INTO order_items (order_id,product_id,quantity,size,price) VALUES (%s,%s,%s,%s,%s)",
                          (oid, item['product_id'], item['quantity'], item['size'], item['price']))

            if voucher_id:
                c.execute("UPDATE vouchers SET used_count=used_count+1 WHERE id=%s", (voucher_id,))

            # Remove ordered items from cart
            if selected_ids:
                for cid in selected_ids:
                    c.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session['user_id']))
            else:
                c.execute("DELETE FROM cart WHERE user_id=%s", (session['user_id'],))

        db.commit()
        flash(f'Order #{oid} placed successfully! 🎉', 'success')
        return redirect(url_for('order_tracking', oid=oid))

    except Exception as e:
        db.rollback()
        flash(f'Order failed: {str(e)}', 'error')
        return redirect(url_for('cart'))
    finally:
        db.close()

# ─── USER ORDERS ──────────────────────────────────────────
@app.route('/my-orders')
@login_required
def my_orders():
    if session.get('is_admin'):
        return redirect(url_for('admin_orders'))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC", (session['user_id'],))
            orders = c.fetchall()
    finally:
        db.close()
    return render_template('my_orders.html', orders=orders, cart_count=get_cart_count())

@app.route('/my-orders/<int:oid>')
@login_required
def order_tracking(oid):
    if session.get('is_admin'):
        return redirect(url_for('admin_order_detail', oid=oid))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM orders WHERE id=%s AND user_id=%s", (oid, session['user_id']))
            order = c.fetchone()
            if not order:
                flash('Order not found.', 'error'); return redirect(url_for('my_orders'))
            c.execute("""SELECT oi.*, p.name AS product_name, p.image, p.id AS product_id
                         FROM order_items oi JOIN products p ON oi.product_id=p.id
                         WHERE oi.order_id=%s""", (oid,))
            items = c.fetchall()
            # Load existing reviews for each product in this order
            reviews_map = {}
            if order['status'] == 'delivered':
                for item in items:
                    c.execute("SELECT * FROM reviews WHERE product_id=%s AND user_id=%s",
                              (item['product_id'], session['user_id']))
                    reviews_map[item['product_id']] = c.fetchone()
    finally:
        db.close()
    return render_template('order_tracking.html', order=order, items=items,
                           reviews_map=reviews_map, cart_count=get_cart_count())

# ─── USER PROFILE ─────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def user_profile():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'change_name':
                name = request.form.get('name', '').strip()
                if name:
                    with db.cursor() as c:
                        c.execute("UPDATE users SET name=%s WHERE id=%s", (name, session['user_id']))
                    db.commit(); session['username'] = name
                    flash('Name updated!', 'success')
            elif action == 'change_phone':
                phone = request.form.get('phone', '').strip()
                with db.cursor() as c:
                    c.execute("UPDATE users SET phone=%s WHERE id=%s", (phone or None, session['user_id']))
                db.commit(); flash('Phone updated!', 'success')
            elif action == 'change_password':
                old_pw  = hash_password(request.form.get('old_password', ''))
                new_pw  = request.form.get('new_password', '')
                conf_pw = request.form.get('confirm_password', '')
                if new_pw != conf_pw:
                    flash('Passwords do not match.', 'error')
                elif len(new_pw) < 6:
                    flash('Password must be at least 6 characters.', 'error')
                else:
                    with db.cursor() as c:
                        c.execute("SELECT id FROM users WHERE id=%s AND password=%s",
                                  (session['user_id'], old_pw))
                        ok = c.fetchone()
                    if ok:
                        with db.cursor() as c:
                            c.execute("UPDATE users SET password=%s WHERE id=%s",
                                      (hash_password(new_pw), session['user_id']))
                        db.commit(); flash('Password changed!', 'success')
                    else:
                        flash('Current password incorrect.', 'error')
            return redirect(url_for('user_profile') + '?tab=' + request.form.get('tab', 'settings'))

        active_tab   = request.args.get('tab', 'profile')
        order_status = request.args.get('status', '')
        with db.cursor() as c:
            c.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],)); user = c.fetchone()
            q = "SELECT * FROM orders WHERE user_id=%s"; p = [session['user_id']]
            if order_status and order_status != 'all':
                q += " AND status=%s"; p.append(order_status)
            q += " ORDER BY id DESC"; c.execute(q, p); all_orders = c.fetchall()
            c.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 3",
                      (session['user_id'],)); recent_orders = c.fetchall()
            c.execute("SELECT COUNT(*) AS n FROM orders WHERE user_id=%s", (session['user_id'],))
            total_orders = c.fetchone()['n']
            c.execute("SELECT COALESCE(SUM(total),0) AS s FROM orders WHERE user_id=%s AND status!='cancelled'",
                      (session['user_id'],)); total_spent = c.fetchone()['s']
            status_counts = {}
            for st in ['pending', 'processing', 'shipped', 'delivered', 'cancelled']:
                c.execute("SELECT COUNT(*) AS n FROM orders WHERE user_id=%s AND status=%s",
                          (session['user_id'], st)); status_counts[st] = c.fetchone()['n']
            c.execute("SELECT * FROM chat_messages WHERE user_id=%s ORDER BY created_at ASC",
                      (session['user_id'],)); chat_messages = c.fetchall()
            c.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='admin'",
                      (session['user_id'],))
        db.commit()
    finally:
        db.close()
    stats = {'total_orders': total_orders, 'total_spent': float(total_spent),
             **status_counts}
    return render_template('profile.html', user=user, stats=stats, all_orders=all_orders,
                           recent_orders=recent_orders, chat_messages=chat_messages,
                           active_tab=active_tab, order_status=order_status,
                           cart_count=get_cart_count())

# ─── REVIEWS ──────────────────────────────────────────────
@app.route('/product/<int:pid>/review', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def submit_review(pid):
    if session.get('is_admin'):
        return redirect(url_for('product_detail', pid=pid))
    rating = request.form.get('rating', type=int)
    title  = sanitize(request.form.get('title', ''), 200)
    body   = sanitize(request.form.get('body', ''), 1000)
    next_url = request.form.get('next', url_for('product_detail', pid=pid))
    if not rating or not 1 <= rating <= 5:
        flash('Please select a star rating.', 'error')
        return redirect(next_url)
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""SELECT oi.id FROM order_items oi JOIN orders o ON oi.order_id=o.id
                         WHERE o.user_id=%s AND oi.product_id=%s
                         AND o.status = 'delivered' LIMIT 1""",
                      (session['user_id'], pid))
            if not c.fetchone():
                flash('You can only review products after delivery.', 'error')
                return redirect(next_url)
            # Handle media uploads (photos/videos)
            media = []
            for field in ['media_1', 'media_2', 'media_3']:
                f = request.files.get(field)
                if f and f.filename:
                    allowed = {'png','jpg','jpeg','gif','webp','mp4','mov','avi','webm'}
                    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                    if ext in allowed:
                        fname = secure_filename(f.filename)
                        base, fext = os.path.splitext(fname)
                        fname = f"{base}_{int(time.time())}{fext}"
                        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                        media.append('/static/uploads/' + fname)
                    else:
                        media.append(None)
                else:
                    media.append(None)
            while len(media) < 3:
                media.append(None)
          if USE_POSTGRES:
    c.execute("""INSERT INTO reviews (product_id, user_id, rating, title, body, media_1, media_2, media_3)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (product_id, user_id) DO UPDATE SET
                 rating=EXCLUDED.rating, title=EXCLUDED.title, body=EXCLUDED.body,
                 media_1=COALESCE(EXCLUDED.media_1, reviews.media_1),
                 media_2=COALESCE(EXCLUDED.media_2, reviews.media_2),
                 media_3=COALESCE(EXCLUDED.media_3, reviews.media_3)""",
                 (pid, session['user_id'], rating, title, body, media[0], media[1], media[2]))
else:
    c.execute("""INSERT INTO reviews (product_id, user_id, rating, title, body, media_1, media_2, media_3)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                 ON DUPLICATE KEY UPDATE rating=%s, title=%s, body=%s,
                 media_1=COALESCE(VALUES(media_1), media_1),
                 media_2=COALESCE(VALUES(media_2), media_2),
                 media_3=COALESCE(VALUES(media_3), media_3)""",
                 (pid, session['user_id'], rating, title, body, media[0], media[1], media[2],
                  rating, title, body))
                      (pid, session['user_id'], rating, title, body, media[0], media[1], media[2],
                       rating, title, body))
        db.commit()
        flash('Review submitted! Thank you. 🌟', 'success')
    except Exception as e:
        flash(f'Could not submit review: {str(e)}', 'error')
    finally:
        db.close()
    return redirect(next_url)

# ─── LIVE CHAT ────────────────────────────────────────────
@app.route('/chat', methods=['GET', 'POST'])
@login_required
def user_chat():
    if session.get('is_admin'):
        return redirect(url_for('admin_chat_list'))
    db = get_db()
    try:
        if request.method == 'POST':
            msg = request.form.get('message', '').strip()
            if msg:
                with db.cursor() as c:
                    c.execute("INSERT INTO chat_messages (user_id,sender,message) VALUES (%s,'user',%s)",
                              (session['user_id'], msg))
                db.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=True)
            return redirect(url_for('user_chat'))
        with db.cursor() as c:
            c.execute("SELECT * FROM chat_messages WHERE user_id=%s ORDER BY created_at ASC",
                      (session['user_id'],)); messages = c.fetchall()
            c.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='admin'",
                      (session['user_id'],))
        db.commit()
    finally:
        db.close()
    return render_template('chat.html', messages=messages, cart_count=get_cart_count())

@app.route('/chat/poll')
@login_required
def chat_poll():
    since = request.args.get('since', 0, type=int)
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM chat_messages WHERE user_id=%s AND id>%s ORDER BY created_at ASC",
                      (session['user_id'], since)); msgs = c.fetchall()
            c.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='admin' AND id>%s",
                      (session['user_id'], since))
        db.commit()
        return jsonify(messages=[{'id': m['id'], 'sender': m['sender'], 'message': m['message'],
                                  'time': m['created_at'].strftime('%H:%M') if m['created_at'] else ''} for m in msgs])
    finally:
        db.close()

# ═══ ADMIN ════════════════════════════════════════════════
@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT COUNT(*) AS c FROM products");   prod_count  = c.fetchone()['c']
            c.execute("SELECT COUNT(*) AS c FROM orders");     order_count = c.fetchone()['c']
            c.execute("SELECT COUNT(*) AS c FROM users");      user_count  = c.fetchone()['c']
            c.execute("SELECT SUM(total) AS rev FROM orders WHERE status!='cancelled'"); revenue = c.fetchone()['rev'] or 0
            c.execute("SELECT COUNT(*) AS c FROM orders WHERE status='pending'");        pending      = c.fetchone()['c']
            c.execute("SELECT COUNT(*) AS c FROM products WHERE stock=0");               out_of_stock = c.fetchone()['c']
            c.execute("SELECT COUNT(*) AS c FROM products WHERE stock>0 AND stock<=5");  low_stock    = c.fetchone()['c']
            c.execute("SELECT o.*,u.name AS customer FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.id DESC LIMIT 10")
            recent_orders = c.fetchall()
    finally:
        db.close()
    return render_template('admin/dashboard.html', prod_count=prod_count, order_count=order_count,
                           user_count=user_count, revenue=revenue, pending=pending,
                           out_of_stock=out_of_stock, low_stock=low_stock, recent_orders=recent_orders)

@app.route('/admin/products')
@admin_required
def admin_products():
    search   = request.args.get('search', '')
    category = request.args.get('category', '')
    gender   = request.args.get('gender', '')
    stock_f  = request.args.get('stock', '')
    flag     = request.args.get('flag', '')
    db = get_db()
    try:
        with db.cursor() as c:
            q, p = "SELECT * FROM products WHERE 1=1", []
            if search:   q += " AND name LIKE %s";  p.append(f'%{search}%')
            if category: q += " AND category=%s";   p.append(category)
            if gender:   q += " AND gender=%s";     p.append(gender)
            if stock_f == 'out':  q += " AND stock=0"
            elif stock_f == 'low': q += " AND stock>0 AND stock<=5"
            if flag == 'featured': q += " AND is_featured=1"
            elif flag == 'new':    q += " AND is_new=1"
            elif flag == 'none':   q += " AND is_featured=0 AND is_new=0"
            q += " ORDER BY id DESC"; c.execute(q, p); items = c.fetchall()
    finally:
        db.close()
    return render_template('admin/products.html', products=items, search=search,
                           category=category, gender=gender, stock_f=stock_f, flag=flag)

@app.route('/admin/product/<int:pid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_product(pid):
    flag  = request.form.get('flag', '')
    value = request.form.get('value', '')
    db = get_db()
    try:
        with db.cursor() as c:
            if flag == 'featured':
                c.execute("UPDATE products SET is_featured=%s WHERE id=%s", (int(value), pid)); msg = f"Featured {'on' if int(value) else 'off'}"
            elif flag == 'is_new':
                c.execute("UPDATE products SET is_new=%s WHERE id=%s", (int(value), pid)); msg = f"New Arrival {'on' if int(value) else 'off'}"
            elif flag == 'stock':
                c.execute("UPDATE products SET stock=%s WHERE id=%s", (int(value), pid)); msg = f"Stock set to {value}"
            elif flag == 'category' and value in ['t-shirt', 'shirt', 'pant']:
                c.execute("UPDATE products SET category=%s WHERE id=%s", (value, pid)); msg = f"Category: {value}"
            elif flag == 'gender' and value in ['men', 'kid']:
                c.execute("UPDATE products SET gender=%s WHERE id=%s", (value, pid)); msg = f"Gender: {value}"
            else:
                return jsonify(success=False, message="Invalid field")
        db.commit()
        return jsonify(success=True, message=msg)
    except Exception as e:
        return jsonify(success=False, message=str(e))
    finally:
        db.close()

@app.route('/admin/product/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        img = save_upload('image_file') or request.form.get('image_url', '').strip()
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("""INSERT INTO products (name,category,gender,price,original_price,description,image,sizes,stock,is_new,is_featured)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['name'], request.form['category'], request.form['gender'],
                     request.form['price'], request.form.get('original_price') or None,
                     request.form.get('description', ''), img, request.form.get('sizes', 'S,M,L,XL'),
                     request.form.get('stock', 0), int('is_new' in request.form), int('is_featured' in request.form)))
            db.commit()
        finally:
            db.close()
        flash('Product added!', 'success'); return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html', product=None, action='Add')

@app.route('/admin/product/edit/<int:pid>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(pid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM products WHERE id=%s", (pid,)); product = c.fetchone()
        if not product:
            flash('Not found.', 'error'); return redirect(url_for('admin_products'))
        if request.method == 'POST':
            img = save_upload('image_file') or request.form.get('image_url', '').strip() or product['image']
            with db.cursor() as c:
                c.execute("""UPDATE products SET name=%s,category=%s,gender=%s,price=%s,original_price=%s,
                    description=%s,image=%s,sizes=%s,stock=%s,is_new=%s,is_featured=%s WHERE id=%s""",
                    (request.form['name'], request.form['category'], request.form['gender'],
                     request.form['price'], request.form.get('original_price') or None,
                     request.form.get('description', ''), img, request.form.get('sizes', 'S,M,L,XL'),
                     request.form.get('stock', 0), int('is_new' in request.form), int('is_featured' in request.form), pid))
            db.commit(); flash('Updated!', 'success'); return redirect(url_for('admin_products'))
    finally:
        db.close()
    return render_template('admin/product_form.html', product=product, action='Edit')

@app.route('/admin/product/stock/<int:pid>', methods=['POST'])
@admin_required
def admin_update_stock(pid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("UPDATE products SET stock=%s WHERE id=%s", (request.form.get('stock', type=int), pid))
        db.commit()
    finally:
        db.close()
    flash('Stock updated!', 'success'); return redirect(url_for('admin_products'))

@app.route('/admin/product/delete/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_product(pid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("DELETE FROM cart WHERE product_id=%s", (pid,))
            c.execute("DELETE FROM products WHERE id=%s", (pid,))
        db.commit()
    finally:
        db.close()
    flash('Deleted.', 'success'); return redirect(url_for('admin_products'))

@app.route('/admin/orders')
@admin_required
def admin_orders():
    sf = request.args.get('status', ''); search = request.args.get('search', '')
    db = get_db()
    try:
        with db.cursor() as c:
            q = "SELECT o.*,u.name AS customer FROM orders o JOIN users u ON o.user_id=u.id WHERE 1=1"; p = []
            if sf: q += " AND o.status=%s"; p.append(sf)
            if search: q += " AND (u.name LIKE %s OR o.phone LIKE %s)"; p += [f'%{search}%', f'%{search}%']
            q += " ORDER BY o.id DESC"; c.execute(q, p); orders = c.fetchall()
    finally:
        db.close()
    return render_template('admin/orders.html', orders=orders, status_f=sf, search=search)

@app.route('/admin/order/<int:oid>', methods=['GET', 'POST'])
@admin_required
def admin_order_detail(oid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT o.*,u.name AS customer,u.email FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=%s", (oid,))
            order = c.fetchone()
            if not order: flash('Not found.', 'error'); return redirect(url_for('admin_orders'))
            c.execute("SELECT oi.*,p.name AS product_name,p.image FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s", (oid,))
            items = c.fetchall()
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'update_discount':
                disc = request.form.get('discount_amount', 0.0, type=float)
                note = request.form.get('admin_note', '').strip()
                orig = sum(i['price'] * i['quantity'] for i in items)
                with db.cursor() as c:
                    c.execute("UPDATE orders SET discount_amount=%s,admin_note=%s,total=%s WHERE id=%s",
                              (disc, note, max(orig - disc, 0), oid))
                db.commit(); flash('Discount applied!', 'success')
            elif action == 'update_tracking':
                tn = request.form.get('tracking_note', '').strip()
                with db.cursor() as c:
                    c.execute("UPDATE orders SET tracking_note=%s WHERE id=%s", (tn, oid))
                db.commit(); flash('Tracking updated!', 'success')
            return redirect(url_for('admin_order_detail', oid=oid))
    finally:
        db.close()
    return render_template('admin/order_detail.html', order=order, items=items)

@app.route('/admin/order/<int:oid>/status', methods=['POST'])
@admin_required
def admin_update_order_status(oid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("UPDATE orders SET status=%s WHERE id=%s", (request.form['status'], oid))
        db.commit()
    finally:
        db.close()
    flash('Status updated!', 'success'); return redirect(request.form.get('next', url_for('admin_orders')))

@app.route('/admin/order/delete/<int:oid>', methods=['POST'])
@admin_required
def admin_delete_order(oid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("DELETE FROM order_items WHERE order_id=%s", (oid,))
            c.execute("DELETE FROM orders WHERE id=%s", (oid,))
        db.commit()
    finally:
        db.close()
    flash('Deleted.', 'success'); return redirect(url_for('admin_orders'))

@app.route('/admin/users')
@admin_required
def admin_users():
    search = request.args.get('search', '')
    db = get_db()
    try:
        with db.cursor() as c:
            q = "SELECT u.*,(SELECT COUNT(*) FROM orders WHERE user_id=u.id) AS order_count FROM users u WHERE 1=1"; p = []
            if search: q += " AND (u.name LIKE %s OR u.email LIKE %s)"; p += [f'%{search}%', f'%{search}%']
            q += " ORDER BY u.id DESC"; c.execute(q, p); users = c.fetchall()
    finally:
        db.close()
    return render_template('admin/users.html', users=users, search=search)

@app.route('/admin/user/<int:uid>/set-tag', methods=['POST'])
@admin_required
def admin_set_user_tag(uid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("UPDATE users SET tag=%s,rating=%s WHERE id=%s",
                      (request.form.get('tag', 'New'), request.form.get('rating', type=int), uid))
        db.commit()
    finally:
        db.close()
    flash('Updated.', 'success'); return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:uid>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    if uid == session['user_id']:
        flash("Can't change your own role.", 'error'); return redirect(url_for('admin_users'))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("UPDATE users SET is_admin=NOT is_admin WHERE id=%s", (uid,))
        db.commit()
    finally:
        db.close()
    flash('Role updated.', 'success'); return redirect(url_for('admin_users'))

@app.route('/admin/user/delete/<int:uid>', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid == session['user_id']:
        flash("Can't delete yourself.", 'error'); return redirect(url_for('admin_users'))
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("DELETE FROM cart WHERE user_id=%s", (uid,))
            c.execute("DELETE FROM users WHERE id=%s", (uid,))
        db.commit()
    finally:
        db.close()
    flash('Deleted.', 'success'); return redirect(url_for('admin_users'))

@app.route('/admin/vouchers')
@admin_required
def admin_vouchers():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT v.*,u.name AS user_name FROM vouchers v LEFT JOIN users u ON v.user_id=u.id ORDER BY v.id DESC"); vouchers = c.fetchall()
            c.execute("SELECT id,name FROM users WHERE is_admin=0 ORDER BY name"); users = c.fetchall()
    finally:
        db.close()
    return render_template('admin/vouchers.html', vouchers=vouchers, users=users)

@app.route('/admin/vouchers/add', methods=['POST'])
@admin_required
def admin_add_voucher():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("INSERT INTO vouchers (code,discount_pct,discount_amt,min_order,max_uses,user_id,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (request.form.get('code', '').strip().upper(), request.form.get('discount_pct', 0.0, type=float),
                 request.form.get('discount_amt', 0.0, type=float), request.form.get('min_order', 0.0, type=float),
                 request.form.get('max_uses', type=int), request.form.get('user_id', type=int), request.form.get('expires_at') or None))
        db.commit(); flash('Voucher created!', 'success')
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower() or '1062' in str(e):
            flash('Code already exists.', 'error')
        else:
            flash(f'Error: {str(e)}', 'error')
    finally:
        db.close()
    return redirect(url_for('admin_vouchers'))

@app.route('/admin/vouchers/delete/<int:vid>', methods=['POST'])
@admin_required
def admin_delete_voucher(vid):
    db = get_db()
    try:
        with db.cursor() as c: c.execute("DELETE FROM vouchers WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()
    flash('Deleted.', 'success'); return redirect(url_for('admin_vouchers'))

@app.route('/admin/vouchers/toggle/<int:vid>', methods=['POST'])
@admin_required
def admin_toggle_voucher(vid):
    db = get_db()
    try:
        with db.cursor() as c: c.execute("UPDATE vouchers SET is_active=NOT is_active WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('admin_vouchers'))

@app.route('/admin/banners', methods=['GET', 'POST'])
@admin_required
def admin_banners():
    if request.method == 'POST':
        db = get_db()
        try:
            with db.cursor() as c:
                for key in ['announcement_bar','hero_title','hero_subtitle','hero_badge',
                            'hero_stat_1_num','hero_stat_1_label','hero_stat_2_num','hero_stat_2_label',
                            'hero_stat_3_num','hero_stat_3_label',
                            'promo_strip_1','promo_strip_2','promo_strip_3','promo_strip_4',
                            'feature_badge_1','feature_badge_2','feature_badge_3',
                            'bkash_number','nagad_number','rocket_number','payment_instructions']:
                    val = request.form.get(key, '').strip()
                    c.execute("INSERT INTO site_settings (setting_key,setting_value) VALUES (%s,%s) ON DUPLICATE KEY UPDATE setting_value=%s", (key, val, val))
            db.commit()
        finally:
            db.close()
        flash('Saved!', 'success'); return redirect(url_for('admin_banners'))
    return render_template('admin/banners.html', settings=get_all_settings())

@app.route('/admin/homepage', methods=['GET', 'POST'])
@admin_required
def admin_homepage():
    if request.method == 'POST':
        db = get_db()
        try:
            with db.cursor() as c:
                keys = ['section_cat_title','section_cat_sub','section_featured_title','section_featured_sub','section_new_title','section_new_sub']
                for i in range(1, 7): keys += [f'cat_{i}_label', f'cat_{i}_sub', f'cat_{i}_url', f'cat_{i}_img']
                for i in range(1, 3): keys += [f'promo_{i}_title', f'promo_{i}_text', f'promo_{i}_btn', f'promo_{i}_url', f'promo_{i}_img']
                for key in keys:
                    val = request.form.get(key, '').strip()
                    c.execute("INSERT INTO site_settings (setting_key,setting_value) VALUES (%s,%s) ON DUPLICATE KEY UPDATE setting_value=%s", (key, val, val))
            db.commit()
        finally:
            db.close()
        flash('Homepage saved!', 'success'); return redirect(url_for('admin_homepage'))
    return render_template('admin/homepage.html', s=get_all_settings())

@app.route('/admin/reviews')
@admin_required
def admin_reviews():
    status = request.args.get('status', '')
    db = get_db()
    try:
        with db.cursor() as c:
            q = """SELECT r.*,u.name AS user_name,p.name AS product_name,p.image AS product_image
                   FROM reviews r JOIN users u ON r.user_id=u.id JOIN products p ON r.product_id=p.id WHERE 1=1"""
            if status == 'pending':  q += " AND r.is_approved=0"
            elif status == 'approved': q += " AND r.is_approved=1"
            q += " ORDER BY r.id DESC"; c.execute(q); reviews = c.fetchall()
    finally:
        db.close()
    return render_template('admin/reviews.html', reviews=reviews, status=status)

@app.route('/admin/reviews/<int:rid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_review(rid):
    db = get_db()
    try:
        with db.cursor() as c: c.execute("UPDATE reviews SET is_approved=NOT is_approved WHERE id=%s", (rid,))
        db.commit()
    finally:
        db.close()
    flash('Updated.', 'success'); return redirect(url_for('admin_reviews'))

@app.route('/admin/reviews/<int:rid>/delete', methods=['POST'])
@admin_required
def admin_delete_review(rid):
    db = get_db()
    try:
        with db.cursor() as c: c.execute("DELETE FROM reviews WHERE id=%s", (rid,))
        db.commit()
    finally:
        db.close()
    flash('Deleted.', 'success'); return redirect(url_for('admin_reviews'))

@app.route('/admin/chat')
@admin_required
def admin_chat_list():
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""SELECT u.id,u.name,u.email,
                (SELECT COUNT(*) FROM chat_messages WHERE user_id=u.id AND sender='user' AND is_read=0) AS unread,
                (SELECT MAX(created_at) FROM chat_messages WHERE user_id=u.id) AS last_msg
                FROM users u WHERE EXISTS (SELECT 1 FROM chat_messages WHERE user_id=u.id)
                ORDER BY last_msg DESC"""); chats = c.fetchall()
    finally:
        db.close()
    return render_template('admin/chat_list.html', chats=chats)

@app.route('/admin/chat/<int:uid>', methods=['GET', 'POST'])
@admin_required
def admin_chat_user(uid):
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM users WHERE id=%s", (uid,)); user = c.fetchone()
        if not user: flash('Not found.', 'error'); return redirect(url_for('admin_chat_list'))
        if request.method == 'POST':
            msg = request.form.get('message', '').strip()
            if msg:
                with db.cursor() as c:
                    c.execute("INSERT INTO chat_messages (user_id,sender,message) VALUES (%s,'admin',%s)", (uid, msg))
                db.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=True)
            return redirect(url_for('admin_chat_user', uid=uid))
        with db.cursor() as c:
            c.execute("SELECT * FROM chat_messages WHERE user_id=%s ORDER BY created_at ASC", (uid,)); messages = c.fetchall()
            c.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='user'", (uid,))
        db.commit()
    finally:
        db.close()
    return render_template('admin/chat_user.html', user=user, messages=messages)

@app.route('/admin/chat/<int:uid>/poll')
@admin_required
def admin_chat_poll(uid):
    since = request.args.get('since', 0, type=int)
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("SELECT * FROM chat_messages WHERE user_id=%s AND id>%s ORDER BY created_at ASC", (uid, since)); msgs = c.fetchall()
            c.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='user' AND id>%s", (uid, since))
        db.commit()
        return jsonify(messages=[{'id': m['id'], 'sender': m['sender'], 'message': m['message'],
                                  'time': m['created_at'].strftime('%H:%M') if m['created_at'] else ''} for m in msgs])
    finally:
        db.close()

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old = hash_password(request.form['old_password']); new = hash_password(request.form['new_password'])
            db = get_db()
            try:
                with db.cursor() as c:
                    c.execute("SELECT id FROM users WHERE id=%s AND password=%s", (session['user_id'], old))
                    if c.fetchone():
                        c.execute("UPDATE users SET password=%s WHERE id=%s", (new, session['user_id'])); db.commit(); flash('Password changed!', 'success')
                    else: flash('Incorrect password.', 'error')
            finally: db.close()
        elif action == 'change_name':
            name = request.form.get('name', '').strip()
            if name:
                db = get_db()
                try:
                    with db.cursor() as c: c.execute("UPDATE users SET name=%s WHERE id=%s", (name, session['user_id']))
                    db.commit(); session['username'] = name; flash('Name updated!', 'success')
                finally: db.close()
        return redirect(url_for('admin_settings'))
    return render_template('admin/settings.html')

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True, host='localhost', port=5000)
