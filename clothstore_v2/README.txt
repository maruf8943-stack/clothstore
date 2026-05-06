====================================================
  ClothStore v2 — Full Admin Control Panel
====================================================

WHAT'S NEW IN THIS VERSION
────────────────────────────
✅ Edit any product (name, price, image, stock, sizes, etc.)
✅ Upload product images from your computer (JPG/PNG/WebP)
✅ Quick stock update inline in the products table
✅ Filter products by category, gender, stock level, name
✅ Full order details page with customer info
✅ Delete orders
✅ Manage users — make/remove admin, delete users
✅ Settings — change your name and password
✅ Better dashboard with revenue, pending orders, low stock alerts

ADMIN PANEL SECTIONS
─────────────────────
  /admin              Dashboard
  /admin/products     All Products (add, edit, delete, stock)
  /admin/product/add  Add New Product
  /admin/orders       All Orders (filter, status, detail, delete)
  /admin/users        All Users (roles, delete)
  /admin/settings     Change name & password

SETUP (same as before)
────────────────────────
1. Run clothstore_mysql.sql in MySQL Workbench
2. Set your MySQL password in app.py (DB_CONFIG)
3. pip install -r requirements.txt
4. python app.py
5. Open http://localhost:5000

Admin: admin@clothstore.com / admin123
====================================================
