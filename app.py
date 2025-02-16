from flask import Flask, render_template, request
import pandas as pd
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'  # Directory to save uploaded files
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
    # Extract JID and Expansion from `Journals` table
    sql_dump_journals = sql_dump.split("INSERT INTO `pcv3_elsevier_books`.`Journals`")[1]
    journals_parts = sql_dump_journals.split("VALUES")[1].strip()
    journals_values = journals_parts.strip('();').split(',')
    
    db_row['JID'] = journals_values[0].strip().strip("'")  # JID is the first value
    db_row['Expansion'] = journals_values[3].strip().strip('"')  # Expansion is the fourth value

    # For `journal_attributes` table
    # Extract editionNumber and cslStylePath from `journal_attributes` table
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
def compare_values(excel_row, db_row):
    comparison_results = []

    def normalize_value(value):
        if isinstance(value, str):
            return ' '.join(value.split())  # Removes extra spaces, newlines, and tabs
        return value

    # Compare Formatted ISBN with JID
    comparison_results.append({
        'Excel_key': 'Formatted ISBN',
        'Excel_value': excel_row['Formatted ISBN'],
        'DB_value': db_row['JID'],
        'Status': 'same' if str(excel_row['Formatted ISBN']) == str(db_row['JID']) else 'mismatch'
    })

    # Compare Book Title with Expansion
    comparison_results.append({
        'Excel_key': 'Book Title',
        'Excel_value': excel_row['Book Title'],
        'DB_value': db_row['Expansion'],
        'Status': 'same' if str(excel_row['Book Title']) == str(db_row['Expansion']) else 'mismatch'
    })

    # Compare Edition No. with editionNumber
    comparison_results.append({
        'Excel_key': 'Edition No.',
        'Excel_value': excel_row['Edition No.'],
        'DB_value': db_row['editionNumber'],
        'Status': 'same' if str(excel_row['Edition No.']) == str(db_row['editionNumber']) else 'mismatch'
    })

    # Compare Reference style with cslStylePath using the mapping
    reference_style_mapping = {
        'APA 7th': 'csl/elsevier-apa-7th-edition.csl',
        'Harvard': 'csl/elsevier-harvard.csl',
        'Vancouver Numbered': 'csl/elsevier-vancouver-numbered.csl', 
    }

    excel_reference_style = normalize_value(excel_row['Reference style (Numbered/Harvard/Vancouver Numbered/AMA/APA/Vancouver Name/Year)'])
    db_csl_style_path = normalize_value(db_row['cslStylePath'])

    if excel_reference_style in reference_style_mapping:
        expected_csl_style = reference_style_mapping[excel_reference_style]
        status = 'same' if normalize_value(expected_csl_style) == db_csl_style_path else 'mismatch'
    else:
        status = 'mismatch'

    comparison_results.append({
        'Excel_key': 'Reference style',
        'Excel_value': excel_reference_style,
        'DB_value': db_csl_style_path,
        'Status': status
    })

    return comparison_results

@app.route('/', methods=['GET', 'POST'])
def upload_and_compare():
    if request.method == 'POST':
        # Handle Excel file upload
        if 'excel_file' not in request.files or 'sql_dump_file' not in request.files:
            return "No file part in the request", 400
        
        excel_file = request.files['excel_file']
        sql_dump_file = request.files['sql_dump_file']
        
        if excel_file.filename == '' or sql_dump_file.filename == '':
            return "No file chosen", 400
        
        if excel_file and sql_dump_file:
            # Save uploaded files
            excel_file_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_file.filename)
            sql_dump_file_path = os.path.join(app.config['UPLOAD_FOLDER'], sql_dump_file.filename)
            excel_file.save(excel_file_path)
            sql_dump_file.save(sql_dump_file_path)
            
            # Load Excel data
            config_df = load_excel_config(excel_file_path)
            
            # Load the SQL dump
            sql_dump = parse_sql_dump(sql_dump_file_path)
            
            # Select a specific row from Excel (without loop)
            excel_row = config_df.iloc[0]
            
            # Fetch corresponding SQL dump data for the JID in the Excel row
            FormattedISBN = excel_row['Formatted ISBN']
            db_row = fetch_data_from_sql_dump(FormattedISBN, sql_dump)
            
            if db_row:
                # Compare values and get results
                comparison_results = compare_values(excel_row, db_row)
                
                # Display results
                return render_template('results.html', results=comparison_results)
            else:
                return "No matching data in SQL dump for the provided Formatted ISBN", 400

    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True)
