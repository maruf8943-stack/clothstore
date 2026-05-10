-- =============================================
-- ClothStore v3 — PostgreSQL Setup Script
-- Run this via: python init_db.py
-- OR paste in Render's PostgreSQL shell
-- =============================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(100)  NOT NULL,
    email      VARCHAR(150)  UNIQUE NOT NULL,
    password   VARCHAR(255)  NOT NULL,
    phone      VARCHAR(20)   DEFAULT NULL,
    is_admin   SMALLINT      DEFAULT 0,
    tag        VARCHAR(30)   DEFAULT 'New',
    rating     SMALLINT      DEFAULT NULL,
    reset_token VARCHAR(64)  DEFAULT NULL,
    reset_expiry TIMESTAMP   DEFAULT NULL,
    created_at TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(200)    NOT NULL,
    category       VARCHAR(50)     NOT NULL,
    gender         VARCHAR(10)     NOT NULL,
    price          DECIMAL(10,2)   NOT NULL,
    original_price DECIMAL(10,2)   DEFAULT NULL,
    description    TEXT,
    image          VARCHAR(500),
    sizes          VARCHAR(100)    DEFAULT 'S,M,L,XL',
    stock          INT             DEFAULT 0,
    is_new         SMALLINT        DEFAULT 0,
    is_featured    SMALLINT        DEFAULT 0,
    created_at     TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- Cart table
CREATE TABLE IF NOT EXISTS cart (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INT         DEFAULT 1,
    size       VARCHAR(10) DEFAULT 'M'
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    user_id         INT          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    phone           VARCHAR(20),
    address         TEXT         NOT NULL,
    total           DECIMAL(10,2) NOT NULL,
    discount_amount DECIMAL(10,2) DEFAULT 0,
    admin_note      TEXT          DEFAULT NULL,
    tracking_note   VARCHAR(500)  DEFAULT NULL,
    payment_method  VARCHAR(30)   DEFAULT 'cod',
    status          VARCHAR(20)   DEFAULT 'pending',
    created_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- Order Items table
CREATE TABLE IF NOT EXISTS order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INT          NOT NULL REFERENCES orders(id)   ON DELETE CASCADE,
    product_id INT          NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INT          NOT NULL,
    size       VARCHAR(10),
    price      DECIMAL(10,2) NOT NULL
);

