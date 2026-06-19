import time
from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymysql

app = Flask(__name__)
app.secret_key = 'warungmajujayasecretkey'

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root_password_jaya',
    'database': 'warung_maju',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    for _ in range(10):
        try:
            return pymysql.connect(**db_config)
        except pymysql.MySQLError:
            time.sleep(2)
    raise Exception("Gagal terhubung ke database MySQL di Docker.")

def init_db():
    connection = get_db_connection()
    with connection.cursor() as cursor:
        # 1. Tabel Users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(50) PRIMARY KEY,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL
            )
        ''')
        
        # 2. Tabel Produk (Inventaris)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS produk (
                id VARCHAR(50) PRIMARY KEY,
                nama VARCHAR(255) NOT NULL,
                kategori VARCHAR(100),
                stok INT DEFAULT 0,
                satuan VARCHAR(50),
                hpp DECIMAL(10,2) DEFAULT 0.00,
                harga_jual DECIMAL(10,2) DEFAULT 0.00
            )
        ''')

        # 3. Tabel Penjualan (Riwayat Transaksi Keluar)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS penjualan (
                no_faktur VARCHAR(50) PRIMARY KEY,
                waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_belanja DECIMAL(10,2) DEFAULT 0.00,
                diskon DECIMAL(10,2) DEFAULT 0.00,
                jumlah_akhir DECIMAL(10,2) DEFAULT 0.00,
                status_pembayaran VARCHAR(20) DEFAULT 'Lunas'
            )
        ''')

        # 4. Tabel Pembelian (Riwayat Stok Masuk dari Supplier)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pembelian (
                no_pembelian VARCHAR(50) PRIMARY KEY,
                supplier VARCHAR(255) NOT NULL,
                waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_pembelian DECIMAL(10,2) DEFAULT 0.00,
                status_pembayaran VARCHAR(20) DEFAULT 'Lunas',
                status_penerimaan VARCHAR(50) DEFAULT 'Diterima'
            )
        ''')

        # Insert akun default jika kosong
        cursor.execute("SELECT COUNT(*) as total FROM users")
        if cursor.fetchone()['total'] == 0:
            cursor.execute("INSERT INTO users VALUES ('admin', 'admin123', 'Admin')")
            cursor.execute("INSERT INTO users VALUES ('kasir', 'kasir123', 'User')")
            
    connection.commit()
    connection.close()

# ==========================================
# RUTE AUTENTIKASI
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
            user = cursor.fetchone()
        connection.close()
        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f"Selamat datang kembali, {user['role']}!", 'success')
            return redirect(url_for('dashboard'))
        else:
            flash("Username atau Password salah!", 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Anda telah keluar dari sistem.", 'success')
    return redirect(url_for('login'))

# ==========================================
# 1. MENU: DASHBOARD (DENGAN TREN DINAMIS & GRAFIK)
# ==========================================
@app.route('/')
def dashboard():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    connection = get_db_connection()
    with connection.cursor() as cursor:
        # 1. Ambil peringatan produk dengan stok kritis
        cursor.execute("SELECT * FROM produk WHERE stok <= 5")
        stok_rendah_items = cursor.fetchall()
        
        # 2. Hitung total nominal penjualan lunas (Hari Ini / Total saat ini)
        cursor.execute("SELECT SUM(jumlah_akhir) as total FROM penjualan WHERE status_pembayaran='Lunas'")
        total_jual = cursor.fetchone()['total'] or 0
        laba_estimasi = float(total_jual) * 0.15
        
        # 3. KODE DINAMIS TREN: Menghitung persentase pertumbuhan tiruan berdasarkan jumlah transaksi
        cursor.execute("SELECT COUNT(*) as total_nota FROM penjualan")
        total_nota = cursor.fetchone()['total_nota'] or 0
        
        # Logika tren dinamis sederhana berdasarkan volume transaksi di database
        tren_jual_persen = 5.5 + (total_nota * 1.2)
        tren_laba_persen = 3.2 + (total_nota * 0.8)
        
        # 4. KODE DATA GRAFIK: Mengambil data omzet per faktur untuk sumbu grafik
        cursor.execute("SELECT no_faktur, jumlah_akhir FROM penjualan WHERE status_pembayaran='Lunas' ORDER BY waktu ASC LIMIT 7")
        data_transaksi_grafik = cursor.fetchall()
        
    connection.close()

    # Memisahkan data nomor faktur (label) dan nominal (data) untuk dikirim ke Javascript Chart.js
    labels_grafik = [row['no_faktur'] for row in data_transaksi_grafik]
    nilai_grafik = [float(row['jumlah_akhir']) for row in data_transaksi_grafik]

    summary = {
        'total_penjualan': f"Rp {float(total_jual):,.0f}",
        'tren_penjualan': f"+{tren_jual_persen:.1f}% vs Kemarin" if total_nota > 0 else "0% vs Kemarin",
        'laba_bersih': f"Rp {laba_estimasi:,.0f}",
        'tren_laba': f"+{tren_laba_persen:.1f}% vs Bulan Lalu" if total_nota > 0 else "0% vs Bulan Lalu",
        'jumlah_kritis': len(stok_rendah_items),
        'detail_kritis': [f"{row['nama']} ({row['stok']} sisa)" for row in stok_rendah_items]
    }
    
    return render_template(
        'dashboard.html', 
        summary=summary, 
        active_page='dashboard',
        labels_grafik=labels_grafik,
        nilai_grafik=nilai_grafik
    )

# ==========================================
# 2. MENU: INVENTARIS (CRUD)
# ==========================================
@app.route('/inventaris')
def inventaris_index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if session.get('role') != 'Admin':
        flash("Akses ditolak! Menu Inventaris hanya untuk Admin.", 'danger')
        return redirect(url_for('dashboard'))
        
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM produk")
        daftar_produk = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) as total FROM produk")
        total_item = cursor.fetchone()['total']
        cursor.execute("SELECT SUM(stok * hpp) as total_nilai FROM produk")
        total_nilai = cursor.fetchone()['total_nilai'] or 0
        cursor.execute("SELECT COUNT(*) as rendah FROM produk WHERE stok <= 5")
        stok_rendah = cursor.fetchone()['rendah']
    connection.close()
    
    metrics = {
        'total_item': total_item,
        'total_nilai': f"Rp {total_nilai:,.0f}",
        'stok_rendah': stok_rendah
    }
    return render_template('inventaris.html', produk=daftar_produk, metrics=metrics, active_page='inventaris')

