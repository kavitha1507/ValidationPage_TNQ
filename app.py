from flask import Flask, render_template, request
import pandas as pd
import os
import re
import html
import boto3
from botocore.exceptions import NoCredentialsError
import nacl.secret
import nacl.utils
import base64
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# Read and decode key from .env
key_base64 = os.getenv('LIBSODIUM_KEY')
if not key_base64:
    raise ValueError("LIBSODIUM_KEY is missing in the .env file")

key = base64.b64decode(key_base64)
box = nacl.secret.SecretBox(key)
key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
box = nacl.secret.SecretBox(key)

key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)  # 32 bytes
box = nacl.secret.SecretBox(key)

def encrypt_with_libsodium(message: str) -> str:
    nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
    encrypted = box.encrypt(message.encode(), nonce)
    return base64.b64encode(encrypted).decode()

def decrypt_with_libsodium(encoded_cipher: str) -> str:
    cipher = base64.b64decode(encoded_cipher)
    decrypted = box.decrypt(cipher)
    return decrypted.decode()

def generate_presigned_url(bucket, key, expiration=3600):
    s3_client = boto3.client('s3')
    try:
        url = s3_client.generate_presigned_url('get_object',
                                               Params={'Bucket': bucket, 'Key': key},
                                               ExpiresIn=expiration)
        return url
    except NoCredentialsError:
        return None

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def load_excel_config(file_path):
    df = pd.read_excel(file_path)
    df.columns = df.columns.str.strip().str.replace(r'[\r\n]+', ' ', regex=True)
    return df

def parse_sql_dump(file_path):
    with open(file_path, 'r') as file:
        sql_data = file.read()
    return sql_data

def fetch_data_from_sql_dump(jid, sql_dump):
    db_row = {}
    try:
        sql_dump_journals = sql_dump.split("INSERT INTO `pcv3_elsevier_books`.`Journals`")[1]
        journals_parts = sql_dump_journals.split("VALUES")[1].strip()
        journals_values = journals_parts.strip('();').split(',')

        db_row['JID'] = journals_values[0].strip().strip("'")
        db_row['Expansion'] = journals_values[3].strip().strip('"').strip("'")

        sql_dump_attributes = sql_dump.split("INSERT INTO `pcv3_elsevier_books`.`journal_attributes`")[1]
        attributes_lines = sql_dump_attributes.split("VALUES")[1].strip().split("),")
        for line in attributes_lines:
            values = line.strip().strip('();').split(',')
            attr_key = values[1].strip().strip("'")
            attr_value = values[2].strip().strip("'")

            if attr_key == 'editionNumber':
                db_row['editionNumber'] = attr_value
            elif attr_key == 'cslStylePath':
                db_row['cslStylePath'] = attr_value

        db_row['coverImagePath'] = next((line.split(',')[2].strip().strip("'") for line in attributes_lines if 'coverImagePath' in line), '')
    except Exception as e:
        print(f"Error parsing SQL: {e}")

    return db_row

def normalize_value(val):
    import pandas as pd
    if pd.isna(val):
        return ''
    if isinstance(val, float) and val.is_integer():
        return str(int(val))  # Convert 1.0 → '1'
    return ' '.join(str(val).split())
    
def normalize_value(val):
    import pandas as pd
    if pd.isna(val) or str(val).strip().upper() in ['NA', '']:
        return 'NA'
    return ' '.join(str(val).split())

def escape_for_db(text):
    if not isinstance(text, str):
        return text

    replacements = {
        "'": "\\'",
        "®": "&#xae;",
        "–": "&#x2013;",
        "’": "\\'",
        "“": "&ldquo;",
        "”": "&rdquo;",
        "©": "&#xa9;",
        "™": "&#x2122;"
    }

    for char, html_entity in replacements.items():
        text = text.replace(char, html_entity)

    return text

def compare_values(excel_row, db_row):
    comparison_results = []

    def normalize_value(val):
        import pandas as pd
        if pd.isna(val):
            return ''
        if isinstance(val, float) and val.is_integer():
            return str(int(val))  # convert 1.0 to '1'
        return ' '.join(str(val).split())  # remove extra whitespace

    # --- Compare Formatted ISBN with JID (with space validation) ---
    excel_jid = normalize_value(excel_row['Formatted ISBN']).strip()
    db_jid_raw = db_row['JID']
    db_jid = normalize_value(db_jid_raw).strip()

    status = 'same' if excel_jid == db_jid else 'mismatch'

