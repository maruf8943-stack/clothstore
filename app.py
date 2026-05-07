from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import pymysql
import pymysql.cursors
from functools import wraps
import hashlib, os, time, secrets
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clothstore_secret_key_v3_2024'

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER']       = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH']  = 5 * 1024 * 1024

DB_CONFIG = {
    'host':        'localhost',
    'port':        3306,
    'user':        'root',
    'password':    '02mM8943',   # <-- your MySQL password here
    'database':    'clothstore',
    'charset':     'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}

def get_db():
    return pymysql.connect(**DB_CONFIG)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(file_field):
    f = request.files.get(file_field)
    if f and f.filename and allowed_file(f.filename):
        fname = secure_filename(f.filename)
        base, ext = os.path.splitext(fname)
        fname = f"{base}_{int(time.time())}{ext}"
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        return '/static/uploads/' + fname
    return None

# ─────────────────────────────────────────────
# HELPERS / DECORATORS
# ─────────────────────────────────────────────
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
    if 'user_id' not in session:
        return 0
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT SUM(quantity) AS t FROM cart WHERE user_id=%s", (session['user_id'],))
            row = cur.fetchone()
        return row['t'] or 0
    finally:
        db.close()

def get_setting(key, default=''):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT setting_value FROM site_settings WHERE setting_key=%s", (key,))
            r = cur.fetchone()
        return r['setting_value'] if r else default
    finally:
        db.close()

def get_all_settings():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT setting_key, setting_value FROM site_settings")
            rows = cur.fetchall()
        return {r['setting_key']: r['setting_value'] for r in rows}
    finally:
        db.close()

def get_unread_chat_count():
    """Count messages from users that admin hasn't read."""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM chat_messages WHERE sender='user' AND is_read=0")
            return cur.fetchone()['c']
    finally:
        db.close()

# ─────────────────────────────────────────────
# CONTEXT PROCESSORS
# ─────────────────────────────────────────────
@app.context_processor
def inject_settings():
    return dict(site=get_all_settings())

# ─────────────────────────────────────────────
# PUBLIC ROUTES
# ─────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE is_featured=1 AND stock>0 LIMIT 8")
            featured = cur.fetchall()
            cur.execute("SELECT * FROM products WHERE is_new=1 AND stock>0 LIMIT 8")
            new_arrivals = cur.fetchall()
    finally:
        db.close()
    return render_template('index.html', featured=featured, new_arrivals=new_arrivals, cart_count=get_cart_count())

@app.route('/products')
def products():
    category = request.args.get('category', '')
    gender   = request.args.get('gender', '')
    search   = request.args.get('search', '')
    sort     = request.args.get('sort', 'newest')
    db = get_db()
    try:
        with db.cursor() as cur:
            q, p = "SELECT * FROM products WHERE stock>0", []
            if category: q += " AND category=%s";  p.append(category)
            if gender:   q += " AND gender=%s";    p.append(gender)
            if search:
                q += " AND (name LIKE %s OR description LIKE %s)"
                p += [f'%{search}%', f'%{search}%']
            q += {'price_asc': " ORDER BY price ASC", 'price_desc': " ORDER BY price DESC"}.get(sort, " ORDER BY id DESC")
            cur.execute(q, p)
            items = cur.fetchall()
            cur.execute("SELECT DISTINCT category FROM products")
            categories = [r['category'] for r in cur.fetchall()]
    finally:
        db.close()
    return render_template('products.html', products=items, categories=categories,
                           selected_category=category, selected_gender=gender,
                           search=search, sort=sort, cart_count=get_cart_count())

@app.route('/product/<int:pid>')
def product_detail(pid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
            product = cur.fetchone()
            if not product: return redirect(url_for('products'))
            cur.execute("SELECT * FROM products WHERE category=%s AND id!=%s AND stock>0 LIMIT 4",
                        (product['category'], pid))
            related = cur.fetchall()
    finally:
        db.close()
    return render_template('product_detail.html', product=product, related=related, cart_count=get_cart_count())

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()  # email OR phone
        pw = hash_password(request.form['password'])
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE (email=%s OR phone=%s) AND password=%s",
                            (identifier, identifier, pw))
                user = cur.fetchone()
        finally:
            db.close()
        if user:
            if user.get('tag') == 'Blocked':
                flash('Your account has been blocked. Contact support.', 'error')
                return redirect(url_for('login'))
            session.update(user_id=user['id'], username=user['name'], is_admin=user['is_admin'])
            flash('Welcome back, ' + user['name'] + '!', 'success')
            return redirect(url_for('admin_dashboard') if user['is_admin'] else url_for('index'))
        flash('Invalid email/phone or password.', 'error')
    return render_template('login.html', cart_count=get_cart_count())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name  = request.form['name']
        email = request.form['email']
        phone = request.form.get('phone', '').strip()
        pw    = hash_password(request.form['password'])
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("INSERT INTO users (name, email, phone, password, tag) VALUES (%s,%s,%s,%s,'New')",
                            (name, email, phone or None, pw))
            db.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except pymysql.err.IntegrityError:
            flash('Email already registered.', 'error')
        finally:
            db.close()
    return render_template('register.html', cart_count=get_cart_count())

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ── Forgot Password ────────────────────────────────────────
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE email=%s OR phone=%s", (identifier, identifier))
                user = cur.fetchone()
            if user:
                token = secrets.token_hex(32)
                from datetime import datetime, timedelta
                expiry = datetime.now() + timedelta(hours=1)
                with db.cursor() as cur:
                    cur.execute("UPDATE users SET reset_token=%s, reset_expiry=%s WHERE id=%s",
                                (token, expiry, user['id']))
                db.commit()
                # In production send via SMS/email; here we show the reset link directly
                flash(f'Reset link (copy this): /reset-password/{token}', 'success')
            else:
                flash('No account found with that email or phone.', 'error')
        finally:
            db.close()
    return render_template('forgot_password.html', cart_count=get_cart_count())

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from datetime import datetime
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE reset_token=%s AND reset_expiry > %s",
                        (token, datetime.now()))
            user = cur.fetchone()
        if not user:
            flash('Reset link is invalid or has expired.', 'error')
            return redirect(url_for('forgot_password'))
        if request.method == 'POST':
            pw = hash_password(request.form['password'])
            with db.cursor() as cur:
                cur.execute("UPDATE users SET password=%s, reset_token=NULL, reset_expiry=NULL WHERE id=%s",
                            (pw, user['id']))
            db.commit()
            flash('Password reset successfully! Please log in.', 'success')
            return redirect(url_for('login'))
    finally:
        db.close()
    return render_template('reset_password.html', token=token, cart_count=get_cart_count())

