import base64
import io
import sqlite3
import json # Meskipun tidak langsung digunakan untuk encoding numpy, ini bisa berguna
import numpy as np
import pandas as pd  # Import modul pandas
from datetime import datetime  # Import modul datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_session import Session
# from openpyxl import Workbook # Tidak digunakan langsung untuk menyimpan Excel
# from openpyxl.utils import get_column_letter # Tidak digunakan langsung untuk menyimpan Excel
from PIL import Image
import face_recognition
import os
from flask import send_file

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key") # Ambil secret key dari env
app.config["SESSION_TYPE"] = "filesystem" # Menggunakan sistem file untuk sesi
Session(app)

DATABASE = "data_wajah.db"
EXCEL_FILE = "absensi.xlsx"

# Admin credentials dari environment variables
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def get_db_connection():
    """Membuka koneksi database SQLite."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Mengembalikan baris sebagai objek mirip dictionary
    return conn

def init_db():
    """Menginisialisasi skema database jika belum ada."""
    with get_db_connection() as conn:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS faces (
                npm TEXT PRIMARY KEY,
                nama TEXT NOT NULL,
                encoding BLOB NOT NULL
            )'''
        )
        conn.commit()

# Pastikan database terinisialisasi saat aplikasi dimulai
init_db()

@app.route("/login", methods=["GET", "POST"])
def login():
    """Menangani proses login admin."""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Username atau password salah.")
    return render_template('login.html')

@app.route("/logout")
def logout():
    """Menangani proses logout admin."""
    session.clear()
    return redirect(url_for("login"))

def login_required(f):
    """Decorator untuk memastikan pengguna sudah login."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
@login_required
def dashboard():
    """Menampilkan halaman dashboard admin."""
    return render_template("dashboard.html")

# Fungsi 'is_face_already_exists' asli tidak digunakan dalam route yang ada,
# tetapi saya perbaiki jika Anda ingin menggunakannya nanti.
def is_face_already_exists(new_encoding, threshold=0.6):
#     """
#     Memeriksa apakah wajah baru sudah sangat mirip dengan wajah yang ada di database.
#     Menggunakan tabel 'faces', bukan 'wajah'.
#     """
    with get_db_connection() as conn: # Menggunakan fungsi yang benar
        cursor = conn.cursor()
        cursor.execute("SELECT npm, nama, encoding FROM faces") # Nama tabel yang benar
        rows = cursor.fetchall()

    for row in rows:
        existing_encoding = np.frombuffer(row["encoding"], dtype=np.float64)
        distance = face_recognition.face_distance([existing_encoding], new_encoding)[0]
        if distance < threshold:
            return True, row["nama"] # Mengembalikan nama jika ditemukan
    return False, None


@app.route("/tambah", methods=["GET", "POST"])
@login_required
def tambah():
    """
    Menampilkan form tambah data wajah (GET) atau
    memproses data wajah yang dikirim (POST).
    """
    if request.method == "GET":
        return render_template("tambah_data.html")

    # POST ajax expects form-data with 'npm', 'name', 'image'
    npm = request.form.get("npm", "").strip()
    nama = request.form.get("name", "").strip()
    image_data_url = request.form.get("image", "")

    if not (npm and nama and image_data_url):
        return jsonify({"status": "error", "message": "Semua data (NPM, Nama, Gambar) wajib diisi."})

    try:
        # Dekode data gambar dari Base64
        # Format: data:image/jpeg;base64,...
        header, encoded = image_data_url.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        # Mendapatkan encoding wajah dari gambar
        img_np = np.array(img)
        face_encodings = face_recognition.face_encodings(img_np)
        if not face_encodings:
            return jsonify({"status": "error", "message": "Wajah tidak terdeteksi di gambar. Harap posisikan wajah dengan jelas."})

        encoding = face_encodings[0] # Ambil encoding wajah pertama
        encoding_bytes = encoding.tobytes() # Konversi ke bytes untuk disimpan di DB

        # Simpan ke database
        with get_db_connection() as conn:
            # Cek apakah NPM sudah terdaftar untuk mencegah duplikasi
            existing_npm = conn.execute("SELECT 1 FROM faces WHERE npm = ?", (npm,)).fetchone()
            if existing_npm:
                return jsonify({"status": "error", "message": f"NPM {npm} sudah terdaftar. Gunakan NPM lain atau hubungi admin untuk pembaruan."})

            conn.execute("INSERT INTO faces (npm, nama, encoding) VALUES (?, ?, ?)",
                         (npm, nama, encoding_bytes))
            conn.commit()

        return jsonify({"status": "success", "message": f"Data wajah {nama} (NPM: {npm}) berhasil disimpan."})
    except Exception as e:
        print(f"Error saat menambahkan data wajah: {e}")
        return jsonify({"status": "error", "message": "Terjadi kesalahan server saat menyimpan data."})