# Detect leading/trailing spaces in DB value
    if db_jid_raw != db_jid:
        error_msg = f"DB JID has leading/trailing spaces. Expected: '{excel_jid}', Found: '{db_jid_raw}'"
    elif status == 'mismatch':
        error_msg = f"Expected: '{excel_jid}'"
    else:
        error_msg = ''

    comparison_results.append({
    'Excel_key': 'Formatted ISBN',
    'Excel_value': excel_jid,
    'DB_value': db_jid_raw,
    'Status': status,
    'Error': error_msg
    })
        # Compare Book Title
    excel_title = normalize_value(excel_row['Book Title'])
    db_title = normalize_value(db_row['Expansion'])
    expected_title = escape_for_db(excel_title)

    title_status = 'same' if expected_title == db_title else 'mismatch'
    title_error = f"Expected: {expected_title}" if title_status == 'mismatch' else ''

    comparison_results.append({
        'Excel_key': 'Book Title',
        'Excel_value': excel_title,
        'DB_value': db_title,
        'Status': title_status,
        'Error': title_error
    })

    # Compare Edition No.
    excel_edition = normalize_value(excel_row['Edition No.'])
    db_edition = normalize_value(db_row['editionNumber'])

    edition_status = 'same' if excel_edition == db_edition else 'mismatch'
    edition_error = f"Expected: {excel_edition}" if edition_status == 'mismatch' else ''

    comparison_results.append({
        'Excel_key': 'Edition No.',
        'Excel_value': excel_edition,
        'DB_value': db_edition,
        'Status': edition_status,
        'Error': edition_error
    })

    # Reference Style
    reference_style_mapping = {
        'APA 7th': 'csl/elsevier-apa-7th-edition.csl',
        'Harvard': 'csl/elsevier-harvard.csl',
        'Vancouver Numbered': 'csl/elsevier-vancouver-numbered.csl',
        'Numbered': 'csl/elsevier-with-titles.csl',
        'AMA': 'csl/ama.csl',
        'Embellished_Vancouver': 'csl/elsevier-vancouver-embellish.csl',
        'Vancouver_nameAndYear': 'csl/elsevier-vancouver-author-date.csl',
        'APA': 'csl/apa.csl',
        'Saunders_nameAndYear':'csl/saunders-author.csl',
        'Saunders_numbered':'csl/saunders-number.csl',
        'ACS':'csl/acs.csl',
        'ACS_nameAndYear':'csl/acs-author-date.csl'
    }

    excel_ref = normalize_value(excel_row['Reference style (Numbered/Harvard/Vancouver Numbered/AMA/APA/Vancouver Name/Year)'])
    db_csl = normalize_value(db_row['cslStylePath'])
    expected_csl = reference_style_mapping.get(excel_ref, '')

    ref_status = 'same' if expected_csl == db_csl else 'mismatch'
    ref_error = f"Expected: {expected_csl}" if ref_status == 'mismatch' else ''

    comparison_results.append({
        'Excel_key': 'Reference style',
        'Excel_value': excel_ref,
        'DB_value': db_csl,
        'Status': ref_status,
        'Error': ref_error
    })

    # Journal Cover Image
    excel_cover = normalize_value(excel_row['Journal cover image* (*Attach cover image)'])
    db_cover = normalize_value(db_row.get('coverImagePath', ''))

    cover_result = {
    'Excel_key': 'Journal cover image',
    'Excel_value': excel_cover,
    'DB_value': db_cover,
    'Status': '',
    'Error': '',
    'Image_URL': ''
    }

    if excel_cover == 'NA':
        cover_result['Status'] = 'info'
        cover_result['Error'] = 'Cover image not attached'
    elif excel_cover.upper() == 'ATTACHED':
            if db_cover:
             cover_result['Status'] = 'same'
             cover_result['Image_URL'] = f"https://pcv3-elsbook-live.s3.amazonaws.com/{db_cover}"
    else:
        cover_result['Status'] = 'mismatch'
        cover_result['Error'] = 'Cover not attached in configuration ticket'

    comparison_results.append(cover_result)

    if db_cover:
        s3_url = generate_presigned_url('pcv3-elsbook-live', db_cover)
        cover_result['Image_URL'] = s3_url

     # PM name
        excel_PM = normalize_value(excel_row['New PM Internal/External'])
        db_PM_encrypted = normalize_value(db_row.get('projectManagerName', ''))

        try:
            db_PM_decrypted = decrypt_with_libsodium(db_PM_encrypted)
            pm_status = 'same' if db_PM_decrypted == excel_PM else 'mismatch'
            pm_error = '' if pm_status == 'same' else f"Expected: {excel_PM}"

            comparison_results.append({
            'Excel_key': 'New PM Internal/External',
            'Excel_value': excel_PM,
            'DB_value': db_PM_encrypted,
            'Decrypted_value': db_PM_decrypted,
            'Status': pm_status,
            'Error': pm_error,
            'Needs_Decrypt': True  # for UI
            })
        except Exception as e:
            comparison_results.append({
            'Excel_key': 'New PM Internal/External',
            'Excel_value': excel_PM,
            'DB_value': db_PM_encrypted,
            'Status': 'error',
            'Error': str(e),
            'Needs_Decrypt': True
            })


    return comparison_results

@app.route('/', methods=['GET', 'POST'])
def upload_and_compare():
    if request.method == 'POST':
        if 'excel_file' not in request.files or 'sql_dump_file' not in request.files:
            return "No file part in the request", 400

        excel_file = request.files['excel_file']
        sql_dump_file = request.files['sql_dump_file']

        if excel_file.filename == '' or sql_dump_file.filename == '':
            return "No file chosen", 400

        if excel_file and sql_dump_file:
            excel_file_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_file.filename)
            sql_dump_file_path = os.path.join(app.config['UPLOAD_FOLDER'], sql_dump_file.filename)
            excel_file.save(excel_file_path)
            sql_dump_file.save(sql_dump_file_path)

            config_df = load_excel_config(excel_file_path)
            sql_dump = parse_sql_dump(sql_dump_file_path)

            excel_row = config_df.iloc[0]
            formatted_isbn = str(excel_row['Formatted ISBN'])
            db_row = fetch_data_from_sql_dump(formatted_isbn, sql_dump)

            if db_row:
                comparison_results = compare_values(excel_row, db_row)
                return render_template('results.html', results=comparison_results)
            else:
                return f"No matching data in SQL dump for Formatted ISBN: {formatted_isbn}", 400

    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True)


@app.route('/decrypt', methods=['POST'])
def decrypt_handler():
    from flask import redirect, url_for, flash
    ciphertext = request.form['ciphertext']
    try:
        decrypted = decrypt_with_libsodium(ciphertext)
        flash(f'Decrypted value: {decrypted}')
    except Exception as e:
        flash(f'Decryption failed: {str(e)}')
    return redirect(url_for('upload_and_compare'))