# ─────────────────────────────────────────────
# CART
# ─────────────────────────────────────────────
@app.route('/cart')
@login_required
def cart():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT c.id, c.quantity, c.size, p.name, p.price,
                           p.original_price, p.image, p.id AS product_id
                           FROM cart c JOIN products p ON c.product_id=p.id
                           WHERE c.user_id=%s""", (session['user_id'],))
            items = cur.fetchall()
    finally:
        db.close()
    subtotal = sum(i['price'] * i['quantity'] for i in items)
    return render_template('cart.html', items=items, subtotal=subtotal, cart_count=len(items))

@app.route('/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    pid  = request.form.get('product_id', type=int)
    qty  = request.form.get('quantity', 1, type=int)
    size = request.form.get('size', 'M')
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT id, quantity FROM cart WHERE user_id=%s AND product_id=%s AND size=%s",
                        (session['user_id'], pid, size))
            ex = cur.fetchone()
            if ex:
                cur.execute("UPDATE cart SET quantity=%s WHERE id=%s", (ex['quantity'] + qty, ex['id']))
            else:
                cur.execute("INSERT INTO cart (user_id, product_id, quantity, size) VALUES (%s,%s,%s,%s)",
                            (session['user_id'], pid, qty, size))
        db.commit()
    finally:
        db.close()
    flash('Added to cart!', 'success')
    return redirect(url_for('product_detail', pid=pid))

@app.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    cid = request.form.get('cart_id', type=int)
    qty = request.form.get('quantity', type=int)
    db = get_db()
    try:
        with db.cursor() as cur:
            if qty and qty > 0:
                cur.execute("UPDATE cart SET quantity=%s WHERE id=%s AND user_id=%s", (qty, cid, session['user_id']))
            else:
                cur.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session['user_id']))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:cid>')
@login_required
def remove_from_cart(cid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session['user_id']))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('cart'))

# ── Voucher validation (AJAX) ──────────────────────────────
@app.route('/voucher/validate', methods=['POST'])
@login_required
def validate_voucher():
    from datetime import date
    code     = request.form.get('code', '').strip().upper()
    subtotal = request.form.get('subtotal', 0, type=float)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT * FROM vouchers WHERE code=%s AND is_active=1
                           AND (expires_at IS NULL OR expires_at >= %s)
                           AND (max_uses IS NULL OR used_count < max_uses)
                           AND (user_id IS NULL OR user_id=%s)""",
                        (code, date.today(), session['user_id']))
            v = cur.fetchone()
        if not v:
            return jsonify(success=False, message='Invalid or expired voucher.')
        if subtotal < float(v['min_order']):
            return jsonify(success=False, message=f"Minimum order ৳{v['min_order']:.0f} required.")
        discount = 0.0
        if v['discount_pct'] > 0:
            discount = round(subtotal * float(v['discount_pct']) / 100, 2)
        elif v['discount_amt'] > 0:
            discount = float(v['discount_amt'])
        discount = min(discount, subtotal)
        return jsonify(success=True, discount=discount, message=f'Voucher applied! -{discount:.0f}৳', voucher_id=v['id'])
    finally:
        db.close()