def get_known_faces():
    """
    Mengambil semua data wajah (NPM, Nama, Encoding) yang tersimpan di database.
    Mengkonversi encoding BLOB kembali ke array NumPy.
    Returns:
        tuple: (list_npm, list_nama, list_encodings_np)
    """
    with get_db_connection() as conn:
        rows = conn.execute("SELECT npm, nama, encoding FROM faces").fetchall()

    list_npm = []
    list_nama = []
    list_encodings_np = []
    for row in rows:
        list_npm.append(row["npm"])
        list_nama.append(row["nama"])
        # Pastikan tipe data numpy sesuai dengan yang disimpan dan diharapkan face_recognition (float64)
        enc = np.frombuffer(row["encoding"], dtype=np.float64)
        list_encodings_np.append(enc)
    return list_npm, list_nama, list_encodings_np

def save_absensi_data_to_excel(npm, nama):
    """
    Menyimpan data absensi ke file Excel.
    Akan memeriksa apakah absensi untuk NPM yang sama sudah ada pada hari yang sama.
    Menggunakan pandas untuk membaca dan menulis file Excel.
    Returns:
        dict: {'status': 'success'/'info'/'error', 'message': 'Pesan'}
    """
    waktu_absen = datetime.now()
    tanggal_hari_ini = waktu_absen.strftime('%Y-%m-%d')
    waktu_lengkap = waktu_absen.strftime('%Y-%m-%d %H:%M:%S')

    df = pd.DataFrame(columns=['NPM', 'Nama', 'Waktu Absen']) # Inisialisasi DataFrame kosong
    if os.path.exists(EXCEL_FILE):
        try:
            # Membaca file Excel yang ada, pastikan kolom NPM dibaca sebagai string
            df = pd.read_excel(EXCEL_FILE, dtype={'NPM': str})
        except Exception as e:
            print(f"Warning: Gagal membaca file Excel '{EXCEL_FILE}'. Membuat file baru. Error: {e}")
            # Jika ada masalah membaca file, perlakukan sebagai file baru
            df = pd.DataFrame(columns=['NPM', 'Nama', 'Waktu Absen'])


    # Cek apakah data absen sudah ada untuk NPM yang sama pada hari ini
    sudah_absen = False
    if not df.empty:
        # Mengubah kolom 'Waktu Absen' menjadi format tanggal untuk perbandingan yang tepat
        # Pastikan kolom 'Waktu Absen' sudah ada dan bukan NaN
        if 'Waktu Absen' in df.columns and not df['Waktu Absen'].isnull().all():
            df['Waktu Absen Date'] = pd.to_datetime(df['Waktu Absen'], errors='coerce').dt.strftime('%Y-%m-%d')
            sudah_absen = ((df['NPM'] == npm) & (df['Waktu Absen Date'] == tanggal_hari_ini)).any()
            df = df.drop(columns=['Waktu Absen Date']) # Hapus kolom sementara
        else:
            print("Warning: Kolom 'Waktu Absen' kosong atau tidak valid, tidak bisa cek duplikasi absensi.")

    if sudah_absen:
        return {"status": "info", "message": f"Absensi untuk {nama} (NPM: {npm}) sudah tercatat hari ini."}

    # Tambahkan data absen baru ke DataFrame
    new_entry = pd.DataFrame([{'NPM': npm, 'Nama': nama, 'Waktu Absen': waktu_lengkap}])
    df = pd.concat([df, new_entry], ignore_index=True) # Menggunakan pd.concat sebagai pengganti df.append

    try:
        # Simpan DataFrame kembali ke file Excel
        df.to_excel(EXCEL_FILE, index=False)
        return {"status": "success", "message": f"Absensi untuk {nama} (NPM: {npm}) berhasil dicatat."}
    except Exception as e:
        print(f"Error saat menyimpan ke file Excel '{EXCEL_FILE}': {e}")
        return {"status": "error", "message": f"Gagal menyimpan absensi ke Excel: {str(e)}."}


