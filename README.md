# Smart Inventory Management System

## Features
- Flask + MySQL
- Kaggle CSV import
- Dashboard and product CRUD
- Low-stock and out-of-stock notifications
- Restocking and stock movement history
- Rule-based virtual assistant

## 1. Install prerequisites
Install Python 3.10+ and MySQL Server. Create a virtual environment:

Windows:
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If `mysqlclient` fails to install on Windows, install the required Microsoft C++ Build Tools/MySQL development dependencies, or ask to adapt the project to `PyMySQL`.

## 2. Create database
Open MySQL Workbench, open `schema.sql`, and execute the script.
Alternatively:
```bash
mysql -u root -p < schema.sql
```

## 3. Configure database credentials
Set environment variables before running the app (Windows Command Prompt example):
```bat
set MYSQL_HOST=localhost
set MYSQL_USER=root
set MYSQL_PASSWORD=your_mysql_password
set MYSQL_DB=smart_inventory
set FLASK_SECRET_KEY=change_this_to_a_long_random_value
```
Do not put a real password into a public GitHub repository.

## 4. Download the Kaggle dataset
Dataset page:
https://www.kaggle.com/datasets/anirudhchauhan/retail-store-inventory-forecasting-dataset

Download and unzip `retail_store_inventory.csv` to your computer.

## 5. Run
```bash
python app.py
```
Open http://127.0.0.1:5000 in your browser.

## 6. Import data
Click Import CSV and choose `retail_store_inventory.csv`.
The dataset has daily history. This app imports the latest row per Store ID + Product ID into the current products table; it does not import every historical day as a separate product. It uses the Product ID as a name because the CSV does not have a human-friendly product-name field.

## Notes
- Default reorder level is 10 and can be edited for each product.
- Notifications are in-app only. Email notifications can be added as a separate enhancement.
- This starter project does not include login/authentication. Add authentication before exposing it publicly.
- For production use, add CSRF protection, authorization, migrations, and stronger validation.