# ─────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    db = get_db()
    settings = get_all_settings()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT c.quantity, c.size, p.name, p.price, p.id AS product_id
                           FROM cart c JOIN products p ON c.product_id=p.id WHERE c.user_id=%s""",
                        (session['user_id'],))
            items = cur.fetchall()
        subtotal = sum(i['price'] * i['quantity'] for i in items)

        if request.method == 'POST':
            payment_method  = request.form.get('payment_method', 'cod')
            voucher_id      = request.form.get('voucher_id', type=int)
            discount_amount = request.form.get('discount_amount', 0.0, type=float)
            final_total     = max(subtotal - discount_amount, 0)
            trx_id          = request.form.get('trx_id', '').strip()

            with db.cursor() as cur2:
                cur2.execute("""INSERT INTO orders
                    (user_id, name, phone, address, total, discount_amount, payment_method)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (session['user_id'], request.form['name'], request.form['phone'],
                     request.form['address'], final_total, discount_amount, payment_method))
                oid = cur2.lastrowid
                for item in items:
                    cur2.execute("INSERT INTO order_items (order_id, product_id, quantity, size, price) VALUES (%s,%s,%s,%s,%s)",
                                 (oid, item['product_id'], item['quantity'], item['size'], item['price']))
                # Mark voucher used
                if voucher_id:
                    cur2.execute("UPDATE vouchers SET used_count=used_count+1 WHERE id=%s", (voucher_id,))
                cur2.execute("DELETE FROM cart WHERE user_id=%s", (session['user_id'],))
            db.commit()
            flash(f'Order #{oid} placed successfully! Payment: {payment_method.upper()}', 'success')
            return redirect(url_for('my_orders'))
    finally:
        db.close()
    return render_template('checkout.html', items=items, subtotal=subtotal,
                           cart_count=len(items), settings=settings)

# ─────────────────────────────────────────────
# USER ACCOUNT — Orders & Tracking
# ─────────────────────────────────────────────
@app.route('/my-orders')
@login_required
def my_orders():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC", (session['user_id'],))
            orders = cur.fetchall()
    finally:
        db.close()
    return render_template('my_orders.html', orders=orders, cart_count=get_cart_count())

