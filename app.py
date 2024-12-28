from flask import Flask, jsonify
from flask_cors import CORS
import socket
import datetime
import re
import time
import pymysql

app = Flask(__name__)
CORS(app)

# Database configuration
DB_HOST = "192.168.48.34"  # Replace with your database host
DB_USER = "root"           # Replace with your database username
DB_PASSWORD = "aman"       # Replace with your database password
DB_NAME = "post_orders_db" # Replace with your database name

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
    )

def initialize_network_connection(ip, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)  # Timeout to prevent infinite waits
        s.connect((ip, port))
        print(f"Connected to RFID reader at {ip}:{port}")
        return s
    except Exception as e:
        print(f"Error connecting to RFID reader: {e}")
        return None

def clean_rfid_data(data_line, tag_length=16):
    """
    Cleans the raw data line and extracts the TagID.
    """
    try:
        clean_line = re.sub(r'[^\x20-\x7E]', '', data_line)
        if len(clean_line) >= tag_length:
            return clean_line[:tag_length]
        return None
    except Exception as e:
        print(f"Failed to clean data line: {data_line} - Error: {e}")
        return None

def is_hex_string(s):
    return all(c in "0123456789ABCDEFabcdef" for c in s)

def hex_to_ascii(hex_string):
    try:
        return bytes.fromhex(hex_string).decode('ascii')
    except ValueError:
        return None

def get_details_from_db(stamp_id):
    """
    Fetches details for the given stamp_id from the orders table.
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT sender_name, sender_address, sender_pincode, sender_mobile,
                   receiver_name, receiver_address, receiver_pincode, receiver_mobile
            FROM orders
            WHERE stamp_id = %s
            """
            cursor.execute(sql, (stamp_id,))
            result = cursor.fetchone()
            if result:
                return {
                    "SenderName": result.get("sender_name"),
                    "SenderAddress": result.get("sender_address"),
                    "SenderPincode": result.get("sender_pincode"),
                    "SenderMobile": result.get("sender_mobile"),
                    "ReceiverName": result.get("receiver_name"),
                    "ReceiverAddress": result.get("receiver_address"),
                    "ReceiverPincode": result.get("receiver_pincode"),
                    "ReceiverMobile": result.get("receiver_mobile"),
                }
            return None
    except Exception as e:
        print(f"Error fetching details from DB: {e}")
        return None
    finally:
        connection.close()