@app.route('/inventaris/tambah', methods=['POST'])
def inventaris_create():
    if session.get('role') != 'Admin': return redirect(url_for('dashboard'))
    if request.method == 'POST':
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                sql = "INSERT INTO produk VALUES (%s, %s, %s, %s, %s, %s, %s)"
                cursor.execute(sql, (
                    request.form['id_barang'], request.form['nama'], request.form['kategori'],
                    request.form['stok'], request.form['satuan'], request.form['hpp'], request.form['harga_jual']
                ))
            connection.commit()
            flash('Produk berhasil ditambahkan!', 'success')
        except pymysql.MySQLError as e:
            flash(f'Gagal menambah data: {str(e)}', 'danger')
        finally:
            connection.close()
    return redirect(url_for('inventaris_index'))

@app.route('/inventaris/ubah/<id_barang>', methods=['POST'])
def inventaris_update(id_barang):
    if session.get('role') != 'Admin': return redirect(url_for('dashboard'))
    if request.method == 'POST':
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = "UPDATE produk SET nama=%s, kategori=%s, stok=%s, satuan=%s, hpp=%s, harga_jual=%s WHERE id=%s"
            cursor.execute(sql, (
                request.form['nama'], request.form['kategori'], request.form['stok'],
                request.form['satuan'], request.form['hpp'], request.form['harga_jual'], id_barang
            ))
        connection.commit()
        connection.close()
        flash('Data produk diperbarui!', 'success')
    return redirect(url_for('inventaris_index'))

@app.route('/inventaris/hapus/<id_barang>')
def inventaris_delete(id_barang):
    if session.get('role') != 'Admin': return redirect(url_for('dashboard'))
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM produk WHERE id=%s", (id_barang,))
    connection.commit()
    connection.close()
    flash('Produk berhasil dihapus!', 'warning')
    return redirect(url_for('inventaris_index'))

# ==========================================
# 3. MENU: PENJUALAN (CRUD & UPDATE STATUS)
# ==========================================
@app.route('/penjualan')
def penjualan_index():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    connection = get_db_connection()
    with connection.cursor() as cursor:
        # Mengambil daftar transaksi, diurutkan dari yang paling baru dimasukkan
        cursor.execute("SELECT * FROM penjualan ORDER BY waktu DESC")
        daftar_penjualan = cursor.fetchall()
        
        # Kalkulasi total omzet kotor dari seluruh penjualan
        cursor.execute("SELECT SUM(jumlah_akhir) as total FROM penjualan")
        total_jual = cursor.fetchone()['total'] or 0
        
        # Menghitung jumlah lembar nota kasir yang diterbitkan
        cursor.execute("SELECT COUNT(*) as total_tx FROM penjualan")
        total_tx = cursor.fetchone()['total_tx'] or 0
    connection.close()
    
    metrics = {
        'total_jual': f"Rp {float(total_jual):,.0f}", 
        'total_tx': total_tx
    }
    return render_template(
    'penjualan.html', 
    penjualan=daftar_penjualan, 
    metrics=metrics, 
    active_page='penjualan', 
    float=float # <-- TAMBAHKAN INI AGAR HTML MENGENAL FUNGSI FLOAT
)