@app.route('/my-orders/<int:oid>')
@login_required
def order_tracking(oid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s AND user_id=%s", (oid, session['user_id']))
            order = cur.fetchone()
            if not order:
                flash('Order not found.', 'error')
                return redirect(url_for('my_orders'))
            cur.execute("""SELECT oi.*, p.name AS product_name, p.image
                           FROM order_items oi JOIN products p ON oi.product_id=p.id
                           WHERE oi.order_id=%s""", (oid,))
            items = cur.fetchall()
    finally:
        db.close()
    return render_template('order_tracking.html', order=order, items=items, cart_count=get_cart_count())

# ─────────────────────────────────────────────
# LIVE CHAT
# ─────────────────────────────────────────────
@app.route('/chat', methods=['GET', 'POST'])
@login_required
def user_chat():
    db = get_db()
    try:
        if request.method == 'POST':
            msg = request.form.get('message', '').strip()
            if msg:
                with db.cursor() as cur:
                    cur.execute("INSERT INTO chat_messages (user_id, sender, message) VALUES (%s,'user',%s)",
                                (session['user_id'], msg))
                db.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=True)
            return redirect(url_for('user_chat'))

        with db.cursor() as cur:
            cur.execute("SELECT * FROM chat_messages WHERE user_id=%s ORDER BY created_at ASC", (session['user_id'],))
            messages = cur.fetchall()
            # mark admin messages read
            cur.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='admin'", (session['user_id'],))
        db.commit()
    finally:
        db.close()
    return render_template('chat.html', messages=messages, cart_count=get_cart_count())

@app.route('/chat/poll')
@login_required
def chat_poll():
    """AJAX: return new messages since given ID."""
    since = request.args.get('since', 0, type=int)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM chat_messages WHERE user_id=%s AND id>%s ORDER BY created_at ASC",
                        (session['user_id'], since))
            msgs = cur.fetchall()
            cur.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='admin' AND id>%s",
                        (session['user_id'], since))
        db.commit()
        return jsonify(messages=[{
            'id': m['id'],
            'sender': m['sender'],
            'message': m['message'],
            'time': m['created_at'].strftime('%H:%M') if m['created_at'] else ''
        } for m in msgs])
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════
# ADMIN — FULL CONTROL PANEL
# ═══════════════════════════════════════════════════════════

# ── Dashboard ──────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM products");       prod_count  = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) AS c FROM orders");         order_count = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) AS c FROM users");          user_count  = cur.fetchone()['c']
            cur.execute("SELECT SUM(total) AS rev FROM orders WHERE status != 'cancelled'")
            revenue = cur.fetchone()['rev'] or 0
            cur.execute("SELECT COUNT(*) AS c FROM orders WHERE status='pending'"); pending = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) AS c FROM products WHERE stock=0");        out_of_stock = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) AS c FROM products WHERE stock>0 AND stock<=5"); low_stock = cur.fetchone()['c']
            cur.execute("""SELECT o.*, u.name AS customer FROM orders o
                           JOIN users u ON o.user_id=u.id ORDER BY o.id DESC LIMIT 10""")
            recent_orders = cur.fetchall()
            unread_chats = get_unread_chat_count()
    finally:
        db.close()
    return render_template('admin/dashboard.html',
                           prod_count=prod_count, order_count=order_count,
                           user_count=user_count, revenue=revenue,
                           pending=pending, out_of_stock=out_of_stock,
                           low_stock=low_stock, recent_orders=recent_orders,
                           unread_chats=unread_chats)

# ── Products — List ────────────────────────────────────────
# ════════════════════════════════════════════════════════════
# REPLACE your existing admin_products route with this one
# (adds 'flag' filter support)
# ════════════════════════════════════════════════════════════

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
            if search:   q += " AND name LIKE %s";   p.append(f'%{search}%')
            if category: q += " AND category=%s";    p.append(category)
            if gender:   q += " AND gender=%s";      p.append(gender)
            if stock_f == 'out':  q += " AND stock=0"
            elif stock_f == 'low': q += " AND stock>0 AND stock<=5"
            if flag == 'featured': q += " AND is_featured=1"
            elif flag == 'new':    q += " AND is_new=1"
            elif flag == 'none':   q += " AND is_featured=0 AND is_new=0"
            q += " ORDER BY id DESC"
            c.execute(q, p)
            items = c.fetchall()
    finally:
        db.close()
    return render_template('admin/products.html', products=items,
                           search=search, category=category,
                           gender=gender, stock_f=stock_f, flag=flag)


# ════════════════════════════════════════════════════════════
# ADD THIS NEW ROUTE — AJAX inline toggle for product fields
# Place it just after admin_products route
# ════════════════════════════════════════════════════════════