@app.route("/absen")
@login_required
def absen_page():
    """
    Menampilkan halaman absensi (GET request).
    Logika deteksi wajah dilakukan di endpoint '/absen/deteksi'.
    """
    return render_template("absen.html")

@app.route("/absen/deteksi", methods=["POST"])
@login_required
def deteksi():
    """
    Menerima gambar dari kamera, mendeteksi wajah,
    membandingkan dengan data tersimpan, dan mencatat absensi.
    """
    # Mengambil data gambar dari form-data (yang umum dari JavaScript FormData)
    image_data_url = request.json.get("image", "")

    if not image_data_url:
        return jsonify({"status": "error", "message": "Tidak ada gambar yang diterima."})

    try:
        # Dekode gambar dari Base64
        header, encoded = image_data_url.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)

        # Deteksi lokasi dan encoding wajah di gambar yang diterima
        face_locations = face_recognition.face_locations(img_np)
        face_encodings = face_recognition.face_encodings(img_np, face_locations)

        if not face_encodings:
            return jsonify({"status": "error", "message": "Wajah tidak terdeteksi di gambar. Silakan posisikan wajah dengan jelas."})

        # Ambil semua data wajah yang sudah dikenal dari database
        known_npms, known_namas, known_encodings = get_known_faces()

        if not known_encodings:
            return jsonify({"status": "info", "message": "Belum ada data wajah yang tersimpan untuk perbandingan."})

        detection_results = []
        # Iterasi melalui setiap wajah yang terdeteksi di gambar
        for (top, right, bottom, left), current_face_encoding in zip(face_locations, face_encodings):
            matches = face_recognition.compare_faces(known_encodings, current_face_encoding, tolerance=0.5)
            face_distances = face_recognition.face_distance(known_encodings, current_face_encoding)

            npm_detected = "Tidak Dikenal"
            nama_detected = "Tidak Dikenal"
            message_for_face = "Wajah tidak dikenali."
            attendance_status = "error" # Default status

            if True in matches:
                # Cari kecocokan terbaik (jarak terpendek)
                best_match_index = np.argmin(face_distances)
                if matches[best_match_index]:
                    npm_detected = known_npms[best_match_index]
                    nama_detected = known_namas[best_match_index]

                    # Simpan absensi ke Excel dan dapatkan statusnya
                    excel_save_result = save_absensi_data_to_excel(npm_detected, nama_detected)
                    attendance_status = excel_save_result["status"]
                    message_for_face = excel_save_result["message"]
                else:
                    message_for_face = "Wajah tidak cocok dengan data yang ada."
            
            # Tambahkan hasil deteksi ke daftar
            detection_results.append({
                'top': top,
                'right': right,
                'bottom': bottom,
                'left': left,
                'npm': npm_detected,
                'name': nama_detected,
                'message': message_for_face,
                'status': attendance_status
            })
        
        # Mengembalikan hasil deteksi wajah pertama yang ditemukan (atau semua jika diinginkan)
        # Untuk tujuan tampilan di halaman HTML, biasanya hanya satu status utama yang ditampilkan.
        if detection_results:
            return jsonify(detection_results[0]) # Mengembalikan hasil deteksi pertama
        else:
            return jsonify({"status": "error", "message": "Tidak ada wajah terdeteksi dalam gambar yang dikirim."})

    except Exception as e:
        print(f"Error selama proses deteksi atau penyimpanan absensi: {e}")
        return jsonify({"status": "error", "message": f"Terjadi kesalahan server saat deteksi: {str(e)}"})
    
@app.route("/unduh_laporan")
@login_required
def unduh_laporan():
    """
    Mengunduh file Excel absensi jika tersedia.
    """
    if os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True)
    else:
        return "File absensi belum tersedia.", 404

if __name__ == "__main__":
    app.run(debug=True)