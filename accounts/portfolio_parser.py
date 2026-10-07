# portfolio_parser.py
import re
import pandas as pd
import pdfplumber
from openpyxl import load_workbook

class PortfolioParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.metadata = {
            "fund_manager": None,
            "aum": None,
            "scheme_name": None
        }
        self.holdings = []

    def parse_excel(self):
        """Parses messy Excel portfolio disclosures dynamically searching for anchors"""
        try:
            # Read all sheets or primary sheet
            xl = pd.ExcelFile(self.file_path)
            for sheet_name in xl.sheet_names:
                df = xl.parse(sheet_name, header=None)
                
                data_started = False
                headers = []
                
                for idx, row in df.iterrows():
                    row_str = " ".join([str(x).strip() for x in row.values if pd.notna(x)])
                    
                    # 1. Extract Metadata via Regex Anchors
                    if "fund manager" in row_str.lower():
                        match = re.search(r"(?:fund manager.*?)(?::|-|\s)(.*)", row_str, re.IGNORECASE)
                        if match: self.metadata["fund_manager"] = match.group(1).strip()
                        
                    if "aum" in row_str.lower() or "assets under management" in row_str.lower():
                        match = re.search(r"(?:aum|assets under management.*?)(?::|-|\s|Rs\.?)([\d.,\s]+)", row_str, re.IGNORECASE)
                        if match: self.metadata["aum"] = match.group(1).strip()

                    # 2. Detect Table Header Start
                    if not data_started and ("isin" in row_str.lower() or "industry" in row_str.lower() or "issuer" in row_str.lower()):
                        headers = [str(h).strip().lower().replace(" ", "_") for h in row.values if pd.notna(h)]
                        data_started = True
                        continue
                    
                    # 3. Collect Data Rows
                    if data_started:
                        # Break if we hit grand totals or summary signatures
                        if "total" in row_str.lower() and len(self.holdings) > 5:
                            break
                        
                        # Filter out empty spacer rows
                        valid_vals = [v for v in row.values if pd.notna(v)]
                        if len(valid_vals) >= 3:
                            row_dict = {}
                            for i, val in enumerate(row.values[:len(headers)]):
                                if i < len(headers):
                                    row_dict[headers[i]] = val
                            self.holdings.append(row_dict)
                            
            return {"metadata": self.metadata, "holdings": pd.DataFrame(self.holdings)}
        except Exception as e:
            return {"error": f"Excel processing failed: {str(e)}"}

    def parse_pdf(self):
        """Extracts structured grids from multi-page PDF portfolio documents"""
        try:
            with pdfplumber.open(self.file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    
                    # Extract Metadata from free text on the page
                    for line in text.split('\n'):
                        if "fund manager" in line.lower() and not self.metadata["fund_manager"]:
                            self.metadata["fund_manager"] = line.split(":")[-1].strip()
                        if ("aum" in line.lower() or "assets" in line.lower()) and not self.metadata["aum"]:
                            self.metadata["aum"] = line.split(":")[-1].strip()

                    # Extract tabular grids
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        
                        # Find header row inside the table
                        header_idx = 0
                        is_portfolio_table = False
                        for r_idx, row in enumerate(table):
                            row_joined = " ".join([str(c) for c in row if c]).lower()
                            if "isin" in row_joined or "industry" in row_joined or "quantity" in row_joined:
                                header_idx = r_idx
                                is_portfolio_table = True
                                break
                        
                        if is_portfolio_table:
                            raw_headers = [str(c).strip().lower().replace("\n", " ").replace(" ", "_") for c in table[header_idx] if c]
                            
                            for row in table[header_idx + 1:]:
                                if not row or not any(row): continue
                                # Clean up formatting artifacts
                                clean_row = [str(c).strip().replace("\n", " ") if c else "" for c in row]
                                
                                # Terminate on totals boundary
                                if "total" in " ".join(clean_row).lower():
                                    continue
                                
                                # Match columns dynamically
                                item = {}
                                for idx, h in enumerate(raw_headers):
                                    if idx < len(clean_row):
                                        item[h] = clean_row[idx]
                                if item:
                                    self.holdings.append(item)
                                    
            return {"metadata": self.metadata, "holdings": pd.DataFrame(self.holdings)}
        except Exception as e:
            return {"error": f"PDF processing failed: {str(e)}"}

# Basic execution pipeline wrapper
def process_portfolio(file_path):
    parser = PortfolioParser(file_path)
    if file_path.endswith(('.xlsx', '.xls')):
        return parser.parse_excel()
    elif file_path.endswith('.pdf'):
        return parser.parse_pdf()
    else:
        return {"error": "Unsupported file format."}