def format_time_field(field):
    if isinstance(field, datetime.timedelta):
        total_seconds = int(field.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    elif isinstance(field, datetime.time):
        return field.isoformat()
    elif isinstance(field, str):
        return field
    else:
        return "N/A"

def update_taglog_entry(stamp_id, operation, location=None):
    """
    Updates the TagLog table for a given stamp_id based on the operation (IN/OUT).
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # Check if the stamp_id already exists in TagLog
            sql_check = "SELECT * FROM TagLog WHERE stamp_id = %s"
            cursor.execute(sql_check, (stamp_id,))
            existing = cursor.fetchone()

            current_datetime = datetime.datetime.now()
            in_date = current_datetime.date().isoformat()
            in_time = current_datetime.time().isoformat()
            out_date = current_datetime.date().isoformat()
            out_time = current_datetime.time().isoformat()

            if operation == "IN":
                if existing:
                    # Update existing record with IN details
                    sql_update = """
                    UPDATE TagLog
                    SET Location = %s, InDate = %s, InTime = %s
                    WHERE stamp_id = %s
                    """
                    cursor.execute(sql_update, (location, in_date, in_time, stamp_id))
                else:
                    # Insert new record with IN details
                    sql_insert = """
                    INSERT INTO TagLog (stamp_id, Location, InDate, InTime)
                    VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(sql_insert, (stamp_id, location, in_date, in_time))
                connection.commit()
                print(f"Logged IN for stamp_id: {stamp_id}")
            elif operation == "OUT":
                if existing:
                    # Update existing record with OUT details
                    sql_update = """
                    UPDATE TagLog
                    SET OutDate = %s, OutTime = %s
                    WHERE stamp_id = %s
                    """
                    cursor.execute(sql_update, (out_date, out_time, stamp_id))
                    connection.commit()
                    print(f"Logged OUT for stamp_id: {stamp_id}")
                else:
                    # Handle case where OUT is attempted without prior IN
                    print(f"No existing IN record for stamp_id: {stamp_id}")
                    return {"error": "No existing IN record for this TagID."}, 400
    except Exception as e:
        print(f"Error updating TagLog: {e}")
        return {"error": "Database error."}, 500
    finally:
        connection.close()
    return {"message": f"{operation} logged successfully."}, 200

@app.route("/log_in", methods=["POST"])
def log_in():
    tag_ids, error = scan_rfid()  # Scan multiple tags
    if error:
        return jsonify(error), 500

    response_data = []
    for stamp_id in tag_ids:
        details = get_details_from_db(stamp_id)
        scan_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        location = "Jaipur Warehouse"  # You can modify this to be dynamic if needed

        # Update TagLog with IN details
        response, status = update_taglog_entry(stamp_id, "IN", location)
        if status != 200:
            return jsonify(response), status

        # Append the data for this tag to the response
        if details:
            response_data.append({
                "TagID": stamp_id,
                **details,
                "InDate": scan_time.split(" ")[0],
                "InTime": scan_time.split(" ")[1],
                "Location": location,
                "OutDate": "N/A",
                "OutTime": "N/A"
            })
        else:
            response_data.append({
                "TagID": stamp_id,
                "SenderName": "No data available",
                "SenderAddress": "No data available",
                "SenderPincode": "No data available",
                "SenderMobile": "No data available",
                "ReceiverName": "No data available",
                "ReceiverAddress": "No data available",
                "ReceiverPincode": "No data available",
                "ReceiverMobile": "No data available",
                "InDate": scan_time.split(" ")[0],
                "InTime": scan_time.split(" ")[1],
                "OutDate": "N/A",
                "OutTime": "N/A",
                "Location": location
            })

    return jsonify(response_data), 200


@app.route("/log_out", methods=["POST"])
def log_out():
    tag_ids, error = scan_rfid()  # Scan multiple tags
    if error:
        return jsonify(error), 500

    response_data = []
    for stamp_id in tag_ids:
        # Update TagLog with OUT details
        response, status = update_taglog_entry(stamp_id, "OUT")
        if status != 200:
            return jsonify(response), status

        # Fetch updated TagLog details
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                sql = "SELECT * FROM TagLog WHERE stamp_id = %s"
                cursor.execute(sql, (stamp_id,))
                result = cursor.fetchone()
                if result:
                    details = get_details_from_db(stamp_id)
                    if details:
                        response_data.append({
                            "TagID": stamp_id,
                            **details,
                            "InDate": result.get("InDate").isoformat() if result.get("InDate") else "N/A",
                            "InTime": format_time_field(result.get("InTime")),
                            "OutDate": result.get("OutDate").isoformat() if result.get("OutDate") else "N/A",
                            "OutTime": format_time_field(result.get("OutTime")),
                            "Location": result.get("Location") or "N/A"
                        })
                    else:
                        response_data.append({
                            "TagID": stamp_id,
                            "SenderName": "No data available",
                            "SenderAddress": "No data available",
                            "SenderPincode": "No data available",
                            "SenderMobile": "No data available",
                            "ReceiverName": "No data available",
                            "ReceiverAddress": "No data available",
                            "ReceiverPincode": "No data available",
                            "ReceiverMobile": "No data available",
                            "InDate": result.get("InDate").isoformat() if result.get("InDate") else "N/A",
                            "InTime": format_time_field(result.get("InTime")),
                            "OutDate": result.get("OutDate").isoformat() if result.get("OutDate") else "N/A",
                            "OutTime": format_time_field(result.get("OutTime")),
                            "Location": result.get("Location") or "N/A"
                        })
        except Exception as e:
            print(f"Error fetching TagLog details: {e}")
            return jsonify({"error": "Database error."}), 500
        finally:
            connection.close()

    return jsonify(response_data), 200


def scan_rfid():
    ip_address = "192.168.1.250"
    port = 60000
    reader_socket = initialize_network_connection(ip_address, port)
    if not reader_socket:
        return None, {"error": "Failed to connect to RFID reader"}, 500

    scan_duration = 5  # seconds
    start_time = time.time()
    unique_tags = set()

    while time.time() - start_time < scan_duration:
        try:
            raw_data = reader_socket.recv(1024).decode('utf-8', errors='ignore').strip()
            if raw_data:
                print(f"Raw Data: {raw_data}")
                tag_id_hex = clean_rfid_data(raw_data)
                if tag_id_hex and len(tag_id_hex) == 16 and is_hex_string(tag_id_hex):
                    stamp_id = hex_to_ascii(tag_id_hex)
                    if stamp_id:
                        unique_tags.add(stamp_id)
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Error reading data: {e}")
            break

    reader_socket.close()
    if unique_tags:
        return list(unique_tags), None
    else:
        return None, {"error": "No valid tags scanned."}, 400

if __name__ == "__main__":
    app.run(debug=True)
