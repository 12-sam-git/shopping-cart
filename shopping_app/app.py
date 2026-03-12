from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient
from flask import Flask, render_template, request, redirect
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
import os
import psycopg2

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


connection_string = "DefaultEndpointsProtocol=https;AccountName=ecomimage;AccountKey=ksbZZEqJZPJ9spBcO6Q/pHvewoHo5WUh6GY5bPO2y9R7UIDkf1CFPHHGC5RQll9sfj4+DOHStd7O+ASt2hkK7w==;EndpointSuffix=core.windows.net"

blob_service_client = BlobServiceClient.from_connection_string(connection_string)

container_name = "productimages"
container_client = blob_service_client.get_container_client(container_name)

queue_client = QueueClient.from_connection_string(
    connection_string,
    "storage-queue"
)


# MongoDB connection
client = MongoClient("mongodb://localhost:27017/")
db = client["shopping_db"]
cart_collection = db["cart"]



pg_conn = psycopg2.connect(
    host="localhost",
    database="shopping",
    user="postgres",
    password="welcome@1234"
)

pg_cursor = pg_conn.cursor()




# Purchase history (temporary until PostgreSQL)
purchase_history = []


# Load products
with open("products.json") as f:
    products = json.load(f)


# HOME PAGE
@app.route("/")
def home():
    return render_template("index.html", products=products)


# TEXT SEARCH
@app.route("/search")
def search():

    query = request.args.get("query", "").lower()

    # SEND QUEUE MESSAGE
    queue_client.send_message(f"Search query: {query}")

    filtered = [p for p in products if query in p["name"].lower()]

    return render_template("index.html", products=filtered)


# IMAGE SEARCH
@app.route("/upload", methods=["POST"])
def upload():

    image = request.files["image"]

    if image.filename != "":

        filename = image.filename.lower()

        # Upload image to Azure Blob Storage
        blob_client = container_client.get_blob_client(filename)

        blob_client.upload_blob(image, overwrite=True)

        # Send message to Storage Queue
        queue_client.send_message(f"Image uploaded: {filename}")

        # Simulate image search
        keyword = filename.split(".")[0]

        results = []

        for p in products:
            if keyword in p["name"].lower():
                results.append(p)

        if not results:
            results = products

        return render_template("index.html", products=results)

    return redirect("/")


# ADD TO CART (store in MongoDB)
# ADD TO CART (store in MongoDB)
@app.route("/add_to_cart/<int:pid>")
def add_to_cart(pid):

    for p in products:
        if p["id"] == pid:

            item = p.copy()

            # remove _id if exists
            if "_id" in item:
                del item["_id"]

            cart_collection.insert_one(item)

            # SEND QUEUE MESSAGE
            queue_client.send_message(f"Added to cart: {p['name']}")

    return redirect("/cart")

# CART PAGE
@app.route("/cart")
def cart_page():

    cart_items = list(cart_collection.find())

    return render_template("cart.html", cart=cart_items)


# REMOVE ITEM
@app.route("/remove/<id>")
def remove(id):

    item = cart_collection.find_one({"_id": ObjectId(id)})

    if item:
        queue_client.send_message(f"Removed from cart: {item['name']}")

    cart_collection.delete_one({"_id": ObjectId(id)})

    return redirect("/cart")

# PURCHASE SELECTED ITEMS
@app.route("/purchase_selected", methods=["POST"])
def purchase_selected():

    selected_ids = request.form.getlist("selected_items")

    purchased_items = []

    for sid in selected_ids:

        item = cart_collection.find_one({"_id": ObjectId(sid)})

        if item:

            purchased_items.append(item)

            # SEND QUEUE MESSAGE
            queue_client.send_message(f"Purchase completed: {item['name']}")

            # INSERT INTO POSTGRESQL
            pg_cursor.execute(
                "INSERT INTO purchases(product_id, name, price) VALUES (%s, %s, %s)",
                (item["id"], item["name"], item["price"])
            )

            pg_conn.commit()

            cart_collection.delete_one({"_id": ObjectId(sid)})

    return render_template("purchase.html", items=purchased_items)


# PURCHASE HISTORY PAGE
@app.route("/history")
def history():

    pg_cursor.execute("SELECT name, price FROM purchases")

    rows = pg_cursor.fetchall()

    items = []

    for r in rows:
        items.append({
            "name": r[0],
            "price": r[1]
        })

    return render_template("history.html", items=items)

if __name__ == "__main__":
    app.run(debug=True)