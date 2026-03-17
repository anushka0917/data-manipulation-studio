import os
import io
import zipfile
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename
import PyPDF2
import pikepdf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import Color

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
    return response

@app.route('/')
def index():
    return render_template('index.html')

def parse_page_ranges(range_str, total_pages):
    pages = set()
    if not range_str.strip():
        return list(range(total_pages))
    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            for p in range(int(start) - 1, int(end)):
                if 0 <= p < total_pages:
                    pages.add(p)
        else:
            p = int(part) - 1
            if 0 <= p < total_pages:
                pages.add(p)
    return sorted(pages)

@app.route('/merge', methods=['POST'])
def merge():
    files = request.files.getlist('pdfs')
    if not files or len(files) < 2:
        return jsonify({'error': 'Please upload at least 2 PDF files.'}), 400
    writer = PyPDF2.PdfWriter()
    for file in files:
        filename = secure_filename(file.filename)
        if not filename.endswith('.pdf'):
            return jsonify({'error': f'{filename} is not a PDF.'}), 400
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return send_file(output, mimetype='application/pdf',
                     as_attachment=True, download_name='merged.pdf')

@app.route('/split', methods=['POST'])
def split():
    file = request.files.get('pdf')
    page_range = request.form.get('range', '').strip()
    if not file:
        return jsonify({'error': 'No file uploaded.'}), 400
    reader = PyPDF2.PdfReader(file)
    total = len(reader.pages)
    pages = parse_page_ranges(page_range, total)
    if not pages:
        return jsonify({'error': 'No valid pages selected.'}), 400
    if len(pages) == 1 or page_range.strip() == '':
        writer = PyPDF2.PdfWriter()
        for p in pages:
            writer.add_page(reader.pages[p])
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return send_file(output, mimetype='application/pdf',
                         as_attachment=True, download_name='split.pdf')
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in pages:
            writer = PyPDF2.PdfWriter()
            writer.add_page(reader.pages[p])
            page_buf = io.BytesIO()
            writer.write(page_buf)
            zf.writestr(f'page_{p + 1}.pdf', page_buf.getvalue())
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype='application/zip',
                     as_attachment=True, download_name='split_pages.zip')

@app.route('/compress', methods=['POST'])
def compress():
    file = request.files.get('pdf')
    quality = request.form.get('quality', 'Balanced')
    if not file:
        return jsonify({'error': 'No file uploaded.'}), 400
    input_bytes = file.read()
    with pikepdf.open(io.BytesIO(input_bytes)) as pdf:
        output = io.BytesIO()
        pdf.save(output, compress_streams=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 stream_decode_level=pikepdf.StreamDecodeLevel.generalized)
    output.seek(0)
    return send_file(output, mimetype='application/pdf',
                     as_attachment=True, download_name='compressed.pdf')

@app.route('/extract', methods=['POST'])
def extract():
    file = request.files.get('pdf')
    page_option = request.form.get('range', 'All pages')
    if not file:
        return jsonify({'error': 'No file uploaded.'}), 400
    reader = PyPDF2.PdfReader(file)
    total = len(reader.pages)
    if page_option == 'First page only':
        pages = [0]
    elif page_option == 'Custom range':
        custom = request.form.get('custom_range', '')
        pages = parse_page_ranges(custom, total)
    else:
        pages = list(range(total))
    extracted = []
    for p in pages:
        text = reader.pages[p].extract_text()
        if text:
            extracted.append(f'--- Page {p + 1} ---\n{text}')
    if not extracted:
        return jsonify({'error': 'No text could be extracted from this PDF.'}), 400
    full_text = '\n\n'.join(extracted)
    output = io.BytesIO(full_text.encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/plain',
                     as_attachment=True, download_name='extracted_text.txt')

@app.route('/rotate', methods=['POST'])
def rotate():
    file = request.files.get('pdf')
    angle_str = request.form.get('angle', 'Rotate 90° clockwise')
    page_range = request.form.get('pages', '').strip()
    if not file:
        return jsonify({'error': 'No file uploaded.'}), 400
    angle_map = {
        'Rotate 90° clockwise': 90,
        'Rotate 90° counter-clockwise': -90,
        'Rotate 180°': 180
    }
    angle = angle_map.get(angle_str, 90)
    reader = PyPDF2.PdfReader(file)
    writer = PyPDF2.PdfWriter()
    total = len(reader.pages)
    pages_to_rotate = parse_page_ranges(page_range, total)
    for i, page in enumerate(reader.pages):
        if i in pages_to_rotate:
            page.rotate(angle)
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return send_file(output, mimetype='application/pdf',
                     as_attachment=True, download_name='rotated.pdf')

def create_watermark(text, position):
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.3))
    c.setFont('Helvetica-Bold', 48)
    if position == 'Diagonal':
        c.saveState()
        c.translate(width / 2, height / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, text)
        c.restoreState()
    elif position == 'Center':
        c.drawCentredString(width / 2, height / 2, text)
    elif position == 'Top-right corner':
        c.setFont('Helvetica-Bold', 28)
        c.drawRightString(width - 30, height - 50, text)
    c.save()
    packet.seek(0)
    return packet

@app.route('/watermark', methods=['POST'])
def watermark():
    file = request.files.get('pdf')
    wm_text = request.form.get('text', 'CONFIDENTIAL').strip()
    position = request.form.get('position', 'Diagonal')
    if not file:
        return jsonify({'error': 'No file uploaded.'}), 400
    if not wm_text:
        wm_text = 'CONFIDENTIAL'
    wm_packet = create_watermark(wm_text, position)
    wm_reader = PyPDF2.PdfReader(wm_packet)
    wm_page = wm_reader.pages[0]
    reader = PyPDF2.PdfReader(file)
    writer = PyPDF2.PdfWriter()
    for page in reader.pages:
        page.merge_page(wm_page)
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return send_file(output, mimetype='application/pdf',
                     as_attachment=True, download_name='watermarked.pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)