@app.route('/admin/product/<int:pid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_product(pid):
    flag  = request.form.get('flag', '')
    value = request.form.get('value', '')
    db = get_db()
    try:
        with db.cursor() as c:
            if flag == 'featured':
                c.execute("UPDATE products SET is_featured=%s WHERE id=%s", (int(value), pid))
                msg = f"Featured {'enabled' if int(value) else 'disabled'}"
            elif flag == 'is_new':
                c.execute("UPDATE products SET is_new=%s WHERE id=%s", (int(value), pid))
                msg = f"New Arrival {'enabled' if int(value) else 'disabled'}"
            elif flag == 'stock':
                c.execute("UPDATE products SET stock=%s WHERE id=%s", (int(value), pid))
                msg = f"Stock set to {value}"
            elif flag == 'category':
                if value in ['t-shirt', 'shirt', 'pant']:
                    c.execute("UPDATE products SET category=%s WHERE id=%s", (value, pid))
                    msg = f"Category set to {value}"
                else:
                    return jsonify(success=False, message="Invalid category")
            elif flag == 'gender':
                if value in ['men', 'kid']:
                    c.execute("UPDATE products SET gender=%s WHERE id=%s", (value, pid))
                    msg = f"Gender set to {value}"
                else:
                    return jsonify(success=False, message="Invalid gender")
            else:
                return jsonify(success=False, message="Unknown field")
        db.commit()
        return jsonify(success=True, message=msg)
    except Exception as e:
        return jsonify(success=False, message=str(e))
    finally:
        db.close()

# ── Products — Add ─────────────────────────────────────────
@app.route('/admin/product/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        image_url = save_upload('image_file') or request.form.get('image_url', '').strip()
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO products
                    (name, category, gender, price, original_price, description,
                     image, sizes, stock, is_new, is_featured)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['name'], request.form['category'], request.form['gender'],
                     request.form['price'], request.form.get('original_price') or None,
                     request.form.get('description', ''), image_url,
                     request.form.get('sizes', 'S,M,L,XL'), request.form.get('stock', 0),
                     int('is_new' in request.form), int('is_featured' in request.form)))
            db.commit()
        finally:
            db.close()
        flash('Product added successfully!', 'success')
        return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html', product=None, action='Add')