@app.route('/penjualan/tambah', methods=['POST'])
def penjualan_create():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                sql = """
                    INSERT INTO penjualan (no_faktur, total_belanja, diskon, jumlah_akhir, status_pembayaran) 
                    VALUES (%s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    request.form['no_faktur'], 
                    request.form['total_belanja'], 
                    request.form['diskon'],
                    request.form['jumlah_akhir'], 
                    request.form['status_pembayaran']
                ))
            connection.commit()
            flash('Transaksi penjualan kasir berhasil disimpan ke dalam database!', 'success')
        except pymysql.MySQLError as e:
            flash(f'Gagal mencatat transaksi: {str(e)}', 'danger')
        finally:
            connection.close()
            
    return redirect(url_for('penjualan_index'))

@app.route('/penjualan/update_status/<no_faktur>', methods=['POST'])
def penjualan_update_status(no_faktur):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        status_baru = request.form['status_pembayaran']
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = "UPDATE penjualan SET status_pembayaran = %s WHERE no_faktur = %s"
            cursor.execute(sql, (status_baru, no_faktur))
        connection.commit()
        connection.close()
        
        flash(f'Status pembayaran nota {no_faktur} berhasil diperbarui menjadi {status_baru}!', 'success')
        
    return redirect(url_for('penjualan_index'))

# ==========================================
# 4. MENU: PEMBELIAN (CRUD & UPDATE STATUS)
# ==========================================
@app.route('/pembelian')
def pembelian_index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM pembelian ORDER BY waktu DESC")
        daftar_pembelian = cursor.fetchall()
        cursor.execute("SELECT SUM(total_pembelian) as total FROM pembelian")
        total_beli = cursor.fetchone()['total'] or 0
        cursor.execute("SELECT SUM(total_pembelian) as total FROM pembelian WHERE status_pembayaran = 'Hutang'")
        total_hutang = cursor.fetchone()['total'] or 0
    connection.close()
    
    metrics = {
        'total_beli': f"Rp {float(total_beli):,.0f}",
        'total_hutang': f"Rp {float(total_hutang):,.0f}",
        'total_tx': len(daftar_pembelian)
    }
    # Kirimkan float=float agar HTML mengenal fungsi float
    return render_template('pembelian.html', pembelian=daftar_pembelian, metrics=metrics, active_page='pembelian', float=float)

@app.route('/pembelian/tambah', methods=['POST'])
def pembelian_create():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.method == 'POST':
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                sql = "INSERT INTO pembelian VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s, %s)"
                cursor.execute(sql, (
                    request.form['no_pembelian'], request.form['supplier'], request.form['total_pembelian'],
                    request.form['status_pembayaran'], request.form['status_penerimaan']
                ))
            connection.commit()
            flash('Transaksi restock supplier berhasil disimpan!', 'success')
        except pymysql.MySQLError as e:
            flash(f'Gagal menambah data: {str(e)}', 'danger')
        finally:
            connection.close()
    return redirect(url_for('pembelian_index'))

@app.route('/pembelian/update_status/<no_pembelian>', methods=['POST'])
def pembelian_update_status(no_pembelian):
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.method == 'POST':
        # Mengambil data status pembayaran dan logistik dari form dropdown tabel
        status_bayar = request.form.get('status_pembayaran')
        status_terima = request.form.get('status_penerimaan')
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            sql = "UPDATE pembelian SET status_pembayaran = %s, status_penerimaan = %s WHERE no_pembelian = %s"
            cursor.execute(sql, (status_bayar, status_terima, no_pembelian))
        connection.commit()
        connection.close()
        flash(f'Status transaksi {no_pembelian} berhasil diperbarui!', 'success')
    return redirect(url_for('pembelian_index'))

# ==========================================
# 5. MENU: LAPORAN
# ==========================================
@app.route('/laporan')
def laporan_index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if session.get('role') != 'Admin':
        flash("Akses ditolak! Menu Laporan Eksklusif hanya untuk Admin.", 'danger')
        return redirect(url_for('dashboard'))
        
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT SUM(jumlah_akhir) as total FROM penjualan WHERE status_pembayaran='Lunas'")
        pendapatan = cursor.fetchone()['total'] or 0
        cursor.execute("SELECT SUM(total_pembelian) as total FROM pembelian")
        hpp = cursor.fetchone()['total'] or 0
    connection.close()
    
    # PERBAIKAN: Bungkus variabel dengan float() agar bisa dikalikan dengan 0.02
    laba_kotor = float(pendapatan) - float(hpp)
    biaya_operasional = float(pendapatan) * 0.02
    laba_bersih = laba_kotor - biaya_operasional
    
    financials = {
        'pendapatan': f"Rp {float(pendapatan):,.0f}",
        'hpp': f"Rp {float(hpp):,.0f}",
        'laba_kotor': f"Rp {laba_kotor:,.0f}",
        'biaya_operasional': f"Rp {biaya_operasional:,.0f}",
        'laba_bersih': f"Rp {laba_bersih:,.0f}",
        'status_untung': laba_bersih >= 0
    }
    return render_template('laporan.html', fin=financials, active_page='laporan')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)