-- Vouchers table
CREATE TABLE IF NOT EXISTS vouchers (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(50)   UNIQUE NOT NULL,
    discount_pct DECIMAL(5,2)  DEFAULT 0,
    discount_amt DECIMAL(10,2) DEFAULT 0,
    min_order    DECIMAL(10,2) DEFAULT 0,
    max_uses     INT           DEFAULT NULL,
    used_count   INT           DEFAULT 0,
    user_id      INT           DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
    is_active    SMALLINT      DEFAULT 1,
    expires_at   DATE          DEFAULT NULL,
    created_at   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- Site Settings table
CREATE TABLE IF NOT EXISTS site_settings (
    setting_key   VARCHAR(100) PRIMARY KEY,
    setting_value TEXT,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chat Messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id         SERIAL PRIMARY KEY,
    user_id    INT          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sender     VARCHAR(10)  NOT NULL CHECK (sender IN ('user','admin')),
    message    TEXT         NOT NULL,
    is_read    SMALLINT     DEFAULT 0,
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- Reviews table
CREATE TABLE IF NOT EXISTS reviews (
    id          SERIAL PRIMARY KEY,
    product_id  INT          NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id     INT          NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    order_id    INT          DEFAULT NULL,
    rating      SMALLINT     NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title       VARCHAR(200) DEFAULT '',
    body        TEXT         DEFAULT '',
    media_1     VARCHAR(500) DEFAULT NULL,
    media_2     VARCHAR(500) DEFAULT NULL,
    media_3     VARCHAR(500) DEFAULT NULL,
    is_approved SMALLINT     DEFAULT 1,
    created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, user_id)
);

-- ─────────────────────────────────────────────
-- DEFAULT SITE SETTINGS
-- ─────────────────────────────────────────────
INSERT INTO site_settings (setting_key, setting_value) VALUES
('announcement_bar',     'Free delivery on orders above ৳2,000 | New arrivals every week!'),
('hero_title',           'Dress Bold.'),
('hero_subtitle',        'Look Sharp.'),
('hero_badge',           '🔥 New Season'),
('hero_stat_1_num',      '500+'),
('hero_stat_1_label',    'Products'),
('hero_stat_2_num',      '50K+'),
('hero_stat_2_label',    'Happy Customers'),
('hero_stat_3_num',      '100%'),
('hero_stat_3_label',    'Quality'),
('promo_strip_1',        'Free Delivery above ৳2,000'),
('promo_strip_2',        'Easy 7-Day Returns'),
('promo_strip_3',        'Authentic Products'),
('promo_strip_4',        '24/7 Support'),
('feature_badge_1',      '✅ Premium Quality'),
('feature_badge_2',      '🚚 Fast Delivery'),
('feature_badge_3',      '↩️ Easy Returns'),
('bkash_number',         '01307461999'),
('nagad_number',         '01307461999'),
('rocket_number',        '01307461999'),
('payment_instructions', 'Send money to the number above and enter your TrxID at checkout.'),
('section_cat_title',    'Shop by Category'),
('section_cat_sub',      'Find what fits your style'),
('section_featured_title','Featured Products'),
('section_featured_sub', 'Handpicked just for you'),
('section_new_title',    'New Arrivals'),
('section_new_sub',      'Just landed this week')
ON CONFLICT (setting_key) DO NOTHING;

-- ─────────────────────────────────────────────
-- ADMIN USER
-- Login: admin@clothstore.com | Password: admin123
-- ─────────────────────────────────────────────
INSERT INTO users (name, email, password, is_admin, tag)
VALUES ('Admin', 'admin@clothstore.com',
        '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9',
        1, 'VIP')
ON CONFLICT (email) DO NOTHING;

-- ─────────────────────────────────────────────
-- SAMPLE PRODUCTS
-- ─────────────────────────────────────────────
INSERT INTO products (name, category, gender, price, original_price, description, image, sizes, stock, is_new, is_featured) VALUES
('Urban Fit Graphic Tee',   't-shirt','men',599,799,  'Premium cotton graphic t-shirt.','https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=500','S,M,L,XL,XXL',50,1,1),
('Classic White Polo Tee',  't-shirt','men',699,NULL, 'Timeless white polo t-shirt.','https://images.unsplash.com/photo-1586363104862-3a5e2ab60d99?w=500','S,M,L,XL',40,0,1),
('Striped Casual Tee',      't-shirt','men',549,649,  'Bold horizontal stripes.','https://images.unsplash.com/photo-1503341504253-dff4815485f1?w=500','S,M,L,XL,XXL',35,1,0),
('Black Essential Tee',     't-shirt','men',499,NULL, 'The perfect black t-shirt.','https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?w=500','S,M,L,XL,XXL',60,0,1),
('Oxford Button-Down Shirt','shirt',  'men',1299,1599,'Classic oxford cloth shirt.','https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=500','S,M,L,XL',30,1,1),
('Linen Summer Shirt',      'shirt',  'men',1099,NULL,'Breathable linen shirt.','https://images.unsplash.com/photo-1602810319250-a663f0af2f75?w=500','S,M,L,XL,XXL',25,1,0),
('Slim Fit Check Shirt',    'shirt',  'men',999,1199, 'Modern slim fit check shirt.','https://images.unsplash.com/photo-1604695573706-53170668f6a6?w=500','S,M,L,XL',20,0,1),
('Solid Navy Formal Shirt', 'shirt',  'men',1199,NULL,'Solid navy formal shirt.','https://images.unsplash.com/photo-1607345366928-199ea26cfe3e?w=500','S,M,L,XL,XXL',45,0,0),
('Slim Chino Pants',        'pant',   'men',1499,1799,'Classic slim-fit chino pants.','https://images.unsplash.com/photo-1473966968600-fa801b869a1a?w=500','28,30,32,34,36',30,1,1),
('Cargo Utility Pants',     'pant',   'men',1699,NULL,'Heavy-duty cargo pants.','https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=500','28,30,32,34,36',25,0,0),
('Formal Dress Pants',      'pant',   'men',1899,2199,'Tailored formal dress pants.','https://images.unsplash.com/photo-1594938298603-c8148c4bff72?w=500','28,30,32,34,36,38',20,0,1),
('Jogger Pants Casual',     'pant',   'men',999,1199, 'Comfortable jogger pants.','https://images.unsplash.com/photo-1552902865-b72c031ac5ea?w=500','S,M,L,XL,XXL',40,1,0),
('Kids Dino Print Tee',     't-shirt','kid',349,449,  'Fun dinosaur print t-shirt.','https://images.unsplash.com/photo-1519278409-1f56fdda7fe5?w=500','4Y,6Y,8Y,10Y,12Y',50,1,1),
('Kids Striped Sport Tee',  't-shirt','kid',299,NULL, 'Sporty striped t-shirt.','https://images.unsplash.com/photo-1622290291468-a28f7a7dc6a8?w=500','4Y,6Y,8Y,10Y,12Y',45,0,0),
('Kids Solid Colour Tee',   't-shirt','kid',499,599,  'Pack of two solid colour tees.','https://images.unsplash.com/photo-1519185007994-4490c53b4b41?w=500','4Y,6Y,8Y,10Y',35,1,1),
('Kids Check Casual Shirt', 'shirt',  'kid',549,699,  'Adorable check shirt for kids.','https://images.unsplash.com/photo-1533827432537-1f1e5b0f5e1a?w=500','4Y,6Y,8Y,10Y,12Y',30,1,0),
('Kids Festive Shirt',      'shirt',  'kid',799,999,  'Special occasion shirt.','https://images.unsplash.com/photo-1595590424283-b8f17842773f?w=500','4Y,6Y,8Y,10Y,12Y',20,1,1),
('Kids Jogger Pants',       'pant',   'kid',449,549,  'Comfortable jogger pants.','https://images.unsplash.com/photo-1518717758536-85ae29035b6d?w=500','4Y,6Y,8Y,10Y,12Y',40,0,1),
('Kids Chino Pants',        'pant',   'kid',599,NULL, 'Smart chino pants for kids.','https://images.unsplash.com/photo-1519185007994-4490c53b4b41?w=500','4Y,6Y,8Y,10Y',30,1,0)
ON CONFLICT DO NOTHING;