# ── Products — Edit ────────────────────────────────────────
@app.route('/admin/product/edit/<int:pid>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(pid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
            product = cur.fetchone()
        if not product:
            flash('Product not found.', 'error')
            return redirect(url_for('admin_products'))
        if request.method == 'POST':
            image_url = save_upload('image_file') or request.form.get('image_url', '').strip() or product['image']
            with db.cursor() as cur:
                cur.execute("""UPDATE products SET
                    name=%s, category=%s, gender=%s, price=%s, original_price=%s,
                    description=%s, image=%s, sizes=%s, stock=%s, is_new=%s, is_featured=%s
                    WHERE id=%s""",
                    (request.form['name'], request.form['category'], request.form['gender'],
                     request.form['price'], request.form.get('original_price') or None,
                     request.form.get('description', ''), image_url,
                     request.form.get('sizes', 'S,M,L,XL'), request.form.get('stock', 0),
                     int('is_new' in request.form), int('is_featured' in request.form), pid))
            db.commit()
            flash('Product updated!', 'success')
            return redirect(url_for('admin_products'))
    finally:
        db.close()
    return render_template('admin/product_form.html', product=product, action='Edit')

@app.route('/admin/product/stock/<int:pid>', methods=['POST'])
@admin_required
def admin_update_stock(pid):
    stock = request.form.get('stock', type=int)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE products SET stock=%s WHERE id=%s", (stock, pid))
        db.commit()
    finally:
        db.close()
    flash('Stock updated!', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/product/delete/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_product(pid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM cart WHERE product_id=%s", (pid,))
            cur.execute("DELETE FROM products WHERE id=%s", (pid,))
        db.commit()
    finally:
        db.close()
    flash('Product deleted.', 'success')
    return redirect(url_for('admin_products'))

# ── Orders — List ──────────────────────────────────────────
@app.route('/admin/orders')
@admin_required
def admin_orders():
    status_f = request.args.get('status', '')
    search   = request.args.get('search', '')
    db = get_db()
    try:
        with db.cursor() as cur:
            q = "SELECT o.*, u.name AS customer FROM orders o JOIN users u ON o.user_id=u.id WHERE 1=1"
            p = []
            if status_f: q += " AND o.status=%s"; p.append(status_f)
            if search:
                q += " AND (u.name LIKE %s OR o.phone LIKE %s)"; p += [f'%{search}%', f'%{search}%']
            q += " ORDER BY o.id DESC"
            cur.execute(q, p)
            orders = cur.fetchall()
    finally:
        db.close()
    return render_template('admin/orders.html', orders=orders, status_f=status_f, search=search)

# ── Orders — Detail (with admin manual discount & notes) ───
@app.route('/admin/order/<int:oid>', methods=['GET', 'POST'])
@admin_required
def admin_order_detail(oid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT o.*, u.name AS customer, u.email FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=%s", (oid,))
            order = cur.fetchone()
            if not order:
                flash('Order not found.', 'error')
                return redirect(url_for('admin_orders'))
            cur.execute("""SELECT oi.*, p.name AS product_name, p.image
                           FROM order_items oi JOIN products p ON oi.product_id=p.id
                           WHERE oi.order_id=%s""", (oid,))
            items = cur.fetchall()

        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'update_discount':
                discount = request.form.get('discount_amount', 0.0, type=float)
                note     = request.form.get('admin_note', '').strip()
                # Recalculate total from original items
                original_total = sum(i['price'] * i['quantity'] for i in items)
                new_total = max(original_total - discount, 0)
                with db.cursor() as cur:
                    cur.execute("UPDATE orders SET discount_amount=%s, admin_note=%s, total=%s WHERE id=%s",
                                (discount, note, new_total, oid))
                db.commit()
                flash('Order discount applied!', 'success')
            elif action == 'update_tracking':
                tracking_note = request.form.get('tracking_note', '').strip()
                with db.cursor() as cur:
                    cur.execute("UPDATE orders SET tracking_note=%s WHERE id=%s", (tracking_note, oid))
                db.commit()
                flash('Tracking note updated!', 'success')
            return redirect(url_for('admin_order_detail', oid=oid))
    finally:
        db.close()
    return render_template('admin/order_detail.html', order=order, items=items)

# ── Orders — Update Status ─────────────────────────────────
@app.route('/admin/order/<int:oid>/status', methods=['POST'])
@admin_required
def admin_update_order_status(oid):
    status = request.form['status']
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, oid))
        db.commit()
    finally:
        db.close()
    flash('Order status updated!', 'success')
    return redirect(request.form.get('next', url_for('admin_orders')))

@app.route('/admin/order/delete/<int:oid>', methods=['POST'])
@admin_required
def admin_delete_order(oid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM order_items WHERE order_id=%s", (oid,))
            cur.execute("DELETE FROM orders WHERE id=%s", (oid,))
        db.commit()
    finally:
        db.close()
    flash('Order deleted.', 'success')
    return redirect(url_for('admin_orders'))

# ── Users — List (with rating & tag) ───────────────────────
@app.route('/admin/users')
@admin_required
def admin_users():
    search = request.args.get('search', '')
    db = get_db()
    try:
        with db.cursor() as cur:
            q = "SELECT u.*, (SELECT COUNT(*) FROM orders WHERE user_id=u.id) AS order_count FROM users u WHERE 1=1"
            p = []
            if search:
                q += " AND (u.name LIKE %s OR u.email LIKE %s)"; p += [f'%{search}%', f'%{search}%']
            q += " ORDER BY u.id DESC"
            cur.execute(q, p)
            users = cur.fetchall()
    finally:
        db.close()
    return render_template('admin/users.html', users=users, search=search)

@app.route('/admin/user/<int:uid>/set-tag', methods=['POST'])
@admin_required
def admin_set_user_tag(uid):
    tag    = request.form.get('tag', 'New')
    rating = request.form.get('rating', type=int)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE users SET tag=%s, rating=%s WHERE id=%s", (tag, rating, uid))
        db.commit()
    finally:
        db.close()
    flash('User tag/rating updated.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:uid>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    if uid == session['user_id']:
        flash("You can't change your own admin status.", 'error')
        return redirect(url_for('admin_users'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE users SET is_admin = NOT is_admin WHERE id=%s", (uid,))
        db.commit()
    finally:
        db.close()
    flash('User role updated.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/delete/<int:uid>', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid == session['user_id']:
        flash("You can't delete yourself.", 'error')
        return redirect(url_for('admin_users'))
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM cart WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        db.commit()
    finally:
        db.close()
    flash('User deleted.', 'success')
    return redirect(url_for('admin_users'))

# ── Vouchers ───────────────────────────────────────────────
@app.route('/admin/vouchers')
@admin_required
def admin_vouchers():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT v.*, u.name AS user_name FROM vouchers v
                           LEFT JOIN users u ON v.user_id=u.id ORDER BY v.id DESC""")
            vouchers = cur.fetchall()
            cur.execute("SELECT id, name FROM users ORDER BY name")
            users = cur.fetchall()
    finally:
        db.close()
    return render_template('admin/vouchers.html', vouchers=vouchers, users=users)

@app.route('/admin/vouchers/add', methods=['POST'])
@admin_required
def admin_add_voucher():
    code         = request.form.get('code', '').strip().upper()
    discount_pct = request.form.get('discount_pct', 0.0, type=float)
    discount_amt = request.form.get('discount_amt', 0.0, type=float)
    min_order    = request.form.get('min_order', 0.0, type=float)
    max_uses     = request.form.get('max_uses', type=int)
    user_id      = request.form.get('user_id', type=int)
    expires_at   = request.form.get('expires_at') or None
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""INSERT INTO vouchers (code, discount_pct, discount_amt, min_order, max_uses, user_id, expires_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (code, discount_pct, discount_amt, min_order, max_uses, user_id, expires_at))
        db.commit()
        flash('Voucher created!', 'success')
    except pymysql.err.IntegrityError:
        flash('Voucher code already exists.', 'error')
    finally:
        db.close()
    return redirect(url_for('admin_vouchers'))

@app.route('/admin/vouchers/delete/<int:vid>', methods=['POST'])
@admin_required
def admin_delete_voucher(vid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM vouchers WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()
    flash('Voucher deleted.', 'success')
    return redirect(url_for('admin_vouchers'))

@app.route('/admin/vouchers/toggle/<int:vid>', methods=['POST'])
@admin_required
def admin_toggle_voucher(vid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE vouchers SET is_active = NOT is_active WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()
    return redirect(url_for('admin_vouchers'))

# ── Banner / Site Settings ─────────────────────────────────
@app.route('/admin/banners', methods=['GET', 'POST'])
@admin_required
def admin_banners():
    if request.method == 'POST':
        db = get_db()
        try:
            with db.cursor() as cur:
                for key in ['announcement_bar', 'hero_title', 'hero_subtitle', 'hero_badge',
                            'feature_badge_1', 'feature_badge_2', 'feature_badge_3',
                            'bkash_number', 'nagad_number', 'rocket_number', 'payment_instructions']:
                    val = request.form.get(key, '').strip()
                    cur.execute("INSERT INTO site_settings (setting_key, setting_value) VALUES (%s,%s) "
                                "ON DUPLICATE KEY UPDATE setting_value=%s", (key, val, val))
            db.commit()
        finally:
            db.close()
        flash('Banner & payment settings saved!', 'success')
        return redirect(url_for('admin_banners'))
    settings = get_all_settings()
    return render_template('admin/banners.html', settings=settings)
# ════════════════════════════════════════════════════
# ADD THIS ROUTE to app.py
# Place it just before: @app.route('/admin/banners' ...)
# ════════════════════════════════════════════════════

@app.route('/admin/homepage', methods=['GET', 'POST'])
@admin_required
def admin_homepage():
    if request.method == 'POST':
        db = get_db()
        try:
            with db.cursor() as c:
                keys = [
                    'section_cat_title','section_cat_sub',
                    'section_featured_title','section_featured_sub',
                    'section_new_title','section_new_sub',
                ]
                # category cards
                for i in range(1, 7):
                    keys += [f'cat_{i}_label', f'cat_{i}_sub', f'cat_{i}_url', f'cat_{i}_img']
                # promo banners
                for i in range(1, 3):
                    keys += [f'promo_{i}_title', f'promo_{i}_text', f'promo_{i}_btn',
                             f'promo_{i}_url', f'promo_{i}_img']
                for key in keys:
                    val = request.form.get(key, '').strip()
                    c.execute(
                        "INSERT INTO site_settings (setting_key, setting_value) VALUES (%s,%s) "
                        "ON DUPLICATE KEY UPDATE setting_value=%s",
                        (key, val, val)
                    )
            db.commit()
        finally:
            db.close()
        flash('Homepage settings saved!', 'success')
        return redirect(url_for('admin_homepage'))
    return render_template('admin/homepage.html', s=get_all_settings())


# ════════════════════════════════════════════════════
# ADD THIS LINK to templates/admin/base_admin.html
# Place it inside the <nav class="admin-nav"> block,
# after the "Banners & Pay" link:
# ════════════════════════════════════════════════════

"""
<a href="{{ url_for('admin_homepage') }}" {% if request.endpoint=='admin_homepage' %}class="active"{% endif %}>
  <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
    <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
    <polyline points="9 22 9 12 15 12 15 22"/>
  </svg>
  <span>Homepage</span>
</a>
"""
# ── Admin Chat ─────────────────────────────────────────────
@app.route('/admin/chat')
@admin_required
def admin_chat_list():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""SELECT u.id, u.name, u.email,
                           (SELECT COUNT(*) FROM chat_messages WHERE user_id=u.id AND sender='user' AND is_read=0) AS unread,
                           (SELECT MAX(created_at) FROM chat_messages WHERE user_id=u.id) AS last_msg
                           FROM users u
                           WHERE EXISTS (SELECT 1 FROM chat_messages WHERE user_id=u.id)
                           ORDER BY last_msg DESC""")
            chats = cur.fetchall()
    finally:
        db.close()
    return render_template('admin/chat_list.html', chats=chats)

@app.route('/admin/chat/<int:uid>', methods=['GET', 'POST'])
@admin_required
def admin_chat_user(uid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            user = cur.fetchone()
            if not user:
                return redirect(url_for('admin_chat_list'))

        if request.method == 'POST':
            msg = request.form.get('message', '').strip()
            if msg:
                with db.cursor() as cur:
                    cur.execute("INSERT INTO chat_messages (user_id, sender, message) VALUES (%s,'admin',%s)",
                                (uid, msg))
                db.commit()
            return redirect(url_for('admin_chat_user', uid=uid))

        with db.cursor() as cur:
            cur.execute("SELECT * FROM chat_messages WHERE user_id=%s ORDER BY created_at ASC", (uid,))
            messages = cur.fetchall()
            # mark user messages read
            cur.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='user'", (uid,))
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
        with db.cursor() as cur:
            cur.execute("SELECT * FROM chat_messages WHERE user_id=%s AND id>%s ORDER BY created_at ASC",
                        (uid, since))
            msgs = cur.fetchall()
            cur.execute("UPDATE chat_messages SET is_read=1 WHERE user_id=%s AND sender='user' AND id>%s",
                        (uid, since))
        db.commit()
        return jsonify(messages=[{
            'id': m['id'],
            'sender': m['sender'],
            'message': m['message'],
            'time': m['created_at'].strftime('%H:%M') if m['created_at'] else ''
        } for m in msgs])
    finally:
        db.close()

# ── Settings ───────────────────────────────────────────────
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old_pw = hash_password(request.form['old_password'])
            new_pw = hash_password(request.form['new_password'])
            db = get_db()
            try:
                with db.cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE id=%s AND password=%s", (session['user_id'], old_pw))
                    if cur.fetchone():
                        cur.execute("UPDATE users SET password=%s WHERE id=%s", (new_pw, session['user_id']))
                        db.commit()
                        flash('Password changed successfully!', 'success')
                    else:
                        flash('Current password is incorrect.', 'error')
            finally:
                db.close()
        elif action == 'change_name':
            name = request.form.get('name', '').strip()
            if name:
                db = get_db()
                try:
                    with db.cursor() as cur:
                        cur.execute("UPDATE users SET name=%s WHERE id=%s", (name, session['user_id']))
                    db.commit()
                    session['username'] = name
                    flash('Name updated!', 'success')
                finally:
                    db.close()
        return redirect(url_for('admin_settings'))
    return render_template('admin/settings.html')

# ─────────────────────────────────────────────
if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True, host='localhost', port=5000)