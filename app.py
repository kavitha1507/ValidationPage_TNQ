from flask import Flask, render_template, request
import pandas as pd
import os
import re
import html

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'  
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Load Excel file
def load_excel_config(file_path):
    df = pd.read_excel(file_path)
    
    # Clean the column names by removing any newlines, extra spaces
    df.columns = df.columns.str.strip().str.replace(r'[\r\n]+', ' ', regex=True)  # Replaces newlines with space
    
    return df
# Load and parse SQL dump
def parse_sql_dump(file_path):
    with open(file_path, 'r') as file:
        sql_data = file.read()
    return sql_data

# Fetch single data from SQL dump based on JID
def fetch_data_from_sql_dump(jid, sql_dump):
    db_row = {}

    # For `Journals` table
    sql_dump_journals = sql_dump.split("INSERT INTO `pcv3_elsevier_books`.`Journals`")[1]
    journals_parts = sql_dump_journals.split("VALUES")[1].strip()
    journals_values = journals_parts.strip('();').split(',')
    
    db_row['JID'] = journals_values[0].strip().strip("'")  # JID is the first value
    db_row['Expansion'] = journals_values[3].strip().strip('"').strip("'")  # Expansion is the fourth value

    # For `journal_attributes` table
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
    
    return db_row

# Compare values and format the result
def escape_for_db(text):
    if not isinstance(text, str):
        return text

    replacements = {
        "'": "\\'",
        "®": "&#xae;",
        "–": "&#x2013;",   # en dash
        "’": "\\'",        # curly apostrophe to escaped straight apostrophe
        "“": "&ldquo;",
        "”": "&rdquo;",
        "©": "&#xa9;",
        "™": "&#x2122;",
        # Add more as needed
    }

    for char, html_entity in replacements.items():
        text = text.replace(char, html_entity)

    return text


def compare_values(excel_row, db_row):
    comparison_results = []

    def normalize_value(value):
        if isinstance(value, str):
            return ' '.join(value.split())
        return value

    # Compare Formatted ISBN with JID
    comparison_results.append({
        'Excel_key': 'Formatted ISBN',
        'Excel_value': excel_row['Formatted ISBN'],
        'DB_value': db_row['JID'],
        'Status': 'same' if str(excel_row['Formatted ISBN']) == str(db_row['JID']) else 'mismatch',
        'Error': ''
    })

    # Compare Book Title with Expansion (escaped)
    excel_title = normalize_value(str(excel_row['Book Title']))
    db_title = normalize_value(str(db_row['Expansion']))
    expected_title = escape_for_db(excel_title)
    
    status = 'same' if expected_title == db_title else 'mismatch'
    error_msg = ''
    if status == 'mismatch':
        error_msg = f"Expected: {expected_title}"

    comparison_results.append({
        'Excel_key': 'Book Title',
        'Excel_value': excel_title,
        'DB_value': db_title,
        'Status': status,
        'Error': error_msg
    })

    # Edition No.
    comparison_results.append({
        'Excel_key': 'Edition No.',
        'Excel_value': excel_row['Edition No.'],
        'DB_value': db_row['editionNumber'],
        'Status': 'same' if str(excel_row['Edition No.']) == str(db_row['editionNumber']) else 'mismatch',
        'Error': ''
    })

    # Reference style
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

    return comparison_results




@app.route('/', methods=['GET', 'POST'])
def upload_and_compare():
    if request.method == 'POST':
        # Check if both files are provided
        if 'excel_file' not in request.files or 'sql_dump_file' not in request.files:
            return "No file part in the request", 400

        excel_file = request.files['excel_file']
        sql_dump_file = request.files['sql_dump_file']

        # Check if both files are selected
        if excel_file.filename == '' or sql_dump_file.filename == '':
            return "No file chosen", 400

        if excel_file and sql_dump_file:
            # Save files to the uploads directory
            excel_file_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_file.filename)
            sql_dump_file_path = os.path.join(app.config['UPLOAD_FOLDER'], sql_dump_file.filename)
            excel_file.save(excel_file_path)
            sql_dump_file.save(sql_dump_file_path)

            # Load Excel and SQL data
            config_df = load_excel_config(excel_file_path)
            sql_dump = parse_sql_dump(sql_dump_file_path)

            # Process only the first row from Excel
            excel_row = config_df.iloc[0]
            formatted_isbn = str(excel_row['Formatted ISBN'])

            # Fetch data from SQL dump based on Formatted ISBN
            db_row = fetch_data_from_sql_dump(formatted_isbn, sql_dump)

            if db_row:
                # Compare and get results including error details
                comparison_results = compare_values(excel_row, db_row)

                # Render the result page with detailed comparison
                return render_template('results.html', results=comparison_results)
            else:
                return f"No matching data in SQL dump for Formatted ISBN: {formatted_isbn}", 400

    return render_template('upload.html')


if __name__ == '__main__':
    app.run(debug=True)
